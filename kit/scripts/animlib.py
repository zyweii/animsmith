"""animsmith shared helpers: the vault path, categories and IDs, ffmpeg wrappers (GPU first) and sheets.

    from animlib import resolve_vault, CATEGORIES, next_id, claim_id, probe, extract_frames, sheet

The vault path comes only from --vault or the ANIMSMITH_VAULT environment variable; nothing here hard-codes one.

GPU rule: video decode uses `-hwaccel cuda` (override the accelerator name with ANIMSMITH_HWACCEL, for tests).
Errors carry a `code` the callers report:
  gpu_failed                the GPU path itself is broken (GpuError): the caller stops with exit 4 and reruns with
                            gpu=False only when the user says so.
  nvdec_unsupported_format  the GPU works but NVDEC can't decode this file's format (H.264 4:4:4 or 10-bit, ...)
                            (NvdecUnsupported): a per-file failure; the user decides whether to decode that one file
                            on the CPU. ffmpeg itself would quietly fall back to the CPU here, so this is caught
                            before (probe) and after (its log) the decode, and any CPU frames are thrown away.
  decode_errors             the file is corrupt beyond a few frames (DecodeError): a per-file failure.
  probe_failed, bad_crop, bad_trim, error: other per-file failures.
Codecs with no NVDEC decoder at all (gif, png, ...) decode on the CPU because no GPU path exists for them; that
is recorded in `decode` and `notes`, never a silent fallback.

Stdlib + numpy + Pillow (Pillow is imported only by the image helpers, so stdlib-only callers such as
anim_find work without it); ffmpeg/ffprobe on PATH.
"""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

LIB = "11_ASSET_LIBRARY"
_PIL_NAMES = ("Image", "ImageDraw", "ImageFont", "ImageOps")


def __getattr__(name):
    """animlib.Image etc. import Pillow on first use (module-level __getattr__, PEP 562)."""
    if name in _PIL_NAMES:
        import importlib
        mod = importlib.import_module("PIL." + name)
        globals()[name] = mod
        return mod
    raise AttributeError(f"module 'animlib' has no attribute {name!r}")


def _pil():
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    return Image, ImageDraw, ImageFont, ImageOps

# cat -> prefix, folder (relative to 11_ASSET_LIBRARY), hub note name, facet tag
CATEGORIES = {
    "combat": {"prefix": "ANIM-COMBAT", "folder": "Animation/Combat", "hub": "Category_Combat_Animation",
               "tag": "asset/combat"},
    "weapon": {"prefix": "ANIM-WEAPON", "folder": "Animation/Weapon", "hub": "Category_Weapon_Animation",
               "tag": "asset/weapon"},
    "ability": {"prefix": "ANIM-ABILITY", "folder": "Animation/Ability", "hub": "Category_Ability_Animation",
                "tag": "asset/ability"},
    "loco": {"prefix": "ANIM-LOCO", "folder": "Animation/Locomotion", "hub": "Category_Locomotion_Animation",
             "tag": "asset/locomotion"},
    "world": {"prefix": "ANIM-WORLD", "folder": "Animation/World", "hub": "Category_World_Animation",
              "tag": "asset/world"},
    "camera": {"prefix": "ANIM-CAMERA", "folder": "Animation/Camera", "hub": "Category_Camera_Animation",
               "tag": "asset/camera"},
    # (contract addendum) hit-reacts, knockdowns, get-ups
    "reaction": {"prefix": "ANIM-REACTION", "folder": "Animation/Reaction", "hub": "Category_Reaction_Animation",
                 "tag": "asset/reaction"},
}

# words a user may type for a category (folder names, sidecar first words)
CATEGORY_ALIASES = {"locomotion": "loco", "movement": "loco", "weapons": "weapon", "abilities": "ability",
                    "reactions": "reaction", "react": "reaction", "cam": "camera"}

IDS_FILE = "Animation/_ids.json"


def category_of(word):
    """A user word -> category key, or None."""
    w = (word or "").strip().lower().strip(":;,.-—()[]")
    if w in CATEGORIES:
        return w
    return CATEGORY_ALIASES.get(w)


# ---------------------------------------------------------------- vault

def resolve_vault(arg=None):
    """The vault root: arg, else env ANIMSMITH_VAULT. It must hold 11_ASSET_LIBRARY, else SystemExit."""
    raw = arg if arg else os.environ.get("ANIMSMITH_VAULT", "")
    raw = (raw or "").strip().strip('"').strip("'").strip()
    if not raw:
        raise SystemExit("animsmith: no vault. Pass --vault <vault root> or set ANIMSMITH_VAULT to the folder "
                         "that holds 11_ASSET_LIBRARY.")
    p = Path(raw).expanduser()
    if not (p / LIB).is_dir():
        raise SystemExit(f"animsmith: '{p}' has no {LIB} folder. Pass --vault <vault root> or set "
                         f"ANIMSMITH_VAULT to the folder that holds {LIB}.")
    return p.resolve()


def lib(vault):
    return Path(vault) / LIB


def _ids_path(vault):
    return lib(vault) / IDS_FILE


def read_ids(vault):
    p = _ids_path(vault)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float, str)) and str(v).isdigit()}
    except (ValueError, OSError):
        return {}


_ID_DIR = re.compile(r"^[A-Za-z]+(?:-[A-Za-z]+)*-\d{4,}")
_SKIP_DIRS = {"frames", "sheets", "source", "analysis", ".obsidian", ".git", ".trash", "__pycache__"}


def _max_on_disk(vault, prefix):
    """Highest number used by any name with the prefix in 11_ASSET_LIBRARY. Folders named like an ID (a media or
    spec folder) count by their name but are never walked into, and frames/sheets/source folders are skipped, so a
    claim never lists thousands of frame JPEGs."""
    rx = re.compile(r"^(?:Breakdown_)?" + re.escape(prefix) + r"-(\d{4,})")
    best = 0
    root = lib(vault)
    if not root.is_dir():
        return 0
    for _dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for name in dirnames:
            m = rx.match(name)
            if m:
                best = max(best, int(m.group(1)))
            if not (_ID_DIR.match(name) or name in _SKIP_DIRS):
                keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            m = rx.match(name)
            if m:
                best = max(best, int(m.group(1)))
    return best


def id_number(ID):
    m = re.search(r"-(\d{4,})$", ID)
    return int(m.group(1)) if m else None


def prefix_of(ID):
    return ID.rsplit("-", 1)[0]


def next_id(vault, cat, skip=0):
    """Next free ID for the category: max(registry, every name in 11_ASSET_LIBRARY with the prefix) + 1 (+ skip,
    which dry runs use to number several files). Read-only."""
    prefix = CATEGORIES[cat]["prefix"]
    n = max(read_ids(vault).get(prefix, 0), _max_on_disk(vault, prefix)) + 1 + skip
    return f"{prefix}-{n:04d}"


def claim_id(vault, ID):
    """Make _media/anim/<ID> (exist_ok=False: the lock), then record the number in Animation/_ids.json.
    Raises FileExistsError if another run or a stray folder holds it."""
    mdir = lib(vault) / "_media" / "anim" / ID
    mdir.parent.mkdir(parents=True, exist_ok=True)
    mdir.mkdir(exist_ok=False)
    p = _ids_path(vault)
    ids = read_ids(vault)
    prefix, num = prefix_of(ID), id_number(ID)
    if num is not None and ids.get(prefix, 0) < num:
        ids[prefix] = num
        p.parent.mkdir(parents=True, exist_ok=True)
        _write_ids(p, ids)
    return mdir


def _write_ids(p, ids):
    """Rewrite the registry keeping its key order and line endings."""
    nl = "\n"
    if p.is_file() and b"\r\n" in p.read_bytes():
        nl = "\r\n"
    text = json.dumps(ids, indent=1).replace("\n", nl) + nl
    p.write_bytes(text.encode("utf-8"))


def release_id(vault, ID):
    """Rollback helper: lower the registry back if it still records exactly this ID (nothing claimed after it)."""
    ids = read_ids(vault)
    prefix, num = prefix_of(ID), id_number(ID)
    if ids.get(prefix) == num:
        ids[prefix] = num - 1
        _write_ids(_ids_path(vault), ids)


# ---------------------------------------------------------------- json

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def write_json(path, data, indent=1):
    Path(path).write_bytes(json.dumps(data, indent=indent, ensure_ascii=False).encode("utf-8"))
    return Path(path)


# ---------------------------------------------------------------- ffmpeg (GPU first)

class AnimError(RuntimeError):
    """A failure with a short machine-readable `code` (see the module doc)."""
    code = "error"


class GpuError(AnimError):
    """The GPU path failed. str() starts with 'gpu_failed:'."""
    code = "gpu_failed"


class NvdecUnsupported(AnimError):
    """The GPU works, but NVDEC can't decode this file's format. str() starts with 'nvdec_unsupported_format:'."""
    code = "nvdec_unsupported_format"


class DecodeError(AnimError):
    """The file is corrupt beyond the tolerated few frames. str() starts with 'decode_errors:'."""
    code = "decode_errors"


class ProbeError(AnimError):
    code = "probe_failed"


class BadCrop(AnimError, ValueError):
    code = "bad_crop"


class BadTrim(AnimError, ValueError):
    code = "bad_trim"


def error_code(exc):
    return getattr(exc, "code", None) or "error"


# decoders NVDEC can take; anything else has no GPU decode path at all
NVDEC_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg1video", "mpeg2video", "mpeg4", "vc1", "mjpeg"}
# pixel formats NVDEC decodes per codec (RTX 40-class); for others ffmpeg would fall back to the CPU on its own
NVDEC_FORMATS = {
    "h264": {"yuv420p", "yuvj420p", "nv12"},
    "hevc": {"yuv420p", "yuvj420p", "nv12", "yuv420p10le", "p010le", "yuv420p12le", "yuv444p", "yuvj444p",
             "yuv444p10le", "yuv444p12le"},
    "vp9": {"yuv420p", "yuv420p10le", "yuv420p12le"},
    "av1": {"yuv420p", "yuv420p10le"},
    "vp8": {"yuv420p"}, "mpeg1video": {"yuv420p"}, "mpeg2video": {"yuv420p"}, "mpeg4": {"yuv420p"},
    "vc1": {"yuv420p"},
    "mjpeg": {"yuvj420p", "yuvj422p", "yuvj444p", "yuv420p", "yuv422p", "yuv444p"},
}
# the hardware path itself is unusable
_GPU_DEFINITE = re.compile(r"Unrecognized hwaccel|Device creation failed|Cannot load (?:nvcuda|cuda)|"
                           r"Could not dynamically load CUDA|No device available for decoder|cuInit|CUDA_ERROR|"
                           r"Error creating a CUDA", re.I)
# the hardware path didn't start for this stream: the GPU or the format (told apart by a known-good decode)
_GPU_AMBIG = re.compile(r"Failed setup for format|hwaccel initiali[sz]ation returned error|Failed to get HW surface|"
                        r"hardware accelerator failed", re.I)
# NVDEC says the format is beyond it
_NVDEC_UNSUP = re.compile(r"Hardware is lacking required capabilities|not supported by the hardware|"
                          r"hardware does not support|Unsupported .{0,40}(?:profile|chroma|bit ?depth)|"
                          r"doesn't support hardware accelerated", re.I)
_GPU_FAIL = re.compile(_GPU_DEFINITE.pattern + "|" + _GPU_AMBIG.pattern, re.I)
# one decoder error event each (a corrupt packet prints a few lines; only these count)
_DECODE_ERR = re.compile(r"Error while decoding stream|error while decoding MB|concealing \d+ .{0,30}errors|"
                         r"co located POCs unavailable|missing picture in access unit|corrupt (?:decoded )?frame|"
                         r"Invalid frame dimensions|decode_slice_header error|Frame num gap|"
                         r"Packet corrupt|Truncating packet", re.I)
_SHOWINFO = re.compile(r"Parsed_showinfo_\d+ @ [^\]]*\]\s*n:\s*(\d+)\s.*?pts_time:\s*([-\d.eE+]+)")


def hwaccel():
    return os.environ.get("ANIMSMITH_HWACCEL", "cuda").strip() or "cuda"


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe(path):
    """ffprobe: {width, height, fps, duration, nb_frames, codec, pix_fmt, profile, has_audio}.
    Raises ProbeError (code probe_failed) with ffprobe's own reason."""
    r = _run(["ffprobe", "-v", "error", "-show_entries",
              "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,pix_fmt,profile"
              ":format=duration", "-of", "json", str(path)])
    if r.returncode != 0:
        why = (r.stderr or "").strip().splitlines()
        raise ProbeError(f"ffprobe failed: {(why[-1] if why else 'no message')[-300:]}")
    try:
        j = json.loads(r.stdout or "{}")
    except ValueError:
        raise ProbeError("ffprobe failed: unreadable output")
    streams = j.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v or not v.get("width"):
        raise ProbeError("ffprobe found no video stream")

    def rate(s):
        num, _, den = (s or "0/1").partition("/")
        try:
            return float(num) / float(den or 1) if float(den or 1) else 0.0
        except ValueError:
            return 0.0

    fps = rate(v.get("avg_frame_rate")) or rate(v.get("r_frame_rate"))
    if fps <= 0 or fps > 1000:
        fps = rate(v.get("r_frame_rate"))
    nb = v.get("nb_frames")
    try:
        dur = round(float((j.get("format") or {}).get("duration") or 0.0), 3)
    except ValueError:
        dur = 0.0
    return {"width": int(v["width"]), "height": int(v["height"]), "fps": round(fps, 3), "duration": dur,
            "nb_frames": int(nb) if str(nb or "").isdigit() else None,
            "codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"), "profile": v.get("profile"),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


def nvdec_format_ok(info):
    """(True, None) when NVDEC should decode this stream; (False, why) when its format is known to be beyond it."""
    codec, pf = info.get("codec"), info.get("pix_fmt")
    if codec not in NVDEC_CODECS:
        return False, f"{codec} has no NVDEC decoder"
    ok = NVDEC_FORMATS.get(codec)
    if ok and pf and pf not in ok:
        return False, " ".join(x for x in (codec, info.get("profile"), pf) if x)
    return True, None


_SANITY = {}


def gpu_sanity():
    """True when the configured hwaccel decodes a known-good clip (H.264 4:2:0, made with h264_nvenc) with no
    hardware errors. Cached per accelerator. It tells a broken GPU from a format NVDEC can't take."""
    key = hwaccel()
    if key in _SANITY:
        return _SANITY[key]
    ok = False
    tmp = Path(tempfile.mkdtemp(prefix="animsmith gpu "))
    try:
        clip = tmp / "sanity.mp4"
        r = _run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                  "testsrc=size=256x192:rate=10:duration=1", "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", str(clip)])
        if r.returncode == 0 and clip.is_file():
            r = _run(["ffmpeg", "-hide_banner", "-nostdin", "-hwaccel", key, "-threads", "1", "-i", str(clip),
                      "-f", "null", "-"])
            log = r.stderr or ""
            ok = r.returncode == 0 and not (_GPU_FAIL.search(log) or _NVDEC_UNSUP.search(log))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _SANITY[key] = ok
    return ok


def gpu_check(gpu=True):
    """Raise GpuError unless the configured hwaccel decodes a tiny known-good clip. No-op when gpu is False."""
    if not gpu:
        return
    r = _run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-hwaccel", hwaccel(), "-f", "lavfi",
              "-i", "testsrc=size=64x64:rate=1:duration=1", "-frames:v", "1", "-f", "null", "-"])
    if r.returncode != 0 or _GPU_DEFINITE.search(r.stderr or "") or not gpu_sanity():
        raise GpuError(f"gpu_failed: ffmpeg -hwaccel {hwaccel()} did not start "
                       f"({(r.stderr or '').strip().splitlines()[-1:] or ['no message']}); "
                       f"fix the GPU/driver or rerun with --gpu off if the user agrees")


def parse_trim(text):
    """'2.0-5.0', '2 - 5', '0:02-0:05.5' (seconds or m:ss) -> [start, end] seconds. Raises BadTrim."""
    t = str(text or "").strip().replace("\u2013", "-").replace("\u2014", "-")
    m = re.fullmatch(r"((?:\d+:)?\d+(?:\.\d+)?)\s*s?\s*(?:-|to)\s*((?:\d+:)?\d+(?:\.\d+)?)\s*s?", t)
    if not m:
        raise BadTrim(f"bad_trim: '{text}' (want start-end in seconds, e.g. 2.0-5.0)")

    def sec(v):
        if ":" in v:
            mm, ss = v.split(":", 1)
            return int(mm) * 60 + float(ss)
        return float(v)

    a, b = sec(m.group(1)), sec(m.group(2))
    if b <= a:
        raise BadTrim(f"bad_trim: '{text}' ends before it starts")
    return [round(a, 3), round(b, 3)]


def scan_decode_log(log, fps_src, fps_out, frames_out):
    """Decoder errors in an ffmpeg log whose filter chain starts with `showinfo` -> {events, lost_frames,
    suspect_frames (1-based output frames), examples}. Each error is tied to the next decoded frame; when errors
    occurred, gaps in the decoded timestamps are frames the decoder dropped (the fps filter fills them with copies,
    which would otherwise read as holds)."""
    events, examples, pending = 0, [], False
    times, suspect_t = [], []
    for line in (log or "").splitlines():
        m = _SHOWINFO.search(line)
        if m:
            try:
                t = float(m.group(2))
            except ValueError:
                continue
            if pending:
                suspect_t.append(t)
                pending = False
            times.append(t)
            continue
        if _DECODE_ERR.search(line):
            events += 1
            pending = True
            if len(examples) < 4:
                examples.append(line.strip()[-160:])
    if pending and times:
        suspect_t.append(times[-1])
    lost = 0
    if events and len(times) > 1 and fps_src:
        step = 1.0 / fps_src
        ts = sorted(times)
        for a, b in zip(ts, ts[1:]):
            if b - a > 1.5 * step:
                k = int(round((b - a) / step)) - 1
                lost += k
                suspect_t += [a + step * (j + 1) for j in range(k)]
    t0 = min(times) if times else 0.0
    frames = sorted({min(frames_out, max(1, int(round((t - t0) * fps_out)) + 1)) for t in suspect_t}) \
        if frames_out else []
    return {"events": events, "lost_frames": lost, "suspect_frames": frames, "examples": examples}


def extract_frames(src, out_dir, fps_cap=60, width=480, max_frames=1200, gpu=True, crop=None, trim=None,
                   fps_exact=None):
    """Decode src into out_dir/f_0001.jpg ... at min(source fps, fps_cap) (or exactly fps_exact), at most `width`
    px wide (never upscaled), at most max_frames. crop = [x, y, w, h] in source pixels, applied before scaling;
    trim = [start, end] seconds (only that range is decoded; the file itself is untouched).
    Returns {frames, fps, fps_src, files, width, height, truncated, decode, probe, trim, decode_errors, notes}.
    Raises GpuError (stop the run), or NvdecUnsupported / DecodeError / ProbeError / BadCrop / BadTrim /
    AnimError (this file only)."""
    out_dir = Path(out_dir)
    info = probe(src)
    notes = []
    if crop:
        x, y, w, h = [int(v) for v in crop]
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > info["width"] or y + h > info["height"]:
            raise BadCrop(f"bad_crop: {list(crop)} doesn't fit the {info['width']}x{info['height']} source")
    if trim:
        a, b = [float(v) for v in trim]
        if a < 0 or b <= a:
            raise BadTrim(f"bad_trim: {list(trim)}")
        if info["duration"] and a >= info["duration"]:
            raise BadTrim(f"bad_trim: starts at {a:g} s but the clip is {info['duration']:g} s long")
        if info["duration"] and b > info["duration"] + 0.05:
            notes.append(f"trim end {b:g} s is past the clip's end ({info['duration']:g} s); used the end")
            b = info["duration"]
        trim = [round(a, 3), round(b, 3)]
    out_dir.mkdir(parents=True, exist_ok=True)
    src_fps = info["fps"] or 30.0
    if not info["fps"]:
        notes.append("source fps unknown; assumed 30")
    fps = float(fps_exact) if fps_exact else min(src_fps, float(fps_cap))
    vf = ["showinfo"]                    # first: logs every decoded frame's time, to place decoder errors
    if crop:
        vf.append(f"crop={w}:{h}:{x}:{y}")
    vf.append(f"fps={fps:.6g}")
    vf.append(f"scale='min({int(width)},iw)':-2:flags=area")
    has_nvdec = info.get("codec") in NVDEC_CODECS
    if gpu and has_nvdec:
        fmt_ok, why = nvdec_format_ok(info)
        if not fmt_ok:
            raise NvdecUnsupported(f"nvdec_unsupported_format: {why} has no NVDEC decode on this GPU (the GPU "
                                   f"itself works); decode this file on the CPU (--gpu off) only if the user agrees")
    use_gpu = bool(gpu) and has_nvdec
    decode = f"gpu ({hwaccel()})" if use_gpu else ("cpu (--gpu off)" if not gpu else
                                                    f"cpu (no NVDEC decoder for {info.get('codec')})")
    if gpu and not use_gpu:
        notes.append(f"{info.get('codec')} has no GPU decoder; decoded on the CPU (no GPU path exists)")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    if use_gpu:
        # one decoder thread: frame threading on many-core CPUs asks NVDEC for > 32 surfaces and it refuses
        # ("Failed setup for format cuda"), which would otherwise fall back to the CPU
        cmd += ["-hwaccel", hwaccel(), "-threads", "1"]
    if trim:
        cmd += ["-ss", f"{trim[0]:.3f}", "-t", f"{trim[1] - trim[0]:.3f}"]
    cmd += ["-i", str(src), "-an", "-vf", ",".join(vf), "-frames:v", str(int(max_frames)), "-q:v", "3",
            str(out_dir / "f_%04d.jpg")]
    r = _run(cmd)
    log = r.stderr or ""

    def clear():
        for f in out_dir.glob("f_*.jpg"):
            f.unlink()

    if use_gpu:
        # ffmpeg quietly decodes on the CPU when NVDEC refuses a stream: those frames are thrown away, never used
        hits = [l.strip() for l in log.splitlines() if _GPU_FAIL.search(l) or _NVDEC_UNSUP.search(l)]
        tail = " | ".join(hits[-2:] or [l for l in log.strip().splitlines() if "showinfo" not in l][-2:])[-240:]
        if _GPU_DEFINITE.search(log):
            clear()
            raise GpuError(f"gpu_failed: ffmpeg -hwaccel {hwaccel()} decode failed ({tail}); "
                           f"fix the GPU/driver or rerun with --gpu off if the user agrees")
        if _NVDEC_UNSUP.search(log) or _GPU_AMBIG.search(log):
            clear()
            if _NVDEC_UNSUP.search(log) or gpu_sanity():
                raise NvdecUnsupported(f"nvdec_unsupported_format: NVDEC refused "
                                       f"{' '.join(x for x in (info.get('codec'), info.get('pix_fmt')) if x)} "
                                       f"({tail}); the GPU itself works; decode this file on the CPU (--gpu off) "
                                       f"only if the user agrees")
            raise GpuError(f"gpu_failed: ffmpeg -hwaccel {hwaccel()} decode failed ({tail}); "
                           f"fix the GPU/driver or rerun with --gpu off if the user agrees")
    if r.returncode != 0:
        clear()
        lines = [l for l in log.strip().splitlines() if "showinfo" not in l]
        raise AnimError(f"ffmpeg frame extraction failed: {' | '.join(lines[-2:])[-300:]}")
    files = sorted(out_dir.glob("f_*.jpg"))
    if not files:
        raise AnimError("ffmpeg wrote no frames")
    dur = (trim[1] - trim[0]) if trim else info["duration"]
    errs = scan_decode_log(log, src_fps, fps, len(files))
    if errs["events"]:
        decoded = max(1, int(round((dur or len(files) / fps) * src_fps)))
        bad = errs["events"] + errs["lost_frames"]
        limit = max(3, int(0.02 * decoded))
        errs.update(limit=limit, decoded_frames_est=decoded)
        if bad > limit:
            clear()
            raise DecodeError(f"decode_errors: ffmpeg reported {errs['events']} decoder error(s) and "
                              f"{errs['lost_frames']} dropped frame(s) (limit {limit}); the file looks corrupt: "
                              f"{'; '.join(errs['examples'][:2])}")
        notes.append(f"decode: ffmpeg reported {errs['events']} decoder error(s), {errs['lost_frames']} dropped "
                     f"frame(s); numbers near frames {errs['suspect_frames'][:12]} are suspect "
                     f"(see decode_errors.affected)")
    expected = dur * fps if dur else None
    truncated = len(files) >= max_frames and (expected is None or expected > max_frames + 1)
    if truncated:
        notes.append(f"clip longer than {max_frames} frames at {fps:g} fps; only the first {max_frames} kept")
    Image = _pil()[0]
    with Image.open(files[0]) as im:
        w0, h0 = im.size
    return {"frames": len(files), "fps": round(fps, 3), "fps_src": info["fps"], "files": [str(f) for f in files],
            "width": w0, "height": h0, "truncated": bool(truncated), "decode": decode, "probe": info,
            "trim": trim, "decode_errors": errs if errs["events"] else None, "notes": notes}


def extract_audio(src, rate=8000, trim=None):
    """Mono float32 PCM of the first audio stream (numpy array) or None when there is none; trim = [start, end]
    seconds. Audio has no GPU decode path in ffmpeg, so this always runs on the CPU."""
    import numpy as np
    cut = ["-ss", f"{float(trim[0]):.3f}", "-t", f"{float(trim[1]) - float(trim[0]):.3f}"] if trim else []
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", *cut, "-i", str(src), "-vn", "-ac", "1",
                        "-ar", str(rate), "-f", "s16le", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768.0


# ---------------------------------------------------------------- images and sheets

def load_rgb(path):
    """Open an image as RGB (alpha flattened onto black, EXIF rotation applied)."""
    Image, _d, _f, ImageOps = _pil()
    with Image.open(path) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (0, 0, 0))
            bg.paste(im, mask=im.split()[-1])
            return bg
        return im.convert("RGB")


def font(size=14):
    """Arial when present, else Pillow's built-in font (no bundled font files)."""
    ImageFont = _pil()[2]
    for f in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def fit(im, max_w, max_h=None):
    Image = _pil()[0]
    w, h = im.size
    s = min(max_w / w, (max_h / h) if max_h else 10.0, 1.0)
    if s >= 1:
        return im
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)


def save_image(im, out, quality=88):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        im.convert("RGB").save(out, "JPEG", quality=quality)
    else:
        im.save(out)
    return out


def sheet(images, out, cols=4, label=True, tile_w=None, title=None, bg=(18, 18, 20)):
    """Grid sheet. images: paths, PIL images, or (image|path, label) pairs. Labels print under each tile.
    tile_w defaults to the first image's width capped at 480. Returns the output path."""
    Image, ImageDraw = _pil()[:2]
    items = []
    for it in images:
        lab = None
        if isinstance(it, (tuple, list)):
            it, lab = it[0], (it[1] if len(it) > 1 else None)
        im = load_rgb(it) if isinstance(it, (str, Path)) else it.convert("RGB")
        items.append((im, lab))
    if not items:
        raise ValueError("sheet: no images")
    cols = max(1, min(cols, len(items)))
    tw = int(tile_w or min(480, items[0][0].width))
    ar = items[0][0].height / items[0][0].width
    th = max(1, int(round(tw * ar)))
    lab_h = 20 if label else 0
    head = 26 if title else 0
    rows = math.ceil(len(items) / cols)
    out_im = Image.new("RGB", (cols * tw, head + rows * (th + lab_h)), bg)
    d = ImageDraw.Draw(out_im)
    f = font(13)
    if title:
        d.text((8, 5), str(title), fill=(235, 235, 235), font=font(15))
    for i, (im, lab) in enumerate(items):
        r, c = divmod(i, cols)
        x, y = c * tw, head + r * (th + lab_h)
        t = fit(im, tw, th)
        out_im.paste(t, (x + (tw - t.width) // 2, y + (th - t.height) // 2))
        if label and lab is not None:
            d.text((x + 4, y + th + 2), str(lab), fill=(225, 225, 225), font=f)
    return save_image(out_im, out)

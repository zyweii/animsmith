"""Record the Studio viewport while the preview animation plays (input for anim_compare.py).

Usage (run it, then start playback within the countdown):
  python kit/scripts/anim_capture.py ANIM-COMBAT-0001 --vault V --seconds 4                       # Windows: records the "Roblox Studio" window
  python kit/scripts/anim_capture.py ANIM-COMBAT-0001 --vault V --seconds 4 --region 400,200,800,800   # x,y,w,h screen region
Writes <vault>/11_ASSET_LIBRARY/_media/anim/<ID>/captures/capture_<timestamp>.mp4 and prints the path
(--out <file> writes anywhere instead; no vault needed then).

Backends: Windows gdigrab (window title or region) / macOS avfoundation (whole screen; crop with --region) / Linux x11grab.
Tip: start this in the background, then trigger playback with the Studio snippet from the pipeline docs so recording and playback
overlap; anim_compare trims the still lead-in/out.

GPU first: the video is encoded with h264_nvenc. If the GPU encoder fails the tool stops with exit code 4 and "gpu_failed";
--gpu off encodes on the CPU (libx264) and is only for when you decided that.
"""
import argparse
import datetime
import os
import platform
import subprocess
import sys

# ffmpeg messages that mean the NVENC encoder (not the capture source) failed
GPU_FAIL_MARKERS = ("nvenc", "cuda", "no capable devices", "openencodesession", "driver does not support")


def _resolve_vault(arg):
    try:
        from animlib import resolve_vault
    except ImportError:
        v = (arg or os.environ.get("ANIMSMITH_VAULT", "")).strip().strip('"').strip("'").strip()
        if not v or not os.path.isdir(os.path.join(v, "11_ASSET_LIBRARY")):
            raise SystemExit("no vault: pass --vault <dir> or set ANIMSMITH_VAULT to a folder that contains 11_ASSET_LIBRARY")
        return v
    return str(resolve_vault(arg))


def build_cmd(a, out):
    sysname = platform.system()
    cmd = ["ffmpeg", "-y", "-v", "error"]
    crop = []
    if a.region:
        x, y, w, h = (int(v) for v in a.region.split(","))
    if sysname == "Windows":
        cmd += ["-f", "gdigrab", "-framerate", str(a.fps)]
        if a.region:
            cmd += ["-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{w}x{h}", "-i", "desktop"]
        else:
            cmd += ["-i", f"title={a.title}"]
    elif sysname == "Darwin":
        cmd += ["-f", "avfoundation", "-framerate", str(a.fps), "-capture_cursor", "0", "-i", "1:none"]
        if a.region:
            crop = ["-vf", f"crop={w}:{h}:{x}:{y}"]
    else:
        disp = os.environ.get("DISPLAY", ":0.0")
        cmd += ["-f", "x11grab", "-framerate", str(a.fps)]
        if a.region:
            cmd += ["-video_size", f"{w}x{h}", "-i", f"{disp}+{x},{y}"]
        else:
            cmd += ["-i", disp]
    # nvenc wants even dimensions and yuv420p
    pad = "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    if crop:
        crop = ["-vf", crop[1] + "," + pad]
    else:
        crop = ["-vf", pad]
    if a.gpu == "on":
        enc = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p"]
    else:
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    return cmd + ["-t", str(a.seconds)] + crop + enc + [out]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("asset_id")
    ap.add_argument("--vault", help="vault folder (else ANIMSMITH_VAULT)")
    ap.add_argument("--out", help="write the capture to this file instead of the vault media folder")
    ap.add_argument("--seconds", type=float, default=4)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--title", default="Roblox Studio")
    ap.add_argument("--region", help="x,y,w,h in screen pixels")
    ap.add_argument("--gpu", choices=["on", "off"], default="on", help="h264_nvenc (default); off = CPU libx264, only when you decided to")
    a = ap.parse_args(argv)
    if a.out:
        out = a.out
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    else:
        vault = _resolve_vault(a.vault)
        out_dir = os.path.join(vault, "11_ASSET_LIBRARY", "_media", "anim", a.asset_id, "captures")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"capture_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4")
    cmd = build_cmd(a, out)
    print("recording:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if a.gpu == "on" and any(m in err.lower() for m in GPU_FAIL_MARKERS):
            print(f"gpu_failed: h264_nvenc could not encode ({err[-300:]}). Not falling back to the CPU; "
                  "rerun with --gpu off if you want that.", file=sys.stderr)
            return 4
        print("ffmpeg failed: " + err[-400:], file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

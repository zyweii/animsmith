#!/usr/bin/env python3
# From vfxmith 0.1.6 (MIT), see THIRD_PARTY.md
# animsmith change: load_xml honours raw=True (CFrame as 12 raw numbers), for Pose.CFrame in KeyframeSequences.
# animsmith change (safety): lz4_block enforces out_len; load_binary caps chunk and total decompressed size
# (MAX_DECOMPRESSED) against decompression bombs; the chunk buffer no longer shadows the raw flag; --scripts
# writes only sanitised basenames inside the out folder, as UTF-8.
"""Read Roblox .rbxm / .rbxl (binary) and .rbxmx / .rbxlx (XML) files WITHOUT Studio.

Nothing in the file runs: this only decodes the instance tree and properties, so it is the safe way to look inside
downloaded open-source models before any of their scripts get near a place.

    python3 -I rbxdump.py <file> [--json out.json] [--tree] [--class ParticleEmitter] [--scripts outdir]
    (--scripts writes each script's Source as text, <sanitised path>.luau.txt, inside outdir; nothing runs)

As a module:  inst = load(path)  ->  list of dicts {ref, class, name, parent, children, props, attrs}

Pure Python (zstandard is optional: only needed for zstd-compressed chunks; LZ4 is decoded here).
Property types decoded: all value types used by VFX (strings, numbers, vectors, colours, sequences, ranges, enums,
referents, CFrames, UDim2, Font, Content, SharedString, attributes). Unknown types are skipped per property.
"""
import json
import math
import os
import struct
import sys
import xml.etree.ElementTree as ET

try:
    import zstandard as _zstd
except Exception:  # pragma: no cover
    _zstd = None


# ---------------------------------------------------------------- LZ4 block (pure Python)
MAX_DECOMPRESSED = 256 * 1024 * 1024     # per file: a real model is far smaller; more is a decompression bomb


def lz4_block(src: bytes, out_len: int) -> bytes:
    """Decode one LZ4 block of exactly out_len bytes. Raises ValueError on a malformed block or on output that
    would pass out_len (or MAX_DECOMPRESSED), so a hostile file can't make it allocate without bound."""
    if out_len < 0 or out_len > MAX_DECOMPRESSED:
        raise ValueError("lz4: declared size %d is out of bounds" % out_len)
    dst = bytearray()
    i, n = 0, len(src)
    try:
        while i < n:
            tok = src[i]; i += 1
            lit = tok >> 4
            if lit == 15:
                while True:
                    b = src[i]; i += 1
                    lit += b
                    if b != 255:
                        break
            if len(dst) + lit > out_len or i + lit > n:
                raise ValueError("lz4: literal run passes the block")
            dst += src[i:i + lit]; i += lit
            if i >= n:
                break
            off = src[i] | (src[i + 1] << 8); i += 2
            ml = tok & 15
            if ml == 15:
                while True:
                    b = src[i]; i += 1
                    ml += b
                    if b != 255:
                        break
            ml += 4
            if off == 0 or off > len(dst):
                raise ValueError("lz4: bad match offset")
            if len(dst) + ml > out_len:
                raise ValueError("lz4: output passes the declared size")
            start = len(dst) - off
            if off >= ml:
                dst += dst[start:start + ml]
            else:
                pat = bytes(dst[start:])
                reps = ml // off + 1
                dst += (pat * reps)[:ml]
    except IndexError:
        raise ValueError("lz4: truncated block")
    if len(dst) != out_len:
        raise ValueError("lz4: decoded %d bytes, header says %d" % (len(dst), out_len))
    return bytes(dst)


# ---------------------------------------------------------------- byte helpers
class R:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def take(self, n):
        v = self.b[self.i:self.i + n]
        if len(v) != n:
            raise EOFError("short read")
        self.i += n
        return v

    def u8(self):
        v = self.b[self.i]; self.i += 1; return v

    def u16(self):
        return struct.unpack_from("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack_from("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack_from("<i", self.take(4))[0]

    def f32(self):
        return struct.unpack_from("<f", self.take(4))[0]

    def f64(self):
        return struct.unpack_from("<d", self.take(8))[0]

    def string(self):
        n = self.u32()
        return self.take(n)

    def left(self):
        return len(self.b) - self.i


def _deint(r: R, count: int, width: int):
    raw = r.take(count * width)
    if count == 0:
        return []
    out = []
    for k in range(count):
        out.append(bytes(raw[j * count + k] for j in range(width)))
    return out


def _u32s(r, n):
    raw = r.take(n * 4)
    return [(a << 24) | (b << 16) | (c << 8) | d
            for a, b, c, d in zip(raw[0:n], raw[n:2 * n], raw[2 * n:3 * n], raw[3 * n:4 * n])]


def _zig(x, bits=32):
    return (x >> 1) ^ -(x & 1)


def _i32s(r, n):
    return [_zig(v) for v in _u32s(r, n)]


def _i64s(r, n):
    return [_zig(int.from_bytes(x, "big"), 64) for x in _deint(r, n, 8)]


def _f32s(r, n):
    out = []
    for v in _u32s(r, n):
        bits = ((v >> 1) | ((v & 1) << 31)) & 0xFFFFFFFF
        out.append(_clean(struct.unpack("<f", struct.pack("<I", bits))[0]))
    return out


def _refs(r, n):
    vals = _i32s(r, n)
    acc, out = 0, []
    for v in vals:
        acc += v
        out.append(acc)
    return out


def _clean(f):
    if isinstance(f, float):
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 5)
    return f


def _s(b: bytes):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


_NORMALS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 0), (0, -1, 0), (0, 0, -1)]


def _rot_from_id(i):
    k = i - 1
    rx, uy = _NORMALS[k // 6], _NORMALS[k % 6]
    bx = (rx[1] * uy[2] - rx[2] * uy[1], rx[2] * uy[0] - rx[0] * uy[2], rx[0] * uy[1] - rx[1] * uy[0])
    return [rx[0], uy[0], bx[0], rx[1], uy[1], bx[1], rx[2], uy[2], bx[2]]


def _euler_deg(m):
    # Roblox ToOrientation-like (YXZ) in degrees, rounded: enough to read a layout
    r00, r01, r02, r10, r11, r12, r20, r21, r22 = m
    x = math.asin(max(-1, min(1, -r12)))
    if abs(r12) < 0.99999:
        y = math.atan2(r02, r22); z = math.atan2(r10, r11)
    else:
        y = math.atan2(-r20, r00); z = 0.0
    return [round(math.degrees(v), 2) for v in (x, y, z)]


# ---------------------------------------------------------------- attributes blob
def parse_attributes(blob: bytes):
    r = R(blob)
    out = {}
    try:
        n = r.u32()
        for _ in range(n):
            name = _s(r.string())
            out[name] = _attr_value(r)
    except Exception:
        out["__partial__"] = True
    return out


def _attr_value(r):
    t = r.u8()
    if t == 0x02:
        return _s(r.string())
    if t == 0x03:
        return bool(r.u8())
    if t == 0x04:
        return r.i32()
    if t == 0x05:
        return _clean(r.f32())
    if t == 0x06:
        return _clean(r.f64())
    if t == 0x09:
        return {"UDim": [_clean(r.f32()), r.i32()]}
    if t == 0x0A:
        return {"UDim2": [_clean(r.f32()), r.i32(), _clean(r.f32()), r.i32()]}
    if t == 0x0E:
        return {"BrickColor": r.u32()}
    if t == 0x0F:
        return {"Color3": [_clean(r.f32()) for _ in range(3)]}
    if t == 0x10:
        return {"Vector2": [_clean(r.f32()) for _ in range(2)]}
    if t == 0x11:
        return {"Vector3": [_clean(r.f32()) for _ in range(3)]}
    if t == 0x14:
        p = [_clean(r.f32()) for _ in range(3)]
        rid = r.u8()
        if rid == 0:
            m = [r.f32() for _ in range(9)]
        else:
            m = _rot_from_id(rid)
        return {"CFrame": p + _euler_deg(m)}
    if t == 0x15:
        return {"Enum": [_s(r.string()), r.u32()]}
    if t == 0x17:
        k = r.u32()
        seq = []
        for _ in range(k):
            env = r.f32(); tm = r.f32(); v = r.f32()
            seq.append([_clean(tm), _clean(v), _clean(env)])
        return {"NumberSequence": seq}
    if t == 0x19:
        k = r.u32()
        seq = []
        for _ in range(k):
            env = r.f32(); tm = r.f32(); c = [r.f32() for _ in range(3)]
            seq.append([_clean(tm)] + [_clean(x) for x in c])
        return {"ColorSequence": seq}
    if t == 0x1B:
        return {"NumberRange": [_clean(r.f32()), _clean(r.f32())]}
    if t == 0x1C:
        return {"Rect": [_clean(r.f32()) for _ in range(4)]}
    if t == 0x21:
        w = r.u16(); st = r.u8(); fam = _s(r.string()); _ = r.string()
        return {"Font": [fam, w, st]}
    raise ValueError("attr type %d" % t)


# ---------------------------------------------------------------- property decoding
RAW = {"on": False}


def _read_prop(r: R, typ: int, n: int, sstr):
    if typ == 0x01:  # String / ProtectedString / BinaryString
        return [r.string() for _ in range(n)]
    if typ == 0x02:
        return [bool(b) for b in r.take(n)]
    if typ == 0x03:
        return _i32s(r, n)
    if typ == 0x04:
        return _f32s(r, n)
    if typ == 0x05:
        return [_clean(r.f64()) for _ in range(n)]
    if typ == 0x06:
        s = _f32s(r, n); o = _i32s(r, n)
        return [[a, b] for a, b in zip(s, o)]
    if typ == 0x07:
        xs = _f32s(r, n); ys = _f32s(r, n); xo = _i32s(r, n); yo = _i32s(r, n)
        return [[a, b, c, d] for a, c, b, d in zip(xs, ys, xo, yo)]
    if typ == 0x08:
        return [[_clean(r.f32()) for _ in range(6)] for _ in range(n)]
    if typ in (0x09, 0x0A):
        return list(r.take(n))
    if typ == 0x0B:
        return _u32s(r, n)
    if typ == 0x0C:
        rr = _f32s(r, n); gg = _f32s(r, n); bb = _f32s(r, n)
        return [[a, b, c] for a, b, c in zip(rr, gg, bb)]
    if typ == 0x0D:
        xs = _f32s(r, n); ys = _f32s(r, n)
        return [[a, b] for a, b in zip(xs, ys)]
    if typ == 0x0E:
        xs = _f32s(r, n); ys = _f32s(r, n); zs = _f32s(r, n)
        return [[a, b, c] for a, b, c in zip(xs, ys, zs)]
    if typ in (0x10, 0x11):
        rots = []
        for _ in range(n):
            rid = r.u8()
            if rid == 0:
                rots.append([r.f32() for _ in range(9)])
            else:
                rots.append(_rot_from_id(rid))
        xs = _f32s(r, n); ys = _f32s(r, n); zs = _f32s(r, n)
        if RAW["on"]:
            return [[x, y, z] + [float(v) for v in m] for x, y, z, m in zip(xs, ys, zs, rots)]
        return [[x, y, z] + _euler_deg(m) for x, y, z, m in zip(xs, ys, zs, rots)]
    if typ == 0x12:
        return _u32s(r, n)
    if typ == 0x13:
        return [("ref", v) for v in _refs(r, n)]
    if typ == 0x14:
        return [[struct.unpack("<h", r.take(2))[0] for _ in range(3)] for _ in range(n)]
    if typ == 0x15:
        out = []
        for _ in range(n):
            k = r.u32()
            out.append([[_clean(r.f32()) for _ in range(3)] for _ in range(k)])
        return out
    if typ == 0x16:
        out = []
        for _ in range(n):
            k = r.u32()
            seq = []
            for _ in range(k):
                tm, cr, cg, cb, _env = (r.f32() for _ in range(5))
                seq.append([_clean(tm), _clean(cr), _clean(cg), _clean(cb)])
            out.append(seq)
        return out
    if typ == 0x17:
        return [[_clean(r.f32()), _clean(r.f32())] for _ in range(n)]
    if typ == 0x18:
        a = _f32s(r, n); b = _f32s(r, n); c = _f32s(r, n); d = _f32s(r, n)
        return [list(x) for x in zip(a, b, c, d)]
    if typ == 0x19:
        out = []
        for _ in range(n):
            f = r.u8()
            if f & 2:
                out.append([_clean(r.f32()) for _ in range(6)])
            elif f & 1:
                out.append([_clean(r.f32()) for _ in range(5)])
            else:
                out.append(None)
        return out
    if typ == 0x1A:
        rr = list(r.take(n)); gg = list(r.take(n)); bb = list(r.take(n))
        return [[a / 255, b / 255, c / 255] for a, b, c in zip(rr, gg, bb)]
    if typ == 0x1B:
        return _i64s(r, n)
    if typ == 0x1C:
        idx = _u32s(r, n)
        return [sstr[i] if i < len(sstr) else b"" for i in idx]
    if typ == 0x1D:
        return [r.string() for _ in range(n)]
    if typ == 0x1E:
        t1 = r.u8()
        cfs = _read_prop(r, 0x10, n, sstr) if t1 == 0x10 else [None] * n
        t2 = r.u8()
        has = [bool(b) for b in r.take(n)] if t2 == 0x02 else [True] * n
        return [c if h else None for c, h in zip(cfs, has)]
    if typ == 0x20:
        out = []
        for _ in range(n):
            fam = _s(r.string()); w = r.u16(); st = r.u8(); _cache = r.string()
            out.append([fam, w, st])
        return out
    if typ == 0x22:  # Content
        kinds = _i32s(r, n)
        nu = r.u32(); uris = [r.string() for _ in range(nu)]
        no = r.u32(); objs = _refs(r, no)
        ne = r.u32(); _ext = _refs(r, ne)
        out = []
        ui = oi = 0
        for k in kinds:
            if k == 1 and ui < len(uris):
                out.append(uris[ui]); ui += 1
            elif k == 2 and oi < len(objs):
                out.append(("ref", objs[oi])); oi += 1
            else:
                out.append(b"")
        return out
    raise ValueError("type 0x%02x" % typ)


TEXT_PROPS = {"Source", "LinkedSource", "Name", "Texture", "TextureId", "TextureID", "MeshId", "Image", "SoundId",
              "AnimationId", "Value", "Text", "Tags", "Graphic", "Face", "ColorMap", "NormalMap", "RoughnessMap",
              "MetalnessMap", "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp", "SunTextureId",
              "MoonTextureId", "Content", "TextureContent", "MeshContent", "ImageContent", "LinkedSource"}


def _val(v, name):
    if isinstance(v, (bytes, bytearray)):
        if name in ("AttributesSerialize",):
            return parse_attributes(bytes(v)) if v else {}
        if name in ("Tags",):
            return [_s(x) for x in bytes(v).split(b"\0") if x]
        if name in ("PhysicsGrid", "MaterialColors", "SmoothGrid", "ChildData", "MeshData", "PhysicalConfigData",
                    "ModelMeshData", "InitialSize", "LevelOfDetail", "SerializedDefaultAttributes",
                    "HistoryId", "UniqueId", "Capabilities", "CollisionGroupData", "AuthorId"):
            return "<%d bytes>" % len(v)
        s = _s(bytes(v))
        return s
    return v


# ---------------------------------------------------------------- binary file
SKIP_PROPS = {"SourceAssetId", "UniqueId", "HistoryId", "ScriptGuid", "Capabilities", "DefinesCapabilities"}


def load_binary(data: bytes, raw=False):
    r = R(data)
    if r.take(8) != b"<roblox!":
        raise ValueError("not a binary Roblox file")
    r.take(6); r.u16()
    r.i32(); r.i32(); r.take(8)
    classes = {}
    inst = {}
    sstr = []
    meta = {}
    total = 0
    while r.left() >= 16:
        name = r.take(4).rstrip(b"\0").decode("ascii", "replace")
        clen = r.u32(); ulen = r.u32(); r.take(4)
        total += ulen
        if ulen > MAX_DECOMPRESSED or total > MAX_DECOMPRESSED:
            raise ValueError("chunk sizes pass %d MB in total: refusing (decompression bomb?)"
                             % (MAX_DECOMPRESSED // (1024 * 1024)))
        blob = r.take(clen if clen else ulen)
        if clen:
            if blob[:4] == b"\x28\xb5\x2f\xfd":
                if not _zstd:
                    raise RuntimeError("zstd chunk but zstandard is not installed")
                body = _zstd.ZstdDecompressor().decompress(blob, max_output_size=ulen)
            else:
                body = lz4_block(blob, ulen)
        else:
            body = blob
        c = R(body)
        if name == "META":
            for _ in range(c.u32()):
                meta[_s(c.string())] = _s(c.string())
        elif name == "SSTR":
            c.u32()
            for _ in range(c.u32()):
                c.take(16); sstr.append(c.string())
        elif name == "INST":
            cid = c.u32(); cname = _s(c.string()); svc = c.u8(); cnt = c.u32()
            refs = _refs(c, cnt)
            classes[cid] = (cname, refs)
            for ref in refs:
                inst[ref] = {"ref": ref, "class": cname, "name": "", "parent": None, "children": [], "props": {},
                             "attrs": {}}
        elif name == "PROP":
            cid = c.u32(); pname = _s(c.string()); typ = c.u8()
            if cid not in classes or pname in SKIP_PROPS:
                continue
            cname, refs = classes[cid]
            try:
                RAW["on"] = raw
                vals = _read_prop(c, typ, len(refs), sstr)
            except Exception as e:  # keep going: one bad property never kills the file
                for ref in refs:
                    inst[ref]["props"].setdefault("__undecoded__", []).append("%s(0x%02x)" % (pname, typ))
                continue
            for ref, v in zip(refs, vals):
                o = inst[ref]
                if raw:
                    o.setdefault("raw", {})[pname] = (typ, v)
                v = _val(v, pname)
                if pname == "Name":
                    o["name"] = v
                elif pname == "AttributesSerialize":
                    if v:
                        o["attrs"] = v
                else:
                    o["props"][pname] = v
        elif name == "PRNT":
            c.u8(); cnt = c.u32()
            kids = _refs(c, cnt); pars = _refs(c, cnt)
            for k, p in zip(kids, pars):
                if k in inst:
                    inst[k]["parent"] = p if p in inst else None
        elif name == "END":
            break
    for o in inst.values():
        p = o["parent"]
        if p is not None:
            inst[p]["children"].append(o["ref"])
    # resolve referent props to instance names (keeps ref ids for lookups)
    for o in inst.values():
        for k, v in list(o["props"].items()):
            if isinstance(v, tuple) and v and v[0] == "ref":
                t = inst.get(v[1])
                o["props"][k] = {"ref": v[1], "name": t["name"] if t else None} if t else None
    return list(inst.values()), meta


# ---------------------------------------------------------------- XML file
def _xml_value(el):
    tag = el.tag
    t = el.text or ""
    if tag in ("string", "ProtectedString", "Content", "BinaryString", "ContentId"):
        u = el.find("url")
        return u.text if u is not None and u.text else t
    if tag in ("bool",):
        return t.strip() == "true"
    if tag in ("int", "int64", "token", "BrickColor"):
        try:
            return int(t)
        except ValueError:
            return t
    if tag in ("float", "double"):
        try:
            return _clean(float(t))
        except ValueError:
            return t
    if tag in ("Vector3", "Vector2", "Color3"):
        if tag == "Color3" and (el.find("R") is not None):
            return [_clean(float(el.find(k).text)) for k in "RGB"]
        return [_clean(float(c.text)) for c in el]
    if tag == "Color3uint8":
        v = int(t)
        return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]
    if tag == "NumberSequence":
        f = [float(x) for x in t.split()]
        return [[_clean(f[i]), _clean(f[i + 1]), _clean(f[i + 2])] for i in range(0, len(f) - 2, 3)]
    if tag == "ColorSequence":
        f = [float(x) for x in t.split()]
        return [[_clean(f[i]), _clean(f[i + 1]), _clean(f[i + 2]), _clean(f[i + 3])] for i in range(0, len(f) - 4, 5)]
    if tag == "NumberRange":
        f = [float(x) for x in t.split()]
        return [_clean(f[0]), _clean(f[1] if len(f) > 1 else f[0])]
    if tag in ("CoordinateFrame", "CFrame"):
        d = {c.tag: float(c.text) for c in el}
        m = [d.get(k, 0) for k in ("R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")]
        if RAW["on"]:  # animsmith: raw 3x3 matrix (row-major) instead of rounded euler angles
            return [d.get("X", 0), d.get("Y", 0), d.get("Z", 0)] + [float(v) for v in m]
        return [_clean(d.get("X", 0)), _clean(d.get("Y", 0)), _clean(d.get("Z", 0))] + _euler_deg(m)
    if tag == "Ref":
        return {"ref": t, "name": None} if t and t != "null" else None
    return t


def load_xml(data: bytes):
    root = ET.fromstring(data)
    out = []

    def walk(el, parent):
        ref = el.get("referent")
        o = {"ref": ref, "class": el.get("class"), "name": "", "parent": parent, "children": [], "props": {},
             "attrs": {}}
        out.append(o)
        props = el.find("Properties")
        if props is not None:
            for p in props:
                nm = p.get("name")
                if nm == "Name":
                    o["name"] = p.text or ""
                elif nm == "AttributesSerialize":
                    import base64
                    try:
                        o["attrs"] = parse_attributes(base64.b64decode(p.text or ""))
                    except Exception:
                        pass
                else:
                    o["props"][nm] = _xml_value(p)
        for ch in el.findall("Item"):
            c = walk(ch, ref)
            o["children"].append(c["ref"])
        return o

    for it in root.findall("Item"):
        walk(it, None)
    return out, {}


def load(path, raw=False):
    data = open(path, "rb").read()
    if data[:8] == b"<roblox!":
        return load_binary(data, raw)
    RAW["on"] = bool(raw)  # animsmith: the XML decoder honours raw=True too (CFrames as 12 numbers)
    try:
        return load_xml(data)
    finally:
        RAW["on"] = False


# ---------------------------------------------------------------- helpers for callers
def index(insts):
    return {o["ref"]: o for o in insts}


def path_of(o, idx):
    parts = []
    while o is not None:
        parts.append(o["name"] or o["class"])
        o = idx.get(o["parent"]) if o["parent"] is not None else None
    return "/".join(reversed(parts))


def safe_basename(text, limit=150):
    """A file name made from an untrusted instance path: no separators, drive letters, '..' or reserved names."""
    import re
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(text or "")).replace("..", "_")
    s = s.strip(" .") or "script"
    if s.split(".")[0].upper() in ("CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "LPT1", "LPT2", "LPT3"):
        s = "_" + s
    return s[:limit]


def script_out_path(out_dir, inst_path):
    """out_dir/<safe name>.luau.txt, unique, and provably inside out_dir. The .txt ending keeps the dump from being
    picked up as code by any tool."""
    os.makedirs(out_dir, exist_ok=True)
    root = os.path.realpath(out_dir)
    base = safe_basename(inst_path.replace("/", "__"))
    p = os.path.join(root, base + ".luau.txt")
    k = 2
    while os.path.exists(p):
        p = os.path.join(root, "%s~%d.luau.txt" % (base, k))
        k += 1
    if os.path.dirname(os.path.realpath(p)) != root:
        raise ValueError("refusing to write outside %s" % root)
    return p


def asset_id(s):
    """'rbxassetid://123', 'http://www.roblox.com/asset/?id=123', '123' -> 123 (or None)."""
    if not isinstance(s, str) or not s:
        return None
    import re
    m = re.search(r"(\d{4,})", s)
    return int(m.group(1)) if m else None


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--json")
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--class", dest="cls")
    ap.add_argument("--scripts", help="write every script's Source under this folder (never runs them)")
    a = ap.parse_args(argv)
    insts, meta = load(a.file)
    idx = index(insts)
    if a.json:
        json.dump({"meta": meta, "instances": insts}, open(a.json, "w"), default=str)
    if a.tree:
        def pr(o, d):
            print("  " * d + "%s [%s]" % (o["name"], o["class"]))
            for c in o["children"]:
                pr(idx[c], d + 1)
        for o in insts:
            if o["parent"] is None:
                pr(o, 0)
    if a.cls:
        for o in insts:
            if o["class"] == a.cls:
                print(path_of(o, idx))
                for k, v in sorted(o["props"].items()):
                    print("   %s = %s" % (k, json.dumps(v, default=str)[:200]))
                if o["attrs"]:
                    print("   @attrs", json.dumps(o["attrs"], default=str)[:300])
    if a.scripts:
        for o in insts:
            if o["class"] in ("Script", "LocalScript", "ModuleScript") and isinstance(o["props"].get("Source"), str):
                p = script_out_path(a.scripts, path_of(o, idx))
                with open(p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(o["props"]["Source"])
    if not (a.json or a.tree or a.cls or a.scripts):
        from collections import Counter
        print(Counter(o["class"] for o in insts).most_common(30))


if __name__ == "__main__":
    main(sys.argv[1:])

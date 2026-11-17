#!/usr/bin/env python3
# From vfxmith 0.1.6 (MIT), see THIRD_PARTY.md
"""Cut ONE subtree out of a .rbxm/.rbxl/.rbxmx and write it as a clean .rbxmx with every script removed.

    python3 -I rbxcut.py <file> --ref <referent> --out effect.rbxmx      (referent from vfx_catalog's effects.jsonl)
    python3 -I rbxcut.py <file> --path "Workspace/VFX/Boom" --out ...    (first match by name path)
    python3 -I rbxcut.py --id <card id> --studio                          (a library effect, straight into Studio's
                                                                           content folder; needs the pack: get_pack.py)

Why: a downloaded place can hide backdoor scripts anywhere (inside a rig attachment, under Terrain). The cut file holds
only the effect's own instances, so nothing from the original scripts can ever reach Studio. Load the result in Studio
with game:GetObjects("rbxasset://<folder under Studio's content dir>/<name>.rbxmx") (no upload, no Roblox account).
Dropped: Script/LocalScript/ModuleScript (+ their children), SharedString data (mesh physics caches, union geometry:
unions come out empty), referents that point outside the subtree.
"""
import argparse
import base64
import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rbxdump as rd  # noqa: E402

DROP_CLASSES = {"Script", "LocalScript", "ModuleScript", "CoreScript", "Plugin"}
CONTENT_PROPS = {"Texture", "TextureId", "TextureID", "MeshId", "Image", "SoundId", "AnimationId", "ColorMap", "NormalMap",
                 "RoughnessMap", "MetalnessMap", "Graphic", "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt",
                 "SkyboxUp", "SunTextureId", "MoonTextureId", "OverlayTextureId", "BaseTextureId", "PantsTemplate",
                 "ShirtTemplate", "HoverImage", "PressedImage", "CursorIcon", "Video", "LinkedSource", "TexturePack"}
BINARY_PROPS = {"AttributesSerialize", "Tags"}
SKIP_PROPS = {"PhysicsData", "Source", "LinkedSource", "ScriptGuid", "MaterialVariantSerialized", "TexturePackMetadata"}


import re as _re
_BAD = _re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def clean(s):
    return _BAD.sub("", s)


def f(v):
    if v is None:
        return None
    return repr(float(v)) if isinstance(v, float) else str(v)


def prop_xml(name, typ, v, refmap):
    n = escape(name, {'"': "&quot;"})
    if typ in (0x01, 0x1D):
        if name in SKIP_PROPS:
            return None
        b = v if isinstance(v, (bytes, bytearray)) else str(v).encode()
        if name in BINARY_PROPS:
            return '<BinaryString name="%s">%s</BinaryString>' % (n, base64.b64encode(b).decode())
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            return '<BinaryString name="%s">%s</BinaryString>' % (n, base64.b64encode(b).decode())
        if _BAD.search(s):
            if name in CONTENT_PROPS:
                s = clean(s)
            else:
                return '<BinaryString name="%s">%s</BinaryString>' % (n, base64.b64encode(b).decode())
        if name in CONTENT_PROPS:
            return '<Content name="%s"><url>%s</url></Content>' % (n, escape(s)) if s else \
                '<Content name="%s"><null></null></Content>' % n
        return '<string name="%s">%s</string>' % (n, escape(s))
    if typ == 0x22:
        b = v if isinstance(v, (bytes, bytearray)) else b""
        legacy = {"MeshContent": "MeshId", "TextureContent": "TextureID", "ImageContent": "Image"}.get(name)
        s = b.decode("utf-8", "replace") if b else ""
        return '<Content name="%s"><url>%s</url></Content>' % (escape(legacy or name), escape(s)) if s else None
    if typ == 0x02:
        return '<bool name="%s">%s</bool>' % (n, "true" if v else "false")
    if typ == 0x03:
        return '<int name="%s">%d</int>' % (n, v)
    if typ == 0x1B:
        return '<int64 name="%s">%d</int64>' % (n, v)
    if typ == 0x04:
        return None if v is None else '<float name="%s">%s</float>' % (n, f(v))
    if typ == 0x05:
        return None if v is None else '<double name="%s">%s</double>' % (n, f(v))
    if typ == 0x06:
        return '<UDim name="%s"><S>%s</S><O>%d</O></UDim>' % (n, f(v[0]), v[1])
    if typ == 0x07:
        return '<UDim2 name="%s"><XS>%s</XS><XO>%d</XO><YS>%s</YS><YO>%d</YO></UDim2>' % (n, f(v[0]), v[1], f(v[2]), v[3])
    if typ == 0x09:
        return '<Faces name="%s"><faces>%d</faces></Faces>' % (n, v)
    if typ == 0x0A:
        return '<Axes name="%s"><axes>%d</axes></Axes>' % (n, v)
    if typ == 0x0B:
        return '<int name="%s">%d</int>' % (n, v)
    if typ == 0x0C:
        if None in v:
            return None
        return '<Color3 name="%s"><R>%s</R><G>%s</G><B>%s</B></Color3>' % (n, f(v[0]), f(v[1]), f(v[2]))
    if typ == 0x0D:
        if None in v:
            return None
        return '<Vector2 name="%s"><X>%s</X><Y>%s</Y></Vector2>' % (n, f(v[0]), f(v[1]))
    if typ == 0x0E:
        if None in v:
            return None
        return '<Vector3 name="%s"><X>%s</X><Y>%s</Y><Z>%s</Z></Vector3>' % (n, f(v[0]), f(v[1]), f(v[2]))
    if typ in (0x10, 0x11):
        if None in v[:3]:
            return None
        keys = ["X", "Y", "Z", "R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22"]
        return '<CoordinateFrame name="%s">%s</CoordinateFrame>' % (
            n, "".join("<%s>%s</%s>" % (k, f(x), k) for k, x in zip(keys, v)))
    if typ == 0x12:
        return '<token name="%s">%d</token>' % (n, v)
    if typ == 0x13:
        tgt = v[1] if isinstance(v, tuple) else None
        return '<Ref name="%s">%s</Ref>' % (n, refmap.get(tgt, "null"))
    if typ == 0x14:
        return '<Vector3int16 name="%s"><X>%d</X><Y>%d</Y><Z>%d</Z></Vector3int16>' % (n, v[0], v[1], v[2])
    if typ == 0x15:
        if any(x is None for k in v for x in k):
            return None
        return '<NumberSequence name="%s">%s</NumberSequence>' % (n, "".join("%s %s %s " % (f(a), f(b), f(c)) for a, b, c in v))
    if typ == 0x16:
        if any(x is None for k in v for x in k):
            return None
        return '<ColorSequence name="%s">%s</ColorSequence>' % (n, "".join("%s %s %s %s 0 " % tuple(f(x) for x in k) for k in v))
    if typ == 0x17:
        if None in v:
            return None
        return '<NumberRange name="%s">%s %s </NumberRange>' % (n, f(v[0]), f(v[1]))
    if typ == 0x18:
        return '<Rect2D name="%s"><min><X>%s</X><Y>%s</Y></min><max><X>%s</X><Y>%s</Y></max></Rect2D>' % (
            n, f(v[0]), f(v[1]), f(v[2]), f(v[3]))
    if typ == 0x1A:
        r, g, b = (max(0, min(255, round(x * 255))) for x in v)
        return '<Color3uint8 name="%s">%d</Color3uint8>' % (n, 0xFF000000 | (r << 16) | (g << 8) | b)
    if typ == 0x20:
        fam, w, st = v
        return '<Font name="%s"><Family><url>%s</url></Family><Weight>%d</Weight><Style>%s</Style></Font>' % (
            n, escape(clean(fam)), w, "Italic" if st == 1 else "Normal")
    return None  # SharedString, OptionalCFrame, PhysicalProperties, UniqueId, ...: engine defaults are fine


def cut(path, ref=None, name_path=None):
    insts, _ = rd.load(path, raw=True)
    idx = rd.index(insts)
    root = None
    if ref is not None:
        root = idx.get(ref)
    elif name_path:
        for o in insts:
            if rd.path_of(o, idx) == name_path:
                root = o
                break
    if root is None:
        raise SystemExit("subtree not found")
    keep = []
    dropped = 0

    def walk(o):
        nonlocal dropped
        if o["class"] in DROP_CLASSES:
            dropped += 1
            return
        keep.append(o)
        for c in o["children"]:
            walk(idx[c])

    walk(root)
    refmap = {o["ref"]: "RBX%d" % i for i, o in enumerate(keep)}
    out = ['<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4">']

    def emit(o):
        out.append('<Item class="%s" referent="%s"><Properties>' % (o["class"], refmap[o["ref"]]))
        out.append('<string name="Name">%s</string>' % escape(clean(o["name"] or "")))
        raw = o.get("raw")
        if raw is None:  # XML source: values are already plain; write the common ones
            raw = {}
        for k, (t, v) in raw.items():
            if k == "Name":
                continue
            try:
                x = prop_xml(k, t, v, refmap)
            except Exception:
                x = None
            if x:
                out.append(x)
        out.append("</Properties>")
        for c in o["children"]:
            if c in refmap:
                emit(idx[c])
        out.append("</Item>")

    emit(root)
    out.append("</roblox>")
    return "\n".join(out), len(keep), dropped


def from_catalog(eid):
    """(pack file, referent) of a library/catalogue effect id; exits with how to get the pack if it is missing."""
    import gzip
    import json
    import get_pack
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    rec = None
    with gzip.open(os.path.join(root, "catalog", "effects.jsonl.gz"), "rt") as fh:
        for line in fh:
            e = json.loads(line)
            if e["id"] == eid:
                rec = e
                break
    if rec is None:
        sys.exit("no effect with id %s in catalog/effects.jsonl.gz" % eid)
    pack = get_pack.find_pack()
    if not pack:
        sys.exit(get_pack.missing_text())
    return os.path.join(pack, rec["file"]), rec["ref"]


def main():
    ap = argparse.ArgumentParser(description="Cut one effect out of a pack file into a clean .rbxmx (no scripts).")
    ap.add_argument("file", nargs="?", help="a .rbxm/.rbxl/.rbxmx (not needed with --id)")
    ap.add_argument("--id", help="a library card / catalogue effect id: file and referent come from the catalogue")
    ap.add_argument("--ref")
    ap.add_argument("--path")
    ap.add_argument("--out", help="output .rbxmx")
    ap.add_argument("--studio", action="store_true",
                    help="write into Studio's content folder as vfxlib/fx_<id>.rbxmx (load with VFXLibPlayer P.load)")
    a = ap.parse_args()
    if a.id:
        a.file, a.ref = from_catalog(a.id)
    if not a.file:
        ap.error("give a file, or --id <effect id>")
    name = "fx_" + (a.id or os.path.splitext(os.path.basename(a.out or a.file))[0])
    if a.studio:
        from rbx_assets import content_dir
        d = os.path.join(content_dir(), "vfxlib")
        os.makedirs(d, exist_ok=True)
        a.out = os.path.join(d, name + ".rbxmx")
    if not a.out:
        ap.error("give --out <file.rbxmx> or --studio")
    ref = int(a.ref) if a.ref and str(a.ref).lstrip("-").isdigit() else a.ref
    xml, n, dropped = cut(a.file, ref, a.path)
    open(a.out, "w").write(xml)
    print("wrote", a.out, n, "instances,", dropped, "scripts dropped")
    if a.studio:
        print('Studio: P.load("%s")  (VFXLibPlayer)   or   game:GetObjects("rbxasset://vfxlib/%s.rbxmx")[1]' % (name, name))


if __name__ == "__main__":
    main()

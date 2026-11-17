"""Rig maths for the Animation Recreation Pipeline (pure Python, no dependencies).

Concepts
-------------------------------------------------------------------------------
* A Roblox joint poses its child as   Part1 = Part0 * C0 * Transform * C1:Inverse()
  and a KeyframeSequence Pose.CFrame IS that Motor6D.Transform ("joint space").
* Joint space differs per rig (R6 shoulders/hips/root are pre-rotated 90 degrees),
  so specs are authored in **REL space** instead:
      Rel  = rotation of the child part relative to its parent part, in the parent's
             rest-aligned axes, pivoting at the joint.  Rest pose = identity for every
             part on both rigs.
      Offset = translation of the child away from its rest joint position, in studs,
             in the parent's axes  (this is "limb detachment").
  Axes (character facing -Z):  +X = character's right, +Y = up, -Z = forward.
  Euler [rx, ry, rz] degrees, composed exactly like CFrame.Angles / fromEulerAnglesXYZ
  (R = Rx * Ry * Rz).  Sign cheat-sheet (verify once per machine with the calibration
  step in the animsmith pipeline docs):
      limb hanging down:  +rx swings it FORWARD/up,  -rx swings it BACK
      torso / head:       -rx leans/nods FORWARD,    +rx leans BACK
      +ry turns the part to its LEFT (counter-clockwise seen from above)
      arm: +rz on the RIGHT arm raises it sideways (abduction); LEFT arm uses -rz
* Conversion (rotation parts only, positions of C0/C1 never matter here):
      Transform.R = C0r^T * Rel * C1r          Transform.p = C0r^T * Offset
      Rel         = C0r * Transform.R * C1r^T   Offset      = C0r * Transform.p
"""
from __future__ import annotations

import json
import math
import os

Mat = list  # 3x3 row-major list of lists
Vec = list  # [x, y, z]

# ---------------------------------------------------------------- basic linear algebra

def mat_mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_vec(a: Mat, v: Vec) -> Vec:
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def mat_t(a: Mat) -> Mat:
    return [[a[j][i] for j in range(3)] for i in range(3)]


IDENTITY: Mat = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def rot_x(t: float) -> Mat:
    c, s = math.cos(t), math.sin(t)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_y(t: float) -> Mat:
    c, s = math.cos(t), math.sin(t)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rot_z(t: float) -> Mat:
    c, s = math.cos(t), math.sin(t)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def euler_to_mat(deg: Vec) -> Mat:
    """Same composition as CFrame.Angles(rx, ry, rz) == Rx * Ry * Rz."""
    rx, ry, rz = (math.radians(d) for d in deg)
    return mat_mul(rot_x(rx), mat_mul(rot_y(ry), rot_z(rz)))


def mat_to_euler(m: Mat) -> Vec:
    ry = math.asin(max(-1.0, min(1.0, m[0][2])))
    if abs(m[0][2]) < 0.99999:
        rx = math.atan2(-m[1][2], m[2][2])
        rz = math.atan2(-m[0][1], m[0][0])
    else:  # gimbal lock: put everything in rx
        rx = math.atan2(m[2][1], m[1][1])
        rz = 0.0
    return [round(math.degrees(rx), 4), round(math.degrees(ry), 4), round(math.degrees(rz), 4)]


# ---------------------------------------------------------------- quaternions (w, x, y, z)

def mat_to_quat(m: Mat):
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return (0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        return ((m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    if m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        return ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s)
    s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
    return ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s)


def quat_to_mat(q) -> Mat:
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def slerp_mat(a: Mat, b: Mat, t: float) -> Mat:
    """Spherical interpolation; t outside [0,1] extrapolates (used for overshoot/exaggerate)."""
    qa, qb = mat_to_quat(a), mat_to_quat(b)
    dot = sum(i * j for i, j in zip(qa, qb))
    if dot < 0:
        qb, dot = tuple(-c for c in qb), -dot
    dot = min(1.0, dot)
    ang = math.acos(dot)
    if ang < 1e-6:
        return b if t >= 0.5 else a
    sa = math.sin(ang)
    wa, wb = math.sin((1 - t) * ang) / sa, math.sin(t * ang) / sa
    return quat_to_mat(tuple(wa * i + wb * j for i, j in zip(qa, qb)))


def angle_between(a: Mat, b: Mat) -> float:
    """Degrees of rotation between two orientations."""
    r = mat_mul(mat_t(a), b)
    c = (r[0][0] + r[1][1] + r[2][2] - 1) / 2
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def lerp_vec(a: Vec, b: Vec, t: float) -> Vec:
    return [x + (y - x) * t for x, y in zip(a, b)]


# ---------------------------------------------------------------- rigs

def _r(*nine) -> Mat:
    return [list(nine[0:3]), list(nine[3:6]), list(nine[6:9])]

# R6: classic constants (rotation part of C0 == rotation part of C1 for every joint).
_R6_ROOT = _r(-1, 0, 0, 0, 0, 1, 0, 1, 0)
_R6_RSH = _r(0, 0, 1, 0, 1, 0, -1, 0, 0)
_R6_LSH = _r(0, 0, -1, 0, 1, 0, 1, 0, 0)

# part (Pose name) -> joint info.  parent = parent Pose name in the KeyframeSequence tree.
R6 = {
    "name": "R6",
    "root": "HumanoidRootPart",
    "parts": {
        "Torso":     {"parent": "HumanoidRootPart", "motor": "RootJoint",      "c0r": _R6_ROOT, "c1r": _R6_ROOT},
        "Head":      {"parent": "Torso",            "motor": "Neck",           "c0r": _R6_ROOT, "c1r": _R6_ROOT},
        "Right Arm": {"parent": "Torso",            "motor": "Right Shoulder", "c0r": _R6_RSH,  "c1r": _R6_RSH},
        "Left Arm":  {"parent": "Torso",            "motor": "Left Shoulder",  "c0r": _R6_LSH,  "c1r": _R6_LSH},
        "Right Leg": {"parent": "Torso",            "motor": "Right Hip",      "c0r": _R6_RSH,  "c1r": _R6_RSH},
        "Left Leg":  {"parent": "Torso",            "motor": "Left Hip",       "c0r": _R6_LSH,  "c1r": _R6_LSH},
    },
}

# R15 (blocky / default): rig attachments are axis-aligned, so C0/C1 rotations are identity.
# If your avatar's rig differs (Rthro, custom), dump the real values with the snippet in
# the animsmith pipeline docs ("dump rig") and pass --rig-file.
_R15_TREE = [
    ("LowerTorso", "HumanoidRootPart", "Root"), ("UpperTorso", "LowerTorso", "Waist"),
    ("Head", "UpperTorso", "Neck"),
    ("RightUpperArm", "UpperTorso", "RightShoulder"), ("RightLowerArm", "RightUpperArm", "RightElbow"),
    ("RightHand", "RightLowerArm", "RightWrist"),
    ("LeftUpperArm", "UpperTorso", "LeftShoulder"), ("LeftLowerArm", "LeftUpperArm", "LeftElbow"),
    ("LeftHand", "LeftLowerArm", "LeftWrist"),
    ("RightUpperLeg", "LowerTorso", "RightHip"), ("RightLowerLeg", "RightUpperLeg", "RightKnee"),
    ("RightFoot", "RightLowerLeg", "RightAnkle"),
    ("LeftUpperLeg", "LowerTorso", "LeftHip"), ("LeftLowerLeg", "LeftUpperLeg", "LeftKnee"),
    ("LeftFoot", "LeftLowerLeg", "LeftAnkle"),
]
R15 = {
    "name": "R15",
    "root": "HumanoidRootPart",
    "parts": {p: {"parent": par, "motor": m, "c0r": IDENTITY, "c1r": IDENTITY} for p, par, m in _R15_TREE},
}

RIGS = {"R6": R6, "R15": R15}


def load_rig(name: str, rig_file: str | None = None) -> dict:
    """Built-in rig, optionally overridden by a JSON dump from Studio:
    {"rig":"R15","joints":{"LowerTorso":{"c0":[x,y,z,r00..r22],"c1":[...]}, ...}}"""
    rig = json.loads(json.dumps(RIGS[name.upper()]))
    if rig_file and os.path.exists(rig_file):
        data = json.load(open(rig_file, encoding="utf-8"))
        for part, j in data.get("joints", {}).items():
            if part in rig["parts"]:
                rig["parts"][part]["c0r"] = _r(*j["c0"][3:12])
                rig["parts"][part]["c1r"] = _r(*j["c1"][3:12])
    return rig


def add_extra_joints(rig: dict, extra: dict | None) -> dict:
    """Spec 'extra_joints' (weapons, capes): {"Handle": {"parent": "RightHand", "motor": "Handle"}}.
    Identity C0/C1 rotation assumed unless c0r/c1r given (author REL == joint space then)."""
    for part, j in (extra or {}).items():
        rig["parts"][part] = {"parent": j["parent"], "motor": j.get("motor", part),
                              "c0r": j.get("c0r", IDENTITY), "c1r": j.get("c1r", IDENTITY)}
    return rig


def rel_to_joint(rig: dict, part: str, rel: Mat, offset: Vec):
    j = rig["parts"][part]
    c0t = mat_t(j["c0r"])
    return mat_mul(c0t, mat_mul(rel, j["c1r"])), mat_vec(c0t, offset)


def joint_to_rel(rig: dict, part: str, rot: Mat, pos: Vec):
    j = rig["parts"][part]
    return mat_mul(j["c0r"], mat_mul(rot, mat_t(j["c1r"]))), mat_vec(j["c0r"], pos)


def chain_to_root(rig: dict, part: str) -> list:
    """[root, ..., parent, part] Pose path for building nested Pose instances."""
    out = [part]
    while out[-1] != rig["root"]:
        out.append(rig["parts"][out[-1]]["parent"])
    return list(reversed(out))


# ---------------------------------------------------------------- rotation vectors (axis * angle, radians)

def mat_log(m: Mat) -> Vec:
    """Rotation matrix -> rotation vector (axis * angle in radians)."""
    c = max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2))
    a = math.acos(c)
    if a < 1e-9:
        return [0.0, 0.0, 0.0]
    if math.pi - a < 1e-5:  # ~180 deg: axis from the diagonal
        x = math.sqrt(max(0.0, (m[0][0] + 1) / 2))
        y = math.sqrt(max(0.0, (m[1][1] + 1) / 2))
        z = math.sqrt(max(0.0, (m[2][2] + 1) / 2))
        if x > 1e-6:
            y, z = math.copysign(y, m[0][1]), math.copysign(z, m[0][2])
        elif y > 1e-6:
            z = math.copysign(z, m[1][2])
        return [x * a, y * a, z * a]
    s = 2 * math.sin(a)
    return [(m[2][1] - m[1][2]) / s * a, (m[0][2] - m[2][0]) / s * a, (m[1][0] - m[0][1]) / s * a]


def mat_exp(v: Vec) -> Mat:
    """Rotation vector (radians) -> rotation matrix (Rodrigues)."""
    a = math.sqrt(sum(x * x for x in v))
    if a < 1e-12:
        return [row[:] for row in IDENTITY]
    x, y, z = (c / a for c in v)
    c, s, C = math.cos(a), math.sin(a), 1 - math.cos(a)
    return [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]

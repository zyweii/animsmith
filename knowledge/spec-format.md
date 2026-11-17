# AnimSpec format

Two parts: **v1 as built** (what `anim_spec.py` reads and writes today; exact) and **v2 PLANNED** (phase 3; a
superset, so every v1 spec stays valid as a one-actor v2 spec). Nothing in v2 exists in code yet.

Specs live in the specs folder in the vault: `<ID>/<ID>_v###.json`. **Never overwrite a version** (HOUSE): each change
is a new file with `version` + 1 and a `history` line. One hypothesis per version.

## v1 (as built)

```json
{
 "id": "ANIM-COMBAT-0001", "version": 3, "name": "Rising uppercut", "rig": "R15", "space": "rel",
 "fps": 60, "length": 42, "loop": false, "priority": "Action", "category": "combat", "stepped": false,
 "camera": {"yaw": 30, "pitch": 8, "distance": 12},
 "extra_joints": {"Handle": {"parent": "RightHand", "motor": "Handle"}},
 "markers": [{"name": "HitStart", "f": 14}, {"name": "HitEnd", "f": 17}, {"name": "MoveCancel", "f": 26}],
 "tracks": {
  "LowerTorso":    [{"f": 0, "r": [0,0,0]}, {"f": 8, "r": [8,25,0], "p": [0,-0.3,0], "e": "CubicV2", "d": "Out"}],
  "RightUpperArm": [{"f": 0, "r": [0,0,0]}, {"f": 10, "r": [-40,0,15]}, {"f": 14, "r": [160,0,10], "e": "Constant", "d": "In"}]
 },
 "history": ["v1 faithful from Breakdown", "v2 retarget R6->R15", "v3 overlap arms 2f, exaggerate strike 1.2"]
}
```

### Top-level fields

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `ANIM-<CAT>-####` |
| `version` | int | Bumped by every tool that writes a new version (retarget, polish); never by hand |
| `name` | string | Human name |
| `rig` | `"R6"` \| `"R15"` | Rig; `rig_file` (optional) points to a dumped joint-frame file for custom rigs |
| `space` | `"rel"` | Rotations are relative to the joint's rest frame |
| `fps` | number | Frame rate of `f` values (60 preferred; match the reference) |
| `length` | number | Last frame |
| `loop` | bool | Loop seam is linted; the engine doesn't interpolate last → first |
| `priority` | `Core` `Idle` `Movement` `Action` `Action2` `Action3` `Action4` | AnimationPriority |
| `category` | `combat` `weapon` `ability` `loco` … | Enables category lint (timid pose, HitStart for combat/weapon/ability) |
| `stepped` | bool | Anime-stepped style: waives the dead-hold warning |
| `camera` | {yaw, pitch, distance} | Preview / capture angle only; not an animated camera |
| `stage_position` | [x,y,z] | Where the preview rig is built (default `[0, 500, 0]`) |
| `extra_joints` | {part: {parent, motor?}} | Weapon/prop joints: a joint named `motor` with Part1 = part under `parent`; `motor` is optional and defaults to the part name |
| `markers` | [{name, f, value?}] | KeyframeMarkers; `value` is an optional string |
| `tracks` | {part: [key…]} | Per-part keys, sorted by `f` |
| `history` | [string] | One line per version |

### Keys

| Key | Meaning |
|---|---|
| `f` | Frame (at `fps`; may be fractional) |
| `r` | REL euler degrees `[rx, ry, rz]`, CFrame.Angles order |
| `p` | Limb offset in studs, parent axes (detachment; root offset) |
| `e` | Easing **leaving** this key: `Linear`, `Constant`, `CubicV2`, `Elastic`, `Bounce` (`Cubic` = legacy, lint warns). Default `CubicV2` |
| `d` | `In`, `Out`, `InOut`. Default `InOut` |
| `fl` | 1 = easing chosen from the motion by the life pass. Lint skips these keys only in the easing-ratio checks (Linear share, legacy Cubic); the overlap check is skipped only when **every** key is `fl`; twinning never skips them. Lint the pre-life version for overlap |

Sign table (REL; **unverified until Stage 0**): hanging limb `+rx` forward/up; torso/head `-rx` lean forward;
`+ry` turn to the character's left; right arm `+rz` / left arm `-rz` raise sideways; R15 lower arm `+rx` elbow bend,
lower leg `-rx` knee bend.

### v1 tool levers (`anim_spec.py polish`)

`--overlap "Part:frames,…"` · `--overshoot "Part@f:amount:settle_f"` · `--exaggerate "Part:f0-f1:scale"` ·
`--retime "f0-f1:scale"` · `--ease "Part@f:Style:Dir"` · `--mirror` · `--life amp[:drag]` (house rule; run last, then
re-ground). Other commands: `new`, `lint`, `retarget --to R15` (pass `--elbow 0` for the straight-limb house style),
`build`, `pose --frame F`, `chart`, `import`.

### v1 as-built quirks (fix in v2 lint)

- The still-part check (house rule: no part still ≥100 ms) runs only on R15 specs and is skipped when `stepped` is
  true. The rule itself still applies to stepped and R6 specs (`principles.md`).
- Lint's startup info line quotes "light 5–9, heavy 12–20"; `timing.md` (startup 4–6 / 18–30) wins.

## v2 (PLANNED, phase 3: not built)

### Sections

| Section | Shape | Notes |
|---|---|---|
| `actors` | name → `{kind: character\|weapon\|prop\|camera, rig: R15\|R6\|<rig file>, attach: {to: "actor.Part", at: f, until?: f}}` | A gun attaches to `hero.RightHand` and may detach mid-clip; a thrown magazine is its own `prop` actor. Generic rigs (any part tree, Motor6D or Bone) come from a rig file |
| `tracks` | actor → part → v1 keys | Camera keys `{f, cf, fov}`; prop parts may also key `transparency` and `scale` |
| `root` | `{keys: [{f, pos: [x,y,z] studs, yaw: deg, e, d}], driven_by: [start_marker, end_marker]}` | Root motion as data, played by script between markers; never baked into HumanoidRootPart |
| `markers` | `[{name, f, args?: {...}, actor?}]` | Schema per category below; linted |
| `delivery` | `[target, …]` | What the exporters must produce (below) |
| `provenance` | `own` \| `licensed` \| `third-party` | `third-party` refuses every shipping target (study only) |
| `camera`, `history`, `version`, `fps`, `length`, `loop`, `priority`, `category`, `stepped` | as v1 | `camera` stays the preview angle; an animated camera is a `camera` actor |

### Marker schema (canonical names; aliases accepted on import and rewritten)

| Category | Canonical markers | Aliases seen in older notes |
|---|---|---|
| combat | `WindupStart`, `HitStart`, `HitEnd`, `ComboWindowOpen`, `MoveCancel`, `End` | `Windup`; `HitboxOn`/`HitboxOff`; `CancelWindow`; `Recover` |
| weapon | `Fire`, `MagOut`, `MagIn`, `BoltBack`, `BoltForward`, `Chamber`, `AimIn`, `AimOut`, `Equip`, `Holster` (+ combat set for melee) | `Shoot`; `Reload` (split it) |
| ability | `ChargeStart`, `Ready`, `Release`, `Impact`, `Recover` | `Cast`, `Spawn` (= `Release`) |
| reaction | `Impact`, `Stagger`, `Fall`, `Ground`, `RiseStart`, `ControlBack` | `ReactStart` → `Impact`; `Down` → `Ground` |
| loco | `FootL`, `FootR`, `Takeoff`, `Land` | `Footstep(L/R)`; `FootPlant1` |
| world | `Open`, `Closed`, `Trigger`, `Settle` | — |
| camera | `Cut`, `Shake(magnitude, roughness, fadeIn, fadeOut)`, `Kick(fov)` | `Shake(amp, rough, dur)` (old 3-arg form: `dur` → fadeOut, fadeIn 0) |
| any | `Sound(name)`, `VFX(name)`, `HitStop(ms)` | `Slash`/`Swing` → `VFX(Slash)` + `Sound(Swing)`; `TrailOn`/`TrailOff` → `VFX(TrailOn/TrailOff)` |

Root-motion markers are canonical: `RootStart`/`RootEnd` (they are `root.driven_by`'s pair). Aliases on import: `DashStart`/`DashEnd`, `MoveStart`/`FeetOff` (rewritten to `RootStart`/`RootEnd`).

Placement rules (SOURCED `Animation_Events_And_Markers`): whoosh `Sound` 2–4 f before the first smear; slash `VFX`
on the first smear frame; trail on 1 f before (last anticipation frame), off 2–4 f after the swing; `HitStart` 1 f
before visual contact; `End` 1–2 f before the last frame; markers within 1 f of the frame data; weight-0 tracks
still fire markers; the server never takes damage timing from client markers.

### Delivery targets

| Target | Exported | For | Rules |
|---|---|---|---|
| `keyframes` | KeyframeSequence → published Animation asset | NPCs, any Humanoid rig without physical limbs, other games | Owned by the experience's owner; temp ids never ship |
| `legs` | A game-specific leg/torso channel clip (root height/sway/pitch/roll/yaw, waist, per-leg channels) as data, looping cycles or timed clips | Games whose code animates legs (procedural feet, IK, pelvis height on top) | Channel list and signs come from the game profile; raw keys never play as plain FK |
| `armref` | Arm reference curves (per side: pitch, abduct, elbow) followed **loosely** by physically simulated arms (goal → force → IK → muscles) | Games with physical arms | **Only where the game profile allows the exception**; otherwise refused by lint |
| `goals` | Wrist-goal and force tables (per tick) for physically driven characters, e.g. a get-up driven by forces from a mocap clip, retimed by dynamic similarity `s = √(k·9.81/g′)` | Physically driven get-ups, kip-ups, climbs | Server-timed; a kill switch in the game |
| `springs` | `{k, zeta, impulse, axis, clamp}` per procedural layer | Procedural recoil, sway, flinch, look-at | Settle via `4/(ζω)` (`timing.md`) |
| `parts` | Cosmetic gun-part curves (bolt, magazine, charging handle, stock) as functions of a replicated 0–1 state | Guns where joint transforms don't replicate | Cosmetic only: **never gates gameplay** (ammo and fire timing stay on the server) |
| `curves` | Easing curves in the game's own format (points + end tangents) | Tween timing, UI-adjacent motion, hitstop release | |
| `camera` | CFrame + FOV track, with `Cut`, `Shake`, `Kick` markers | Ability cut-ins, cinematic moves | Reduced-motion version required (`categories/camera.md`) |
| `tween` | Per-part CFrame, transparency, scale tracks for a runtime player | Doors, platforms, pickups, arena pieces | Server owns state; clients animate (`categories/world.md`) |

### v2 lint (planned additions to v1's)

Marker schema per category; part and easing names checked before any Luau is generated; actor attach consistency
(attached parts have a joint; detach frames inside the clip); delivery-target rules (`armref` refused without a
recorded exception; `parts` refused if a marker gates gameplay; any shipping target refused for `third-party`);
root displacement checked against `root` instead of torso offsets.

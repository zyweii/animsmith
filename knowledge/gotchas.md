# Gotchas: engine and toolchain facts

Checked on **16 Nov 2026**. Each fact is tagged `verified <date>` (checked, with how) or `UNTESTED (<phase>)`.
When a fact changes, edit it in place and re-date it; never append a contradiction. Frames at 60 fps.

## Claude and references

- **Claude takes no video.** Claude Code and the API take images, not video files; a video dropped in chat may not
  arrive at all. Every clip becomes frames, sheets and `numbers.json`; the inbox is the reliable route.
  *verified 2026-11-16 (docs + issue tracker)*
- From one 2D view, timing is good (±1 f at 60 fps from a 60 fps clip; **±2 f from a 30 fps clip**), poses only
  rough: depth, twist and hidden limbs are INFERRED. *verified 2026-11-16 (method)*
- Studio Animation Capture (beta; body mode via Import → Live Animation Creator; R15 only) turns video into keys: one person, under 15 s, stable camera. *verified 2026-11-16 (docs)*
- Licences: stock mocap from a major free library may ship inside a game but not be redistributed alone; a large
  academic motion dataset from a game publisher is **non-commercial** (study only); some video-to-pose models are
  non-commercial, others MIT but need a body model with a paid commercial licence. Check before any key ships.
  *verified 2026-11-16*

## Joints and replication

- `Motor6D.Transform` **doesn't replicate.** Code-driven joint motion must be computed on every client (send state,
  not transforms). *verified 2026-11-09*
- **Avatar Joint Upgrade** (default-on since 27 May 2026): R15 joints become `AnimationConstraint`s. `C0`/`C1` are
  read-only, `IsA("Motor6D")` finds nothing, and Luau that writes `C0` errors. Animations still match joints by part
  name, so published animations are unaffected. Generated Luau must handle both joint kinds. *verified 2026-11-16 (docs)*
- `AnimationTrack:AdjustSpeed(0)` replicates unreliably: run hitstop per client, locally. *SOURCED `Animator_And_AnimationTrack` (NV)*
- Weapons and props need a joint (Motor6D or AnimationConstraint) to the hand, named as the animation expects, and
  `Massless` parts. *SOURCED `Rigging_Motor6D`*
- **R15 spine (resolved):** a classic blocky R15 has 15 parts and one torso joint (Waist) — no spine, chest or
  clavicles. Roblox's skinned-rig spec allows **up to 37 optional bones** (spine, chest, clavicles, fingers, toes),
  but only on skinned mesh avatars. Author for the 15-part rig; treat the "no spine" note as true for blocky R15 and
  optional bones as a per-game rig file. *verified 2026-11-13 (docs spot-check)*
- `AnimationTrack.Length` is 0 until the animation loads; cache tracks, don't reload per play. *SOURCED `Animator_And_AnimationTrack` (NV)*

## Playback

- **Loops don't interpolate last → first.** End a loop on a copy of the first pose; play it 3× to check the seam.
  *SOURCED `Locomotion_Animation`*
- **Default fade is 0.1 s** in `Play()`: it hides about the first 6 f. Attacks play with `Play(0)` or a tiny fade,
  or the anticipation vanishes. *SOURCED `Animation_Principles`*
- **Root offsets snap back.** There is no documented root motion: HumanoidRootPart/torso offsets in keys snap back
  in game, and offsets over 2 studs read as pops. Move the character in script from markers. *SOURCED `Attack_Animation_Anatomy`*
- Keying a joint at its rest pose still **locks** it against lower priorities; delete keys to let a lower layer
  (legs walking) through. Same-priority tracks at equal weight average 50/50 = mush. *SOURCED `Animation_Priority_And_Blending`*
- Tracks at weight 0 still fire markers. Never take damage timing from client markers; the server owns hits.
  *SOURCED `Animation_Events_And_Markers`*
- Animation slow-motion via `AdjustSpeed` desyncs from wall-clock systems (cooldowns, i-frames). *SOURCED `Ability_And_Ultimate_Animation` (NV)*

## Editor and authoring

- The Animation Editor **defaults to 30 fps**: match the reference's rate. *SOURCED `Animation_Workflow_Tools` (NV)*
- The editor's optimiser **deletes holds** made of 3+ identical keys. Make holds moving holds (2–5% drift), which
  the house rule wants anyway. *SOURCED `Programmatic_Animation_Authoring` (NV)*
- Converting a track in the Curve Editor to Euler curves is **irreversible**. *SOURCED `Animation_Workflow_Tools` (NV)*
- Easing enum: Linear 0, Constant 1, Elastic 2, Cubic 3 (**deprecated**: use CubicV2), Bounce 4, CubicV2 5.
  *SOURCED `Programmatic_Animation_Authoring` (NV)*
- Temporary KeyframeSequence ids (`RegisterKeyframeSequence`) **die with the Studio session**: never put one in game
  code. *SOURCED `Programmatic_Animation_Authoring`*
- UGC/marketplace animations are **rejected** when a limb jumps more than 1 stud between frames (detachment smears
  must stay under that). *SOURCED `Limb_Detachment_Technique` (NV)*
- A published animation must be owned by the user or group that owns the experience. *SOURCED `Animator_And_AnimationTrack`*
- Blender export: Add Leaf Bones off. Blender renders and bakes on the GPU. *SOURCED `Animation_Workflow_Tools`*
- `screen_capture` works in Edit mode only and returns dark frames when Studio isn't the front window. *verified 2026-11-15*
- `execute_luau` caches `require()` per ModuleScript for the session; clone to re-require. *verified 2026-11-09*

## Local tools

- Python 3.14 with numpy and Pillow; ffmpeg/ffprobe 4.4 with hwaccel `cuda` and encoder `h264_nvenc`. GPU decode
  and encode by default; a GPU failure stops with `gpu_failed`, never a silent CPU fallback. *verified 2026-11-16*

## Stage 0: still UNTESTED (phase 2 tests these before any build)

| Item | Why it matters |
|---|---|
| The REL sign table (limb `+rx` forward/up, torso `-rx` lean forward, `+ry` turn left, right arm `+rz` raise sideways) | Every spec and every pose estimate depends on it |
| Weight-0 container poses | Whether a weight-0 track can host poses for scrubbing |
| `Animator:StepAnimations` from `execute_luau` (Edit-mode playback) | Freeze-then-shoot captures |
| `RBX_ANIMSAVES` pickup by the Animation Editor | Hand edits and `import` |
| `CreateHumanoidModelFromDescriptionAsync` from MCP | Building lab rigs |
| `RegisterKeyframeSequence` temp ids in Edit mode | Previewing without publishing |
| Building and posing on AnimationConstraint rigs | The Avatar Joint Upgrade |
| Desktop capture with nvenc | Real-time capture for timing compare |
| MCP `generate_animation` (undocumented) | A possible draft route |
| Loading Roblox-owned or catalog KeyframeSequences | Learning from real data |

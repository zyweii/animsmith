# Category: loco (idle, walk/run/sprint, strafe, jump/land, dash, turns, stops)

Status: seed study. The only category with measured references so far: one stylised set of ~10 R6 clips (idle, run,
dashes, jump, landing; mostly 30 fps) gives `MEASURED n=…` rows and observations; everything else SOURCED
`Locomotion_Animation`. Frames at 60 fps (source @30 values doubled; ±2 f).

## Anatomy

| Clip | Phases |
|---|---|
| Walk/run cycle | 4 poses per foot: contact, down, passing, up (×2 feet); phase 0 = left-foot contact |
| Idle | breathing loop + weight shift; the shared stance every clip starts and ends on |
| Jump | crouch → takeoff → ascent → apex hang → fall → land (impact, compress, recover) |
| Dash | start (launch) → glide (moving hold, loop) → end (brake, foot plant) → recover |
| Stop / turn | brake with a counter-lean; pelvis leads a turn, chest follows |

## Starting numbers

| Item | Numbers | Status |
|---|---|---|
| Walk cycle | 60–80 f | SOURCED |
| Run cycle | 32–40 f (measured jog 31 f; strafe/back 37–39 f) | SOURCED; MEASURED n=1 set |
| Sprint cycle | 24–32 f, forward lean 15–30° | SOURCED |
| Stylised run | held extremes (~8 of 38 f each) + 6–8 f swaps; torso counter-twist ±45°; trailing leg to horizontal; passing = flight (root highest) | observation n=1 |
| Lean into movement | 10° forward/back, 8° sideways; spring 8 Hz, ζ 0.7 (settle ≈ 7 f) | observation n=1 |
| Turn | pelvis leads (0.12 s ≈ 7 f), chest follows (0.20 s ≈ 12 f) | observation n=1 |
| Walk stop | 6 f | SOURCED (the source's frame counts are already at 60 fps; not doubled) |
| Run stop | ~16 f; actionable (control back) at f6 | SOURCED (already @60) |
| Jump | crouch 2–4, max stretch in the first 3–5 of the ascent, apex hang 2–4, landing 4–8 (0–2 compress, 3–5 recover) | SOURCED; **fps ambiguous**: one source states no fps for any of the four numbers, so all four are taken as stated; if a build confirms they were @30, double all four together |
| Landing (stylised) | 2 f impact (1 f @30), ~6 f max-compress hold, head drags 4–6 f behind the torso, ~50 f to full settle; root overshoots stance +0.04 studs | observation n=1 |
| Dash set | 64 f; `DashStart` f14–18, `DashEnd` f34–38, `MoveCancel` f46–50; all directions share length and marker frames | observation n=1 (set of 3, @30 doubled) |
| Dash (split clips) | start 0.10 s (6 f), glide loop, end 0.28 s (17 f); travel `pos = D·(1−(1−u)²)` (ease-out) | observation n=1 |
| Forward dash pose | side-on (torso yaw ~80°), lead arm thrust, rear leg flat behind; lean only ~20° (head upright); 16 f moving hold | observation n=1 |
| Lateral dash | lead arm detaches outward ~0.6 studs (R15: ~60% of it); body rolls ~12° into travel; trailing leg kicks out ~25° | observation n=1 |
| Idle breath | 2–4 s, default 3 s; 4–8 f offsets on head/arms; waist 0.5–1°; weight shift every 6–10 s | SOURCED + MEASURED n=1 (`timing.md` resolves the 1–2 s note) |
| Fades | play 0.15 s, stop 0.2 s | SOURCED |
| Crouch | 2–4 f in | SOURCED |
| Locomotion medians | anticipation 184 ms, follow-through 667 ms, follow/antic 3.6, hold 29% of the clip, limb lag 2 f, detachment 0.4 studs | MEASURED n=10 (one stylised source) |

**Landing length:** the theory's 8–16 f is impact + compress + first recovery; the measured stylised landing takes
~50 f to fully settle. Use 8–16 f until control returns, then let the settle run under the next clip.

**Playback speed:** `AdjustSpeed(groundSpeed / authoredSpeed)` so feet don't slide; planted slide ≤3–10% of ground
speed; grounded feet within 0.04 studs. **Mocap** is retimed for the game's gravity by `s = √(k·9.81/g′)` (HOUSE).

## Directional sets (resolved)

Older rule: "directional sets share length and contact frames". Measured: a jog of 31 f vs strafe/back 37–39 f.
**Use one normalised phase (0..1, phase 0 = left-foot contact) shared by every direction**, so lengths may differ while
contacts line up when blended; equal lengths are only required when a system blends by plain clip time. One-shot sets
(dashes) share length and marker frames exactly. Every clip in a set starts and ends on one shared stance.

## Easing

Cycles: CubicV2 on locomotion (not Constant); Linear out of a held extreme, CubicV2 Out into passing; InOut swaps pop
(observation n=1). Loops end on a copy of the first pose and loop seam keys are Linear (no once-per-loop stall). Key
down and up poses too: contact + passing only gives an inverted bob.

## Markers (canonical; aliases)

`FootL`, `FootR` (aliases `Footstep(L/R)`, `FootPlant1`), `Takeoff`, `Land`. Footsteps fire on phase crossings.
Dashes keep `DashStart`/`DashEnd`/`MoveCancel` (aliases `MoveStart`, `FeetOff`) until the schema gets a root-motion
pair. **HOUSE: no foot plant before the dash's end marker.**

## Common mistakes → fix

| Mistake | Fix |
|---|---|
| Sliding feet | speed-matched playback; ground pass on every grounded key |
| Inverted bob | key the down and up poses |
| Loop stall at the seam | Linear seam keys; last pose = first pose; play 3× |
| Dead idle | moving hold, asymmetric offsets on head/arms, weight shift |
| Directions blend into mush | shared normalised phase, contacts aligned |
| Twinned arms in a run | L/R ≥1–2 f apart plus a few degrees |
| Upper-body clip locking the legs | delete leg keys in upper-body clips |
| Dash plants a foot mid-glide | no plant before `DashEnd` (HOUSE) |

## What to look for in a reference

Cycle length (`numbers.cycle`), contacts per foot, stride and cadence, pelvis yaw vs chest, lean and bob amplitude,
knee lift, head stability, arm swing phase vs legs, travel in body heights, speed curve (onset, decay, peak as a
multiple of run speed), transitions (start, stop, turn), ground vs air frames, and what the clip doesn't show.

## GAPS (training fills these)

- Walk and sprint measured references (only jog/strafe/back measured).
- Starts, stops, pivots and 180° turns; slopes and stairs; crouch-walk; climbing, swimming, sliding, wall-run.
- Idle variety (fidgets) and idle → combat stance.
- R15 versions of the measured R6 set (the house style keeps limbs straight; check how it reads).
- Every observation n=1 above needs a second source to become a candidate.

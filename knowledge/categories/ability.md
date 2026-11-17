# Category: ability (specials, ultimates, casts, dashes, counters)

Status: seed study. Numbers SOURCED from `Ability_And_Ultimate_Animation`, which is itself **needs-verify (NV)**:
treat every row as a starting range until measured references back it. Frames at 60 fps. Plain attacks: `combat.md`.

## Anatomy: the 5-beat ultimate (SOURCED, NV)

| Beat | Duration | Animation | Script / VFX / camera | Marker |
|---|---|---|---|---|
| 1. Snap to charge pose | 2–4 f | contrasting, coiled silhouette (near-opposite of the release pose) | world slow-mo or freeze others; invulnerability on | `ChargeStart` |
| 2. Hold / build | 0.5–1.5 s (30–90 f) | **moving hold**: breathing, energy tremble (HOUSE: nothing frozen) | aura VFX grows, sound riser, camera push-in | `Ready` at the end |
| 3. Release | 2–6 f + 1–3 f smear | whip into the hero impact pose | flash, screen effect, camera cut or kick | `Release` |
| 4. Impact hold | 0.3–0.5 s (18–30 f) | both frozen or the victim shaking | the longest hitstop in the kit (15–30 f, slow-mo tail 0 → 0.3 → 1), shake trauma 0.8–1.0 | `Impact`, `HitStop(ms)` |
| 5. Settle | long, late cancel | overshoot → settle → idle | VFX dissipate, time back to 1.0 | `Recover` |

Whole cast budget ≈ 1 s (60 f) before the release for a normal special; ultimates spend it on the hold.

## Other ability types

| Type | Starting numbers | Notes | Status |
|---|---|---|---|
| Projectile cast | startup 10–16 (spawn on the last frame), recovery 15–25 | a readable throw pose; `Release` drives the spawn | SOURCED `Combat_Animation_Frame_Data` |
| Dash / blink | animate in place; travel by a mover (LinearVelocity) between markers; afterimages | dash timing (start clip 0.10 s = 6 f, glide loop, end clip 0.28 s = 17 f; position `D·(1−(1−u)²)`): `loco.md` | SOURCED (NV) + observation n=1 |
| Dodge | startup 2–4 f, i-frames 26–28 f, perfect window 0.13–0.2 s (8–12 f) | i-frames on the server's clock, not the animation's | SOURCED (NV) |
| Counter / parry | 1–2 f snap pose, slow-mo beat, then an immediate counter clip | the snap is the readable beat | SOURCED (NV) |
| Aura / charge loop | fade in 0.2 s (12 f); loop seams closed | moving loop, offsets on every part | SOURCED `Animation_Priority_And_Blending` |
| Dash attack | startup 6–8, active 8–14 (moving), recovery 15–20, hitstop 4 | | SOURCED `Combat_Animation_Frame_Data` |
| Ground slam / AoE | startup 20–35, active 3–4, recovery 30–45, hitstop 10–14 | camera shake on `Impact` | SOURCED |
| Transformation | template above with the longest holds and a camera script | | SOURCED (NV) |

## Easing

Snap into the charge pose: Constant or a 2–4 f CubicV2 Out. The hold: slow sine drift (2–5%) plus tremble. Release:
CubicV2 In or Linear into a Constant contact. Impact hold: hold the pose with drift; release the freeze along a curve.
Settle: CubicV2 Out overshoot, then InOut.

## Time and camera dependence

- **Slow motion** via `AdjustSpeed` desyncs from wall-clock systems (cooldowns, i-frames): drive time-scaled beats
  from one game clock, and run freezes per client (`gotchas.md`). SOURCED (NV).
- Abilities lean on the camera more than any other category: push-in during the hold, a cut or FOV kick on release,
  shake on impact (`camera.md`). An animation asset carries no camera: the camera is a separate track or script.
- Offer reduced motion for the camera parts.

## Markers (canonical; aliases)

`ChargeStart`, `Ready`, `Release` (aliases `Cast`, `Spawn`), `Impact`, `Recover`, plus `VFX(...)`, `Sound(...)`,
`HitStop(ms)`, and camera markers `Cut`, `Shake(magnitude, roughness, fadeIn, fadeOut)`, `Kick(fov)`. Dash travel uses
the source's names (`DashStart`/`DashEnd`) until the schema gets a root-motion pair (open gap in `spec-format.md`).

## Common mistakes → fix

| Mistake | Fix |
|---|---|
| Frozen charge hold | moving hold: breathing + tremble on every part |
| Release pose looks like the charge pose | make them near-opposite; push both 20–30% |
| Travel baked into the root | animate in place; mover between markers |
| Slow-mo breaks cooldowns | one game clock for time-scaled beats |
| Impact with no hold | 15–30 f hitstop with a slow-mo tail + shake |
| The whole thing is unreadable without its VFX | check the silhouette with VFX off first |

## What to look for in a reference

The beats and their lengths (energy plateaus = holds); charge vs release silhouette; what the camera does per beat
(push-in, cut, FOV, shake: `numbers.camera`); hitstop and slow-mo tail; which beats VFX carry (smears, auras); sound
sync on release and impact; when control returns.

## GAPS (training fills these)

- Charge-up frame counts by power tier; how long a hold can be before it bores.
- Camera cut timing and framing in cut-ins (`camera.md`).
- Transformations, summons, grabs-into-cinematics, two-actor ultimates (attacker + victim keyed together).
- Beam/channelled abilities (looping while held) and their exit.
- Whether the NV numbers (dodge i-frames, perfect windows) hold for this style of game.

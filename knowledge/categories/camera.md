# Category: camera (push-in, dolly, FOV kick, cuts, shake, lock-on)

Status: seed study, **thin**. SOURCED: the trauma shake table (`Camera_Shake`), shake while frozen (`Hit_Stop`),
reduce shake on big moves and offer reduced motion, bullet time via camera speed, the gameplay camera angle
(`Posing_And_Exaggeration`). Everything else is Claude's reasoning, labelled UNTESTED. Frames at 60 fps.

An animation asset carries no camera: camera motion is its own track (`camera` delivery target: CFrame + FOV keys
with `Cut`, `Shake`, `Kick` markers) or a script, synced to the character clip by markers.

## The gameplay camera (what character work is judged from)

3/4 rear, 30–45° above (SOURCED `Posing_And_Exaggeration`). Every key pose must read from it.

## Shake (SOURCED `Camera_Shake`)

Trauma model: events add trauma (0..1), trauma decays linearly, amplitude = trauma² (exponent 2–3), sampled from
noise; plus a directional spring kick in the hit direction.

| Parameter | Light hit | Heavy hit | Ult / explosion |
|---|---|---|---|
| Trauma added | 0.15–0.25 | 0.4–0.6 | 0.8–1.0 |
| Decay per s | 2.5 | 1.8 | 1.0 |
| Max yaw/pitch at amp 1 | 1.5° | 3° | 6° |
| Max roll | 1° | 2.5° | 5° |
| Max offset | 0 | 0.15 studs | 0.5 studs |
| Noise frequency | 25 Hz | 18 Hz | 12 Hz |
| Lasts (trauma/decay) | ≈ 0.06–0.1 s (4–6 f) | ≈ 0.22–0.33 s (13–20 f) | ≈ 0.8–1.0 s (48–60 f) |

Shake keeps running during hitstop (the freeze + shake combo is the point). Reduce shake on big camera moves.

**The marker form** is CameraShaker-style: `Shake(magnitude, roughness, fadeIn, fadeOut)`. Mapping from the trauma
table (UNTESTED): magnitude ≈ trauma² × max rotation, in degrees (light ≈ 0.03–0.1, heavy ≈ 0.5–1.1, ult ≈ 4–6; a light hit's shake is
nearly invisible by design, the kick carries it; CameraShaker's own magnitude units need calibrating against this), roughness rises
with noise frequency (light highest), fadeIn 0 for impacts (0.05–0.2 s for rumbles), fadeOut ≈ the "lasts" row.
The old 3-argument `Shake(amp, rough, dur)` maps `dur` → fadeOut with fadeIn 0.

## Moves (UNTESTED starting numbers)

| Move | Numbers | Easing | Notes |
|---|---|---|---|
| FOV kick (hit, shot) | +2–4° light, +5–8° heavy, peak in 1–2 f, back in 6–15 f | Constant up, exponential decay down | `Kick(fov)`; never on every light hit of a combo |
| FOV sprint | +5–10° over 12–18 f, back over 12–18 f | CubicV2 Out / InOut | |
| ADS zoom | FOV 70 → 50–60 (scopes 20–30), same curve as the ADS animation | CubicV2 Out | `weapon.md` |
| Push-in (charge hold) | 10–25% closer or FOV −5 to −15° across the 0.5–1.5 s hold | CubicV2 InOut, slow start | the release snaps back or cuts |
| Pull-out (impact reveal) | 15–40% further over 12–30 f after impact | CubicV2 Out | shows the hit's reach |
| Dolly / orbit (cinematic) | 0.5–2 s per move | CubicV2 InOut | one move per shot |
| Follow lag | spring k ≈ 150, ζ 1 (settle ≈ 28 f, `timing.md`) | spring | too stiff = rigid, too soft = seasick |
| Lock-on blend | 9–18 f (0.15–0.3 s) to the new target | CubicV2 Out | |
| Cut-in (ultimate) | 2–4 shots in 1.5–3 s; each shot ≥ 30 f to read, except a 6–12 f impact insert | — | |
| Cut timing | cut on action: on the release frame or 1–2 f before impact; keep screen direction (180° rule) | — | `Cut` marker |
| Bullet time | slow the camera's clock, not the world's (SOURCED hint) | slow-mo tail 0 → 0.3 → 1 | one game clock (`ability.md`) |

## Accessibility

Offer reduced motion: scale shake ×0–0.3, drop FOV kicks and pull-outs, replace cuts with a hold. SOURCED (hint).

## Markers

`Cut`, `Shake(magnitude, roughness, fadeIn, fadeOut)`, `Kick(fov)`, plus `Sound(...)`, `VFX(...)`, `HitStop(ms)`.

## Common mistakes (reasoned)

| Mistake | Fix |
|---|---|
| Shake on every hit, same size | scale with damage; small or none on combo fillers |
| Shake stops during hitstop | keep it running |
| Cut lands after the impact | cut on the release or 1–2 f before |
| Camera snaps to a lock-on target | 9–18 f eased blend |
| Push-in and a big shake together | reduce the shake on big moves |
| A cinematic that hides the character's key pose | frame the key pose first, then move |

## What to look for in a reference

`numbers.camera`: per-frame shift (moves vs static), `shake_candidates` (frame ranges, rough amplitude in px), cuts
(contact sheet jumps); FOV changes (background scale change without parallax); push-in/pull-out timing vs the
character's beats; which beats the camera sells instead of the body.

## GAPS (training fills these)

FOV kick sizes, push-in and dolly durations, cut timing in cut-ins, lock-on blends, framing rules for ultimates,
first-person viewmodel camera bob and sway, the CameraShaker parameter mapping above.

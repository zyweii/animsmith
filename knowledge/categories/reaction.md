# Category: reaction (hit-reacts, stagger, knockdown, get-up, KO)

Status: seed study, **mostly UNTESTED**. SOURCED rows come from `Hit_Stop`, `Animation_Priority_And_Blending`,
`Attack_Animation_Anatomy` and `Combat_Animation_Frame_Data`; the rest is reasoned from those (how long a victim must
be readable, how mass falls and rises) and marked UNTESTED. Frames at 60 fps.

## Anatomy

| Tier | What it is | Phases |
|---|---|---|
| Flinch (light) | upper-body react layered over whatever plays | snap to the hurt pose → hold through hitstop → recover |
| Hit-react (standard/heavy) | full-body react by direction | snap → hold → recoil/overshoot → recover to guard |
| Stagger | lost balance: steps to catch the weight | snap → stumble steps → regain → guard |
| Knockdown | falls to the ground | snap → fall → ground impact (bounce) → down hold |
| Get-up | from down to standing (front/back, roll, kip-up) | push/roll → rise → settle → control back |
| KO / death | final fall, no recovery | snap → fall → impact → settle (still alive: breathing stops only here; a KO stillness carve-out from the house rule is **pending the user's ruling**, do not assume it) |

## Starting numbers

| Beat | Numbers | Status |
|---|---|---|
| Any → hit-react fade | **0** (a snap sells the hit) | SOURCED `Animation_Priority_And_Blending` |
| Flinch layer | Action2, torso/head keys only, weight 0.6, fade 0 in / 0.15 s out; the attack continues underneath | SOURCED |
| First frame | the victim snaps to frame 1 of the hurt pose and **freezes there during hitstop**: author it as the strongest pose of the clip | SOURCED `Hit_Stop`, `Attack_Animation_Anatomy` |
| Victim hitstop | same length as the attacker's (light 2–4, standard 5–7, heavy 8–12, ult 15–30); shake ±0.1–0.2 studs while frozen | SOURCED `Hit_Stop` |
| Hitstun | longer than the attacker's remaining recovery = attacker "plus on hit" (can continue the combo) | SOURCED `Combat_Animation_Frame_Data` |
| Flinch total | 12–20 f after hitstop | UNTESTED |
| Heavy hit-react | snap + hold + 20–35 f recover | UNTESTED |
| Stagger | 30–60 f, 1–3 stumble steps, each step a real foot plant | UNTESTED |
| Knockdown fall | 15–30 f to ground impact; a 1–2 f impact, 4–8 f compress/bounce, then a down hold | UNTESTED (compress shape from a landing observation: 1 f impact, ~6 f compress, head drags 4–6 f) |
| Down hold | 30–90 f, breathing (moving hold) | UNTESTED |
| Get-up | 30–60 f standard; roll-up 24–40; kip-up 40–100 (≈ 1.6 s with mocap timing) | UNTESTED; kip-up length observation n=1 |
| Any → death fade | 0.05 s (3 f) | SOURCED |
| Death priority | Action4 (absolute override) | SOURCED |

Direction: pick by the hit's direction relative to the victim (front, back, left, right; high vs low). Front hits fold
the torso back and the head lags 2–4 f; side hits twist and roll toward the far side; low hits buckle a knee (the one
place an R15 knee bends: HOUSE allows it where R6 would compress). Strength scales the pose (10–30% further) and the
recovery length, **not** the snap speed.

## Physically driven reactions (a delivery idea; UNTESTED)

Games with physical or ragdoll bodies can drive knockdowns and get-ups by forces instead of keys:
- A **force/goal table** per tick (wrist goals, leg targets, torque budgets) from a reference or mocap clip, played
  server-timed (target `goals` in `spec-format.md`).
- **Mocap retimed by dynamic similarity** for the game's gravity: `s = √(k·9.81/g′)` (HOUSE), so a heavier-feeling
  game gravity speeds the clip up correctly.
- A kill switch and a keyed fallback; the ragdoll's own fall replaces the "fall" keys.
- Reaction springs (procedural flinch): impulse in the hit direction in local space, k 300, ζ 0.4, settle ≈ 35 f
  (corrected, `timing.md`); freeze springs during hitstop.

## Easing

Into the hurt pose: Constant (snap). Recoil: CubicV2 Out. Fall: CubicV2 In (gravity accelerates), Linear into the
ground contact, Bounce or a short CubicV2 Out for the bounce. Get-up: CubicV2 InOut on the big push, Out into standing,
overshoot ~4 f.

## Markers

Canonical set (`spec-format.md`): `Impact`, `Stagger`, `Fall`, `Ground` (ground impact), `RiseStart`,
`ControlBack`; aliases `ReactStart` → `Impact`, `Down` → `Ground`. Root-motion clips use `RootStart`/`RootEnd`. Use `Sound(...)` on the ground impact and `VFX(Dust)`; `HitStop(ms)` mirrors the attacker's. Control
and i-frames come from the server, not the markers.

## Common mistakes → fix

| Mistake | Fix |
|---|---|
| React fades in | fade 0: snap |
| Weak first frame (it's frozen during hitstop) | make frame 1 the strongest, clearest pose |
| Same react for every direction | at least front/back/left/right |
| Stagger slides | real steps with foot plants |
| Body hits the ground and stops | 1–2 f impact, compress/bounce, then a breathing down hold |
| Get-up floats | weight over the support (hand/foot) before every push |

## What to look for in a reference

Two-actor timing (attacker contact frame vs victim's first react frame; offset 0 expected); the victim's first pose;
hitstop on the victim; direction and strength tiers; head lag; stumble steps; fall time and bounce; down hold; get-up
style and length; when control returns.

## GAPS (training fills these)

Almost all of it: react lengths by tier, stagger step counts, fall and bounce timing, get-up variants (front, back,
roll, kip-up), KO poses, launch/juggle reactions, wall-splats, grab reacts, and how physically driven versions compare
to keyed ones.

# Category: world (doors, lifts, platforms, pickups, breakables, props, creatures)

Status: seed study, **almost all UNTESTED**. The theory notes have no world-animation coverage; the only SOURCED
hints are easing choices (Linear for machines, Bounce for bouncy props) and the UI spring/tween timings
(`UI_Animation_And_Springs`). Every number below is Claude's reasoning from physics (Roblox gravity 196.2 studs/s²),
mechanism and readability, labelled UNTESTED, to be replaced by measured references. Frames at 60 fps.

## How world motion is built and replicated (UNTESTED, phase 3 checks)

- **The server owns the state** (open/closed, position on a route, collected), plus a start time
  (`workspace:GetServerTimeNow()`); **each client animates locally** from that state (TweenService or a runtime
  player sampling a `tween` track at `t`). Server-side tweens of CFrame replicate at network rate and look choppy.
- Anything a player stands on must move physically (a constraint such as a PrismaticConstraint, or CFrame plus a
  matching `AssemblyLinearVelocity`), or players slide off it. Purely visual props can tween freely.
- World rigs with moving parts use an AnimationController + Animator and joints (or Bones), so `keyframes` works too.
- Deterministic sampling (`sample(t)`) lets captures freeze any frame.

## Scope of the house rule

"Every part keeps moving" is written for characters. **Reasoned reading:** it applies to anything alive (creatures,
characters on props) and to idle loops of magical/pickup props; machines at rest (a closed door, a parked lift) may be
still. **Pending the user's ruling**: it is a proposed carve-out to the house rule (README: exception none), not settled; do not assume it.

## Starting numbers (all UNTESTED)

| Element | Motion | Numbers | Easing |
|---|---|---|---|
| Hinged door | open | 24–48 f (0.4–0.8 s), overshoot 2–5° then settle 6–10 f | CubicV2 Out |
| Hinged door | close / slam | 18–30 f, 1–2 f impact + 1 small bounce (1–3°) | CubicV2 In → Constant contact |
| Sliding door | open/close | 18–36 f | CubicV2 InOut (mechanical), a 1–2 f stop jolt |
| Heavy vault door | open | 90–180 f with a 6–12 f shudder before it moves (anticipation) | Linear middle, eased ends |
| Lift / elevator | travel | 8–16 studs/s; ease in/out 18–36 f each; arrival settle 0.05–0.1 studs bounce | CubicV2 InOut ends, Linear cruise |
| Moving platform | ping-pong | 4–12 studs/s; pause 30–90 f at each end | sine (InOut) for patrols; Linear for conveyor-like |
| Pickup idle | bob + spin | bob 0.25–0.5 studs, period 1.5–2.5 s (sine); spin one turn per 3–6 s | sine bob; Linear spin; bob and spin periods not multiples (no visible loop) |
| Pickup spawn | pop in | spring ζ 0.5–0.7, 6–18 f (100–300 ms) | spring / Back-like overshoot |
| Pickup collect | pop out | scale ×1.2 in 4–6 f, then to 0 in 8–12 f (exit ≈ 2/3 of entrance) | Out, then In |
| Button | press | in 3–6 f, hold 1–2 f, return 8–12 f | Constant in, CubicV2 Out back |
| Lever | throw | 10–20 f, hard stop + 1–2 f kick | CubicV2 In → Constant |
| Crumbling platform | warn → fall | shake 30–60 f (±0.05–0.15 studs, rising 3 → 10 Hz), then free fall under gravity; respawn after 3–5 s with a fade-in 12–18 f | shake noise; fall is physics or `y = ½·g·t²` |
| Breakable (crate, wall) | break | 1–2 f hit flash/hold, pieces fly with physics, debris fade 0.5–2 s | physics |
| Hanging sign / lamp | swing | pendulum period `T = 2π√(L/g)`: a 2-stud arm ≈ 0.63 s, 8 studs ≈ 1.27 s; damp out over 3–6 swings | spring ζ 0.05–0.15 |
| Flag / cloth / foliage | sway | spring k 50–100, ζ 0.3–0.5 (settle 48–113 f, `timing.md`); wind noise 0.2–1 Hz | procedural |
| Trap (spikes, crusher) | telegraph → strike → reset | telegraph 30–60 f (same as an enemy telegraph), strike 2–6 f, hold 12–30 f, reset 30–60 f | Constant strike; CubicV2 InOut reset |

## Creatures (UNTESTED; character principles apply)

- The 12 principles, overlap, moving holds and lint all apply as for characters.
- Bigger creatures move slower: cycle time scales roughly with √(leg length) (dynamic similarity); a creature with
  legs 2× a humanoid's walks with a cycle ~1.4× longer.
- Quadrupeds: walk = 4 beats (each foot in turn), trot = diagonal pairs, gallop = with a flight phase; the head bobs
  against the shoulders; the tail lags 3–6 f like a cape.
- Fliers: flap cycle shorter for smaller wings (small 6–15 f, large 30–60 f); down-stroke faster than up-stroke.
- Idle: breathing 2–4 s scaled up with size, a weight shift, a look-around.

## Markers

`Open`, `Closed`, `Trigger` (the moment gameplay changes: plate pressed, trap armed), `Settle` (motion finished:
safe to interact), plus `Sound(...)` on every contact and `VFX(...)`. Gameplay listens to the server's state, never
to client markers.

## Common mistakes (reasoned)

| Mistake | Fix |
|---|---|
| Door moves at constant speed and stops dead | ease out with a small overshoot; a slam gets a bounce |
| Pickup bob and spin share a period | make periods unrelated so the loop never reads |
| Platform tweened on the server | server state + time; clients animate; physics for riders |
| Breakable just disappears | a 1–2 f hit hold, then physics pieces and a fade |
| Machinery with no anticipation | a short shudder or wind-up sound before heavy motion |

## What to look for in a reference

Duration per motion; ease shape (look at spacing on the onion sheet); overshoot and bounce counts; pauses at ends;
telegraphs and how long they read; sound sync on contacts; loop periods for idles (`numbers.cycle`).

## GAPS (training fills these)

Everything: every row above is a reasoned guess. Priorities: doors (open/slam), pickups (idle, collect), moving
platforms, breakables, creature gaits. Also: vehicles, destructible environments, interactive props held by
characters (two-actor sync with `weapon.md`'s attach rules).

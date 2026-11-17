# Category: weapon (guns and melee weapons)

Status: seed study. **Melee** numbers are SOURCED (`Weapon_Animation`). **Guns** are thin in the theory notes: only
the kick, recoil return, camera kick and aim-offset layering are SOURCED; every other gun number below is **UNTESTED**,
reasoned from how the motion has to work (mass, hand travel, readability) and common shooter feel, and must be
replaced by measured references. Frames at 60 fps.

## Rig facts (both kinds)

- The weapon needs a joint to the hand (Motor6D, or an AnimationConstraint on upgraded rigs) named as the animation
  expects, and `Massless` parts. Moving parts (bolt, magazine, slide, pump, charging handle) each need their own joint
  under the weapon. SOURCED `Rigging_Motor6D`.
- **Joint kind (resolved):** the recreation pipeline's pose Luau and the weapon note's recoil code both assume
  Motor6D. That is stale since the Avatar Joint Upgrade: type joints as `Motor6D | AnimationConstraint`, never
  `IsA("Motor6D")` alone, never write `C0` on an AnimationConstraint (read-only). Procedural recoil multiplies into
  `Transform` in PreSimulation, which works on both.
- Joint transforms don't replicate: cosmetic gun-part motion is drawn on each client from a replicated 0–1 state
  (`parts` target), and never gates gameplay (ammo, fire timing and reload completion stay on the server).
- Guns are a **script layer** on top of keys: aim offsets, sway, recoil and kick are procedural springs; keys carry
  the big beats (equip, reload, bolt, holster). SOURCED `Weapon_Animation`.

## Guns: anatomy and starting numbers

| Beat | Starting numbers | Easing / notes | Status |
|---|---|---|---|
| Equip (draw → ready) | pistol 15–20 f, rifle 24–36 f; `Equip` marker = first frame it can fire | CubicV2 Out into the ready pose; a 2–4 f settle overshoot on the hands | UNTESTED |
| Holster | ≈ 2/3 of the equip (pistol 10–14, rifle 16–24) | exits faster than entrances | UNTESTED (exit ratio SOURCED `UI_Animation_And_Springs`) |
| Idle sway (hip) | breath 3 s; 0.3–1° rotation, 0.01–0.03 studs; heavy weapons via a spring k 80–150, ζ 0.6–0.8 (settle 25–45 f) | never a frozen hold (HOUSE) | sway spring SOURCED; amplitudes UNTESTED |
| Aim offsets | 3 poses (up, mid, down) blended by camera pitch, at Action2 | | SOURCED `Weapon_Animation` |
| Fire: kick | 1–2 f to peak | Constant/Linear into the peak | SOURCED |
| Fire: recoil size | pistol 3–6° pitch up + 0.05–0.15 studs back; rifle 1–3° + 0.03–0.08 studs; shotgun/sniper 6–12° + 0.15–0.3 studs | | UNTESTED |
| Fire: return | semi-auto: back to zero **within the fire interval** (600 RPM = 6 f) | | SOURCED |
| Fire: camera kick | opposite the fire direction; 0.3–1.5° pitch per shot, decays in 6–15 f | | direction SOURCED; size UNTESTED |
| ADS in | pistol/SMG 8–15 f, rifle 15–24 f, sniper 24–36 f | CubicV2 Out; FOV 70 → 50–60 (scopes 20–30) on the same curve | UNTESTED |
| ADS out | ≈ 2/3 of ADS in | CubicV2 In/Out | UNTESTED |
| Reload, tactical (rounds left) | pistol 72–100 f (1.2–1.7 s), rifle 100–150 f (1.7–2.5 s) | beats below | UNTESTED |
| Reload, empty | tactical + 18–30 f for the bolt/slide/charge | | UNTESTED |
| Bolt action cycle | up 4–6, back 4–6, forward 4–6, down 3–5 = 15–21 f, plus lower/raise 6–10 each | hard Constant/Linear stops at each end (metal on metal), 1–2 f kick on the slam | UNTESTED |
| Pump | back 5–8, forward 5–8 = 10–16 f | back slower than forward; snap at the front | UNTESTED |
| Charging handle / slide release | pull 4–6 f, release snap 1–2 f | the release is the readable beat | UNTESTED |
| Sprint pose | gun lowered/canted 30–60° | moving hold | UNTESTED |
| Sprint-to-fire | 6–12 f from sprint pose to ready | CubicV2 Out; fire allowed at the end | UNTESTED |

### Reload beats (UNTESTED order, reasoned from hand travel)

1. **Lower and tilt** the gun 6–10 f (turn the mag well toward the off-hand), away from the reticle (SOURCED: reload
   away from the reticle / to the off-hand).
2. **MagOut**: thumb the release, the old magazine drops (a `prop` actor that detaches; gravity in script) 3–6 f.
3. **Reach**: off-hand to the pouch and back 12–20 f (the long, slow beat; keep it moving).
4. **MagIn**: align 4–8 f, then a 2–3 f push and a 1–2 f hard seat with a small whole-gun kick (the beat to sell).
5. **Chamber** (empty only): bolt/slide/charging handle, as above.
6. **Raise** back to ready 8–12 f; `End` when it can fire.

### The recoil spring vs the fire interval (resolved, reasoned)

The theory's snappy recoil spring (k 400–600, ζ 0.5–0.7) settles in **14–24 f** (`timing.md`, corrected), longer than
a 600 RPM fire interval (6 f), and the source's kick (reset to 1 per shot, decaying 10/s) fades in only ~0.1 s, so it does **not** carry over
between shots. At automatic rates the recoil **accumulates** between shots from the spring alone. Use this: semi-auto and single shots return to zero within the interval
(stiffer spring: settle in T s needs `k = (4/(ζT))²`, e.g. 6 f at ζ 0.7 → k ≈ 3,300); automatic fire may accumulate
on purpose (that is the recoil pattern), capped, with a 15–30 f recovery after the trigger is released. UNTESTED.

## Melee weapons (SOURCED `Weapon_Animation`)

| Weapon | Anticipation | Motion | Recovery / hitstop |
|---|---|---|---|
| Dagger / light blade | 2–4 f | wrist-led snap, small arcs, tip leads | quick settle, hitstop 4–6 |
| Katana / longsword | 4–8 f | shoulder → wrist cascade, clean wide arc, 1 f smear | overshoot 10–15%, hitstop 6–10 |
| Greatsword / hammer | **hold** 8–15 f | hips lead 3–4 f, blade lags, visible fight against momentum | overshoot 15–25%, hitstop 10–16, long recovery |
| Spear | 4–8 f | linear thrust with a step-in; arc only on sweeps | retract 1.5× the thrust time |
| Dual blades | 2–4 f | each recovery is the next hit's wind-up, alternate sides | short |

Heavier = longer anticipation **hold** and a later tip overshoot, **not** a slower strike. Combos alternate tip arcs
(high → low, left → right) so recoveries lead into anticipations. Weapon/tip lags its hand 3–6 f. Frame data and combo
windows as in `combat.md`.

## Easing

Melee as `combat.md`. Guns: mechanical parts (bolt, slide, pump, mag seat) move Linear into Constant hard stops, with a
1–2 f kick on impact; hands and body ease (CubicV2 Out into poses). Recoil is a spring, not keys.

## Markers (canonical; aliases)

`Equip`, `Holster`, `AimIn`, `AimOut`, `Fire` (alias `Shoot`), `MagOut`, `MagIn`, `BoltBack`, `BoltForward`,
`Chamber` (`Reload` is not a marker: split it into its beats), plus `Sound(...)` on every metal contact (mag seat, bolt
slam) and `VFX(MuzzleFlash)`. Melee uses the combat set. Sound sync matters more for guns than anything else: a mag
seat 2 f off the sound reads as wrong.

## Common mistakes → fix

| Mistake | Fix |
|---|---|
| Reload is one smooth slide | split into beats with hard metal stops and sound on each |
| Gun freezes between beats | moving holds; hands keep drifting (HOUSE) |
| Recoil keyed in the animation | procedural spring layer; keys only for the big beats |
| Mag teleports | the mag is its own prop actor with an attach/detach frame |
| Reload covers the reticle | tilt toward the off-hand, keep the sight line clear |
| Heavy weapon swings slowly | hold longer before the strike; keep the strike fast |

## What to look for in a reference

Guns: frames per reload beat, which beat is "sold" (seat, slam), off-hand path, how far the gun drops from the sight
line, recoil size and return per shot (strips around each shot), camera kick, ADS duration and FOV change, sound
offsets per metal contact, sprint-to-fire time. Melee: tip arc (onion), lead order (hips → shoulder → wrist → tip),
grip changes, overshoot size, hitstop.

## GAPS (training fills these)

- Every gun number marked UNTESTED: reload beat timings per weapon class, ADS durations and FOV, equip/holster, bolt and pump cycles, recoil sizes per RPM, sprint-to-fire.
- Viewmodel (first-person arms) conventions vs third-person.
- Launchers, bows, throwables (grenade pull-and-throw), shields, two-handed vs one-handed switching.
- Sheathe/unsheathe and flourishes for melee.
- Inspect animations.

# Timing: budgets, easing, hitstop, fades, springs

All frames **at 60 fps** (`@30` = half, rounded). `ms = f × 16.7`. Ranges are starting points: the category file
and the vault's measured medians override them. Ladder status per row.

## Words used loosely in the sources (fixed here)

| Word | Means here | Not |
|---|---|---|
| **Startup** | press → first active frame (includes the fade-in and the anticipation) | the wind-up pose alone |
| **Anticipation** | the visible wind-up: first frame moving away from idle → wind-up extreme | startup |
| **Active** | frames the hit can land (`HitStart`…`HitEnd`), ≥1 f | the whole swing |
| **Recovery** | `HitEnd` → control regained (`MoveCancel`/`End`) | the clip's tail |
| **Combo window** | opens after the last active frame (+ hitstop), closes 8–12 f into recovery; input is buffered earlier | a fixed clip frame |

**Light anticipation: use 2–4 f** (snapped from idle) inside a 4–6 f startup. The "3–5 f" in `Animation_Principles`
is stale: it counts startup, not the wind-up pose (`Animation_Polish_Checklist` and `Attack_Animation_Anatomy` agree on 2–4).

## Frame budgets per category (summary; details in `categories/`)

| Category / move | Anticipation | Strike / smear | Active / contact | Recovery | Total | Status |
|---|---|---|---|---|---|---|
| Light attack (fist, dagger) | 2–4 | 3–5 + 1 smear | 2–3 (contact hold 3–8 with hitstop) | 10–14 | 25–35 | SOURCED `Attack_Animation_Anatomy`, `Combat_Animation_Frame_Data` |
| Combo hit 2–3 | 3–5 (from the previous recovery) | 3–4 | 3 | 12–16 | 30–40 | SOURCED |
| Finisher | 8–12 startup | 3–5 | 4–6 | 20–30 | 45–60 | SOURCED |
| Heavy / charged | 6–12 (or hold 8–15) in 18–30 startup | 5–10 | 4–6 | 25–40 | 45–90 | SOURCED |
| Ground slam | 20–35 startup | 3–4 | 3–4 | 30–45 | 60–90 | SOURCED |
| Projectile cast | 10–16 (spawn on last) | — | — | 15–25 | 30–45 | SOURCED |
| Ultimate | snap 2–4 + hold 30–90 | 2–6 + 1–3 smear | impact hold 18–30 | long, late cancel | ~60 cast | SOURCED `Ability_And_Ultimate_Animation` (NV) |
| Dodge | 2–4 startup | — | i-frames 26–28 | — | — | SOURCED (NV) |
| Walk / run / sprint cycle | — | — | — | — | 60–80 / 32–40 / 24–32 | SOURCED `Locomotion_Animation`; MEASURED n=1 jog 31, strafe/back 37–39 |
| Jump | crouch 2–4 | ascent max stretch 3–5 | apex hang 2–4 | land 4–8 | — | SOURCED; fps ambiguous (see `categories/loco.md`): all four numbers share one unstated-fps source, so they move together if it proves @30 |
| Gun kick | — | 1–2 | — | back to zero within the fire interval (600 RPM = 6 f) | — | SOURCED `Weapon_Animation` |
| World / camera | see their files (UNTESTED) | | | | | |

Rules of thumb: follow-through ≥ anticipation and usually >50% of the clip (SOURCED). A strike over 2 f reads fast,
over 5 f slow (SOURCED `Spacing_And_Easing`). Heavier = longer anticipation **hold**, not a slower strike
(SOURCED `Weapon_Animation`). Locomotion medians (MEASURED n=10, one stylised source set): anticipation 184 ms,
follow-through 667 ms, ratio 3.6, hold 29% of the clip, limb lag 2 f, detachment 0.4 studs.

## Overshoot and settle

Overshoot peaks **~4 f** after the key, then settles over **4–12 f**. The source wrote "settle 2–6 f" next to an
overshoot given at 24–30 fps, so 2–6 is @30: the "2–6 f at 60" reading is stale (fps ambiguity). Size: 10–30%
past the key (katana 10–15%, greatsword 15–25%). Whole-body follow-through settle 8–20 f. Status: SOURCED
`Spacing_And_Easing`, the @60 conversion reasoned.

## Easing per phase (easing **leaving** each key)

| Into… | Easing on the key before it | Status |
|---|---|---|
| Anticipation / wind-up extreme | CubicV2 Out (decelerate into the extreme) | SOURCED `Spacing_And_Easing` |
| Away from an extreme (start of the strike) | CubicV2 In or Linear | SOURCED |
| Contact | Linear, or Constant for a stepped snap | SOURCED |
| Overshoot | CubicV2 Out | SOURCED |
| Settle | CubicV2 InOut | SOURCED |
| Real reversals (>100°) | InOut allowed; elsewhere InOut makes every part stop on every key | SOURCED |
| Mechanical / world motion | Linear (machines), Bounce (bouncy props), Elastic only for cartoon wobble | SOURCED (hints) + UNTESTED |
| Anime-stepped attacks | Constant; holds 3–6 f; transitions 1–3 f with one smear key | SOURCED `Anime_Style_3D_Animation` (NV) |

Always **CubicV2**; legacy `Cubic` is deprecated and stale wherever a note still says "Cubic". Lint warns at >70%
Linear keys. Elliptical sway is keyed at least every quarter period.

## Hitstop (freeze on contact)

`Hit_Stop` is the home of these numbers and wins: light 2–4, standard 5–7, heavy 8–12, ultimate 15–30.
The frame-data table's 3–4 (light) and 8–12 (heavy) sit inside it. The research report's 4–8 / 8–12 / 12–20 is a
**stylised fighting-game band**: use it only when the brief says "heavy, crunchy, anime-impact"; it is not the default.

| Hit | f | s | Notes |
|---|---|---|---|
| Light / combo filler | 2–4 | 0.03–0.07 | shrink on hits 2..n |
| Standard | 5–7 | 0.08–0.12 | |
| Heavy / finisher | 8–12 | 0.13–0.2 | the combo's big one |
| Ultimate | 15–30 | 0.25–0.5 | release with a slow-mo tail: speed 0 → 0.3 over a few frames → 1 |
| Blocked | 60–70% of the hit | | attacker only |

Scaling formula (fighting-game precedent): `f = 0.65·d + 6`, cap 30 (d = damage %). Attacker freezes on the
connecting frame, victim on frame 1 of the flinch (author that frame as a strong pose). Victim shakes ±0.1–0.2 studs;
camera shake keeps running; sound never freezes; springs freeze. Hitstop time is added to server recovery. Run it
per client (`AdjustSpeed(0)` replicates unreliably). Status: SOURCED `Hit_Stop`.

## Fades (`Play(fadeTime)`)

| Transition | s | f | Status |
|---|---|---|---|
| Idle → light attack | 0–0.05 | 0–3 | SOURCED `Animation_Priority_And_Blending` |
| Combo hit n → n+1 | 0.05–0.08 | 3–5 | SOURCED |
| Attack → idle | 0.15–0.3 | 9–18 | SOURCED |
| Any → hit-react / stagger | 0 | 0 | SOURCED |
| Any → death | 0.05 | 3 | SOURCED |
| Aura / charge loop in | 0.2 | 12 | SOURCED |
| Locomotion play / stop | 0.15 / 0.2 | 9 / 12 | SOURCED `Locomotion_Animation` |
| Stepped (anime) clips in | ≤0.05 | ≤3 | SOURCED (NV) |

The default 0.1 s fade hides ~6 f: an anticipation inside the first 6 f vanishes. Fades change perceived timing:
judge in game context.

## Springs (procedural layers)

Settle time (to ~2%) ≈ **4 / (ζ·ω)**, ω = √k (unit mass). For ζ ≥ 1 use ≈ 5.8/ω instead. The settle times in
`Procedural_Animation` (snappy 8–12 f, flinch 15 f) are **optimistic and stale**; the corrected values:

| Look | k | ζ | Settle (corrected) | Status |
|---|---|---|---|---|
| Snappy recoil | 400–600 | 0.5–0.7 | 0.23–0.40 s = **14–24 f** | SOURCED `Procedural_Animation`, settle computed |
| Hit flinch shove | 300 | 0.4 | 0.58 s = **35 f** | SOURCED, computed |
| Heavy weapon sway | 80–150 | 0.6–0.8 | 0.41–0.75 s = **25–45 f** | SOURCED, computed |
| Cape / hair lag | 50–100 | 0.3–0.5 | 0.8–1.9 s = **48–113 f** | SOURCED, computed |
| Smooth follow (critical) | 150 | 1.0 | ≈0.47 s = **28 f**, no overshoot | SOURCED, computed |
| Lean into movement | 8 Hz natural freq (ω ≈ 50, k ≈ 2500) | 0.7 | ≈0.11 s = 7 f | observation n=1 (one dash study's recipe; UNTESTED elsewhere) |

To settle in T seconds pick ζω = 4/T, so k = (4/(ζT))². Example: settle in 6 f (0.1 s) at ζ 0.7 → k ≈ 3,300.
Damping coefficient `d = 2ζ√k`. Sub-step at 120 Hz (explicit Euler explodes at low fps with high k); freeze springs
during hitstop; skip when `Animator.EvaluationThrottled`; cull beyond ~60 studs. Status: SOURCED `Procedural_Animation`.

UI-adjacent springs (menus, world pickups' pop-ins): ζ 1 default, 0.5–0.7 playful, <0.4 wobbly; 100–300 ms;
exits ≈ 2/3 of entrances; nothing triggered repeatedly over 500 ms; stagger 20–40 ms, capped 250 ms.
SOURCED `UI_Animation_And_Springs`.

## Idle breath

Use **2–4 s per breath, default 3 s** (SOURCED `Locomotion_Animation`; MEASURED n=1 idle at ~3 s), with 4–8 f
offsets on head and arms, 0.5–1° waist amplitude, a weight shift every 6–10 s. The "60–120 f" (1–2 s) breath in
`Overlap_Offset_And_Arcs` is stale as a default: it reads as panting; keep it for exertion idles (after a sprint, low HP).

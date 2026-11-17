# Category: combat (unarmed attacks, combos, frame data)

Status: seed study. Numbers SOURCED from the theory notes unless marked; no combat reference measured yet. Frames at
60 fps. Melee weapons: `weapon.md`. Hit-reacts, stagger, knockdown: `reaction.md`. Dash attacks and ultimates: `ability.md`.

## Anatomy (phases)

| Phase | Animation content | Systems on | Marker |
|---|---|---|---|
| Startup | fade-in (0–3 f) + anticipation (wind-up pose, snapped from idle) | windup VFX, whoosh pre-roll | `WindupStart` |
| Active | strike/smear frames, contact pose | hitbox on, slash VFX, trail | `HitStart` … `HitEnd` |
| Hitstop | freeze on contact (both actors) | shake keeps running, sound plays | `HitStop(ms)` |
| Recovery | overshoot → settle → back to idle or the next hit's anticipation | combo window, cancel windows, trail off | `ComboWindowOpen`, `MoveCancel`, `End` |
| Victim hitstun | flinch / stagger (`reaction.md`) | victim can't act; longer than the attacker's remaining recovery = "plus on hit" | — |

Shape of every good attack: snap into a readable anticipation, strike in a handful of frames (often a 1 f smear), then
spend most of the clip in a cancellable follow-through. **Weight lives in the recovery, responsiveness in the startup.**
SOURCED `Attack_Animation_Anatomy`.

## Starting numbers (frame data)

| Move | Startup (antic) | Active | Recovery | Hitstop | Total | Status |
|---|---|---|---|---|---|---|
| Light jab / fist | 4–6 (2–4; fists 2–3) | 2–3 | 10–14 | 2–4 | 25–35 | SOURCED `Combat_Animation_Frame_Data`, `Weapon_Animation` |
| Combo hit 2–3 | 5–7 | 3 | 12–16 | 3–4 (shrink on 2..n) | 30–40 | SOURCED |
| Combo finisher | 8–12 | 4–6 | 20–30 | 6–10 | 45–60 | SOURCED (`Hit_Stop` tiers). Resolved: the frame-data table's 6–10 wins over the tier table's 8–12, because it is the frame-data table's own number for a 45–60 f finisher and the tier table is the older, coarser source; heavies keep 8–12 |
| Heavy / charged | 18–30 (6–12, or a hold 8–15) | 4–6 | 25–40 | 8–12 | 45–90 | SOURCED |
| Ground slam AoE | 20–35 | 3–4 | 30–45 | 10–14 | 60–90 | SOURCED |
| Enemy telegraph (NPC) | 30–60 (0.5–1.0 s) | — | — | — | — | SOURCED `Attack_Animation_Anatomy` |

Poses and spacing: extremes ≥25° from rest on driver joints, pushed 10–30% (battlegrounds style 20–30%); strike 3–5 f
+ 1 smear; contact hold 3–8 f including hitstop; overshoot ~4 f past contact then settle 4–12 f; follow-through ≥
anticipation, usually >50% of the clip. Detachment (R6 look): punch 0.3–0.8 studs, pull-back 0.2–0.5, smear 0.5–1.0
for exactly 1 f, 0 on holds and contacts; R15 keeps ~60%. MEASURED (loco only so far): limb lag median 2 f.

**Anticipation vs startup:** use 2–4 f anticipation for light player attacks inside a 4–6 f startup; the "3–5 f light
anticipation" in `Animation_Principles` is stale (it counted startup). Fade into attacks with `Play(0)`–0.05 s: the
default 0.1 s fade hides ~6 f and eats the anticipation.

**Combo window (resolved):** opens on the first frame after the last active frame + hitstop, closes 8–12 f into
recovery; buffer input from earlier (as soon as the hit lands). The older definitions agree once phases are counted:
"~f12–15" (light, `Attack_Animation_Anatomy`) = 5 startup + 3 active + 4 hitstop; "opens f9" in the frame-data
walkthrough is a 2-active light with 4 f of hitstop that does not advance the clip's frames (hitstop is held game time, so the clip's own frame numbers skip it). `MoveCancel` (movement/dodge may interrupt) ≈ 50% of the clip. Hit N's
recovery leads into hit N+1's anticipation; the combo-to-combo fade is 0.05–0.08 s (3–5 f).

## Easing

| Into | Easing (leaving the previous key) |
|---|---|
| Wind-up extreme | CubicV2 Out |
| Strike | CubicV2 In or Linear |
| Contact | Linear, or Constant for an anime-stepped snap |
| Overshoot | CubicV2 Out |
| Settle → idle | CubicV2 InOut |

Anime-stepped style: Constant easing, holds 3–6 f (each a moving hold: HOUSE), transitions 1–3 f with one smear key,
contact on a fixed tick, fade-in ≤0.05 s (SOURCED `Anime_Style_3D_Animation`, NV).

## Lead order (resolved)

The punch sources seem to disagree (torso leads vs arm leads). **Use the cascade:** in the anticipation and the
strike's start, hips → chest → arm lead down the chain (chest 1–2 f after hips, upper arm 2–3 f after chest); on the
strike itself the **striking arm may lead** and the upper body lurches into contact 1–2 f behind it. Both sources agree
on the real rule: parts never share a stop frame. SOURCED `Overlap_Offset_And_Arcs`.

## Markers (canonical; aliases → canonical)

`WindupStart` (alias `Windup`) · `HitStart`/`HitEnd` (`HitboxOn`/`HitboxOff`) · `ComboWindowOpen` (`CancelWindow`) ·
`MoveCancel` (`Recover`) · `End` · plus `Sound(Swing)` 2–4 f before the smear, `VFX(Slash)` on the first smear frame,
`VFX(TrailOn)` 1 f before the swing and `VFX(TrailOff)` 2–4 f after, `HitStop(ms)`. `HitStart` 1 f before visual
contact; markers within 1 f of the frame data; `End` 1–2 f before the last frame. Hitstop time adds to server
recovery. Never take damage timing from client markers.

## Common mistakes → fix

| Mistake | Fix |
|---|---|
| Everything starts and stops together | overlap cascade 2–4 f per link |
| Weightless hit | longer follow-through, overshoot, hitstop, a strong victim first frame |
| Unreadable | stronger anticipation **pose** (near-opposite of contact); check from the gameplay camera |
| Slow-feeling attack | shorten startup, not recovery; snap the anticipation from idle |
| Mushy combos | short fades (3–5 f), recovery of hit N = anticipation of hit N+1 |
| Lunge baked into the root | animate in place, move the character in script on markers |
| Long hitstop on every combo hit | shrink on hits 2..n; spend the big one on the finisher |

## What to look for in a reference

Startup/active/recovery frames (frame-data row) · anticipation pose and how long it holds · smear frames and
detachment · contact frame vs energy peak · hitstop length on attacker and victim (two-actor timing: attacker contact
f vs victim's first react f) · cancel points (where the next input fires) · lead order (which region peaks first) ·
overshoot size and settle · whoosh/impact sound offsets · what VFX fill (trails, slash meshes).

## GAPS (training fills these)

- No combat reference measured yet: every number above is SOURCED theory; medians start at n=1.
- Kicks, grabs/throws, aerial attacks, launchers, juggles: no numbers.
- Directional variants (forward/back/side attacks) and how they share frames.
- Block, parry and guard-break animation timing.
- Hit-confirm branching (a different recovery on hit vs whiff).
- The R15 straight-limb look on strikes: how much elbow is allowed before it reads "bendy" (HOUSE says none except where R6 cheated).

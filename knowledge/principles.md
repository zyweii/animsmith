# Principles as checkable rules

The 12 principles of animation, then the polish rubric, each as a rule with a threshold, how it's checked (`lint` = done
today by `anim_spec.py lint`; `eye` = a reviewer or the user; `v2 lint (planned)` = not in lint v1, so check it by eye until
built), and its ladder status. Frames at 60 fps.
Lint is heuristic: zero warnings is not a good animation. Appeal, staging and silhouette are eye checks.

## The 12 principles

| # | Principle | Checkable rule | Check | Status |
|---|---|---|---|---|
| 1 | Squash and stretch | Rigid Roblox parts can't scale in a track: fake it with body compress (root drop + knee plant), 1-frame limb detachment on smears, smear meshes, trails, particle squash | eye | SOURCED `Animation_Principles` |
| 2 | Anticipation | Player attacks: a readable wind-up pose within 2–4 f of the press; heavy 6–12 f (or a hold of 8–15 f); enemy telegraphs 0.5–1.0 s. Anticipation and contact poses near-opposite | lint (info report of startup from `HitStart`, no threshold) + eye ("is f2 a clear wind-up silhouette?") | SOURCED `Animation_Polish_Checklist`, `Posing_And_Exaggeration` |
| 3 | Staging | The attack direction reads from the **gameplay camera** (3/4 rear, 30–45° up); arms away from the torso; weapon never behind the body on the hit frame | eye | SOURCED `Posing_And_Exaggeration` |
| 4 | Straight ahead vs pose to pose | Pose to pose: key contact, extreme, recovery first, then breakdowns; keys are key poses + breakdowns, not baked frames (jitter warn if >50% of frames keyed) | lint (jitter) | SOURCED `Animation_Principles` |
| 5 | Follow-through and overlap | Successive breaking down the chain: chest 1–2 f, head 2–4, upper arm 2–3, hand 2–3 after its parent, weapon/cape 3–6; hand lag >6 f = floaty/drunk; L/R ≥1–2 f apart | lint (no-overlap, twinning) | SOURCED `Overlap_Offset_And_Arcs`; MEASURED n=10 limb lag median 2 f |
| 6 | Slow in, slow out | Fast in, slow out. Easing **leaving** a key: Out into an extreme, In/Linear away from it, Linear/Constant into contact, InOut only on settles and real reversals (>100°) | lint (>70% Linear warn; legacy Cubic warn); v2 lint (planned): InOut everywhere warn | SOURCED `Spacing_And_Easing` |
| 7 | Arcs | Hand/tip traces a clean arc except deliberate breaks at impact; a 1/8-cycle phase offset between two axes = oval arc, 1/4 = circle; COG moving evenly in a straight line → flag | eye (onion sheet, trail preview); v2 lint (planned): COG flag | SOURCED `Overlap_Offset_And_Arcs` |
| 8 | Secondary action | Off-hand clench, head turn, look-at (neck 60 / waist 40) on its own low-weight layer or procedural | eye | SOURCED `Procedural_Animation` |
| 9 | Timing | Frame counts per category in `timing.md`; strike over 2 f reads fast, 5 f reads slow | eye against `timing.md` (lint only prints a startup/recovery info line) | SOURCED `Spacing_And_Easing` |
| 10 | Exaggeration | Push extremes 10–30% past "real" (battlegrounds style 20–30%); exaggerate extremes, never breakdowns; combat extremes ≥25° from rest on driver joints | lint (timid-pose warn) | SOURCED `Posing_And_Exaggeration` |
| 11 | Solid drawing | Hips over the support foot; no L/R twinning (mirror + offset ≥1–2 f and a few degrees) | lint (twinning) + eye | SOURCED `Animation_Principles` |
| 12 | Appeal | A strong line of action from foot to hand/tip on every key pose; clear, characterful silhouettes | eye | SOURCED `Animation_Principles` |

## Polish rubric (13 rules)

The source checklist says "12 rules" and lists 13; rule 13 is the user's house rule, added later. **Use all 13.**

| # | Rule | Threshold | Lint | Status |
|---|---|---|---|---|
| 1 | Player attack anticipation snapped from idle | 2–4 f before `HitStart`'s wind-up; the first posed frame reads | lint (startup info report) | SOURCED `Animation_Polish_Checklist` |
| 2 | Follow-through ≥ anticipation | often >50% of the clip; cancellable via markers | lint (recovery info report; warns only when `HitStart` is missing); v2 lint (planned): full marker sets | SOURCED |
| 3 | Fast in, slow out | Linear/Constant into contacts, CubicV2 Out into extremes; one decisive speed peak per action on the chart | lint (>70% Linear, legacy Cubic) | SOURCED |
| 4 | Overshoot and settle | overshoot ~4 f after the key, settle 4–12 f at 60 after that; no frozen holds | lint (dead hold: whole body ≥12 f still) | SOURCED |
| 5 | Offsets down the chain | 2–4 f per link (1–2 f @30); no twinning | lint (no-overlap, twinning) | SOURCED |
| 6 | Hitstop scales with damage | both fighters, capped 30 f; decaying, visual-only shake | eye (feel test) | SOURCED `Hit_Stop` |
| 7 | Poses pushed | 10–30%; combat extremes ≥25° from rest | lint (timid pose) | SOURCED |
| 8 | Detachment only on fast frames | 0.3–0.8 studs on strikes, smear 0.5–1.0 for exactly 1 f, 0 on holds and contacts; <1 stud between frames | v2 lint (planned): max offset (v1 checks only root offset >2) | SOURCED `Limb_Detachment_Technique` (NV) |
| 9 | CubicV2, closed loops | no legacy Cubic; loop ends on a copy of the first pose | lint (legacy Cubic, loop seam) | SOURCED |
| 10 | Displacement in script | root offset ≤2 studs; travel from markers | lint (root displacement) | SOURCED |
| 11 | Clean keys | ≤50% of frames keyed | lint (jitter) | SOURCED |
| 12 | Arcs | clean arcs, deliberate breaks only on impact | eye | SOURCED |
| 13 | **Every part keeps moving** | no part <1.5°/s in the world **and** against its parent for ≥100 ms (6 f) | lint (still part; R15 and not `stepped` only) | **HOUSE** |

### Stillness: two thresholds, one winner

Use **rule 13 (per part, ≥6 f)**: it is the house rule and is stricter. The whole-body dead-hold check (≥12 f) is
kept only as a coarse early warning. `"stepped": true` (anime-stepped style) waives the dead-hold warning, **not**
rule 13: stepped holds of 3–6 f must still carry 2–5% drift on every part.

## Extra lint thresholds (from the theory notes)

| Check | Threshold | Lint | Status |
|---|---|---|---|
| Moving-hold drift | 2–5% of the move's range across the hold | eye | SOURCED `Spacing_And_Easing` |
| Smear speed | >45°/f is a smear (fine for 1–2 f); >45°/f into a **hold** = pop | lint (info on >45°/f frames; the into-a-hold pop is not separated: eye) | SOURCED `Posing_And_Exaggeration` |
| Key reduction | drop keys within 1.5–3° (0.05 studs root) of the interpolated curve | v2 lint (planned) | SOURCED `Video_Pose_Extraction` (NV) |
| Feet grounded | within 0.04 studs; planted slide ≤3–10% of ground speed | v2 lint (planned) | SOURCED `Locomotion_Animation` |
| Walk keys | only contact + passing → inverted bob: key down and up poses too | v2 lint (planned) | SOURCED `Locomotion_Animation` |
| Fade budget | anticipation inside the first 6 f with the default 0.1 s fade → warn | v2 lint (planned) | SOURCED `Animation_Principles` |
| Upper-body clip | leg keys present → warn (they lock the legs) | v2 lint (planned) | SOURCED `Animation_Priority_And_Blending` |
| Markers | required set present; within 1 f of the frame data; `End` 1–2 f before the last frame; active ≥1 f | lint (only `HitStart` presence); v2 lint (planned): full sets, timing, `End` | SOURCED `Combat_Animation_Frame_Data`, `Animation_Events_And_Markers` |
| Hand at face (R15) | elbow bend needed and upper arm ≥80° raised: the one place a straight R15 arm can't reach | v2 lint (planned) | SOURCED (pipeline lint) |
| Joint-safety | generated Luau that searches only `IsA("Motor6D")` or writes `C0` → fail (Avatar Joint Upgrade) | v2 lint (planned) | SOURCED `Rigging_Motor6D` |

## R15 limbs: the house rule beats the retarget notes

Use **straight, R6-like R15 limbs** (HOUSE). Bend elbows and knees only where R6 cheated with offsets: crouch,
landing compress, knee plant, hand-at-face. The retarget note's default 8–10° elbow bend, 60–100° elbows on strikes
and "replace fakes with real bends" are **stale** for this user's style: they predate the house rule (user review of
a locomotion set, which preferred the R6 look). They still apply to a game profile that explicitly asks for bendy
R15. Detachment carries over to R15 at ~60% of the R6 offset.

## Priority when a reference breaks a rule

Timing > posing > follow-through > spacing > arcs (SOURCED `Research_Report_Stylised_Animation`). Fix in that order.

# Reviewer lenses and output format

Source: the plan's §5.4 and the recreation pipeline's Stage 7. Status: seed, **UNTESTED** (no panel has run yet).
This file is the one home of the lens definitions. The vault's `Critic_Calibration` note holds only the lens names
(A. Poses and silhouette, B. Timing and spacing, C. Weight and follow-through) and their score offsets; rename, add
or remove a lens in both places in the same step.

## When the panel runs (2 rounds per build, never more)

| Checkpoint | Who reviews |
|---|---|
| Pass 1, blocking (key poses, stepped) | The user alone, with the pose sheet |
| Pass 3, the first full-motion version that passes the numeric gates (lint, motion, feet, timing) | Panel round 1, then the user |
| Pass 4, final (delivery, in context) | Panel round 2, then the user |

Three blind reviewers, fresh each round, one lens each, same evidence: the brief, the reference sheet (if any), our
key-pose sheet, film strips, onion sheet, one hero frame, the spacing chart and the numbers (lint, `anim_compare`).

## Scales

| Scale | When | Fidelity means |
|---|---|---|
| `absolute` | Default; every third-party or licensed reference ("inspired by") | Fit to the brief and the style profile; **never** closeness to another game's frames |
| `match` | The user's own recording, sketch or animation | Closeness to the reference: key poses, timing (compare ≥85, duration ×0.92–1.08, key-pose offset ≤2 f), silhouette |

## The lenses (check, then anchor)

### A. Poses and silhouette
Checks: line of action on every key pose; silhouette read from the **gameplay camera** (3/4 rear, 30–45° up);
anticipation and contact near-opposite; extremes pushed 10–30% (combat ≥25° from rest); no twinning; hips over the
support foot; R15 limbs straight unless R6 would have cheated (HOUSE); detachment only on fast frames; staging (attack
direction clear, weapon not behind the body on the hit frame); feet grounded within 0.04 studs.

| Score | Anchor |
|---|---|
| 1 | Key poses unreadable from the gameplay camera; stiff, symmetric or twinned; the move's intent unclear |
| 3 | Poses read and have a line of action, but extremes are timid or one key pose is muddy; minor twinning |
| 5 | Every key pose reads as a silhouette in under half a second; strong, varied lines of action; appeal |

### B. Timing and spacing
Checks: frame budget per phase vs `timing.md` and the category file; one decisive speed peak per action; strike 2–5 f;
fast in, slow out; easing per phase (Out into extremes, Linear/Constant into contact); overshoot ~4 f then settle 4–12 f;
hitstop on contact; markers within 1 f of the beats; fades don't eat the anticipation; loop seam clean (3× in a row).

| Score | Anchor |
|---|---|
| 1 | Even spacing everywhere (mechanical), wrong phase lengths, the hit lands late or soft; pops or a broken seam |
| 3 | Phase lengths in range and one clear peak, but easing generic (InOut everywhere) or a beat 2+ f off |
| 5 | Contrast of slow and fast sells every beat; contact snaps; the timing reads as intended at game speed |

### C. Weight and follow-through
Checks: follow-through ≥ anticipation; successive breaking (2–4 f per link, hand ≤6 f); overshoot size fits the mass;
heavier = longer anticipation hold, not slower strike; centre-of-mass path and weight shift; **every part keeps
moving** (no part still ≥100 ms: HOUSE); moving holds carry 2–5% drift; secondary motion (head, off-hand, cape, prop).

| Score | Anchor |
|---|---|
| 1 | Weightless or floaty; everything starts and stops on one frame; frozen parts |
| 3 | Follow-through present and parts offset, but mass is generic (light and heavy feel the same) or one part freezes |
| 5 | Mass is felt in every phase; overlap cascades cleanly; nothing is dead, nothing drifts aimlessly |

### Fidelity and Overall (every reviewer scores both)
- **Fidelity** (1–5) on the build's scale above.
- **Overall** (1–5): would this ship in a polished game as-is? 3 = acceptable with fixes; 5 = a reference-quality move.

## What each reviewer returns

1. **Scores 1–5**: its own lens, fidelity, Overall.
2. **6 ranked problems**, each with the frame range, the part, the numbers, and a concrete spec fix (a lever with
   values: `--overshoot "RightUpperArm@14:0.12:4"`, `--retime "0-12:0.75"`, a key change).
3. **REBUILD:** yes or no (yes = the beat sheet or key poses are wrong, not the polish).
4. **Works:** one line on what works.

## Merging the reviews

Fix first what two or more reviewers flag · skip a fix that contradicts a "works" · change values in half steps ·
one hypothesis per version · rebuild when the same complaint comes back · if scores stall twice, re-read the
reference frames instead of tweaking.

## The user's verdict (always wins)

Recorded after the panel at each panel checkpoint, and alone at blocking: **accept / accept with changes / reject**;
1–5 for **A**, **B**, **C**, **fidelity** and **Overall**; then the user's words, quoted. Stored on the build notes
and in the vault's calibration note; a verdict on an approved build feeds the write-up and `proposals.md`.

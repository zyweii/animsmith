# Analysis method: mining one reference into a Breakdown

How the `anim-analyst` reads ONE reference, once, and fills Breakdown sections 0–13 (the section list is shared with
the vault template and the analyst agent: same numbers, same names). Frames at 60 fps unless marked. Status: SOURCED
`Video_Pose_Extraction` (NV) and the recreation pipeline's Stage 2, extended; the order and tags are binding process.

## Reading order (each image once; write everything down on that turn)

1. `analysis/numbers_brief.json` (cheap, measured: every field below except the per-frame series) → draft the
   timing table before looking at any image. Never read the full `numbers.json`: when one per-frame series is
   needed (the energy around one peak, say), print just that slice with a one-line `python -c`.
2. `sheets/<ID>_motion.png` (energy + camera + region plot) → confirm phases.
3. `sheets/<ID>_keyposes.jpg` (labelled frame numbers) → key-pose table.
4. `sheets/<ID>_strips.jpg` (every frame ±3 around the biggest peaks) → contact frame, smears, hitstop, overlap.
5. `sheets/<ID>_onion.jpg` (the key poses ghosted over the background, ≥ 640 px wide) → arcs, spacing, line of
   action. `sheets/<ID>_contact.jpg` → context, cuts.
6. At most **two** full frames, only where a sheet can't settle a pose (the hero contact pose first).
7. At most **three** theory-note sections (the Breakdown template names up to three: `Spacing_And_Easing` and
   `Overlap_Offset_And_Arcs` in §5, one more in §6), each confirmed to exist before it is cited.

## Frame numbers (read before writing any frame)

- **Brief and numbers frames are 1-based** `f_####` numbers (`f_0001` = frame 1 = t 0) at `fps_analysis`; the brief
  says so as `frame_base: 1` and in `frame_note`.
- **Trimmed clips count from the trim:** `f_0001` is the first frame of the trim, and `trim_offset_frames` source
  frames (at `fps_analysis`) come before it; `timing_60.trim_offset_frames_60` is the same at 60 fps. **"Source
  frames" in the Breakdown (§3, §13) are the `f_####` numbers as they are**, plus one line under the §3 table when
  trimmed: `trim offset: +N source frames (start S s)` (N = `trim_offset_frames`, S = `trim[0]`). Frame f in the
  whole source is f + N.
- **Decoded `.rbxm` specs are 0-based: spec f = brief f − 1** (the data brief carries `spec_frame_offset: -1`).
  Look keys up in the spec with the shifted number.
- **§9 beat-sheet markers are written in spec frames (0-based, at 60 fps)**: for a video that is the `timing_60`
  frame − 1, for data the brief frame − 1 (at `fps_spec`). The beat sheet says so in one line (`markers in spec
  frames, 0-based @60`).

## Keypose types and the motion chart

`keypose_detail[].type` and the motion chart's bands are **candidates found from the energy curve alone; verify every
one by eye on the strips** before naming a phase after it.

| Label | What the analyser saw | What it can also be |
|---|---|---|
| `contact` (keypose type) | The peak frame right before a hit-stop candidate: a fast frame, then the pose freezes | A snap-back into a hold (a bolt pulled back, a guard snapped up), the end of a fast move into a rear or anticipation hold; contact needs a target and the frames after it reading as impact |
| `hold` / `end` | Near-zero motion inside / at the end of the clip | A moving hold under the noise floor (2–5 % drift) |
| `slow` | Smoothed energy low outside holds | A wind-up, a settle, or a far-away subject |
| `extreme` / `fast` | A reversal valley / a high-energy frame | A breakdown pose; a camera artefact the compensation missed |
| Motion chart **purple band "hit-stop"** | A peak, then ≥ 2 f of near-zero raw motion within a few frames (≤ 0.4 s) | Any rear hold after a fast move (the pose at the end of a pull-back, a stepped drawing): a hitstop only if it follows contact and both actors freeze |
| Motion chart blue band "hold", red marks "peak" | `holds`, `peaks` | See the field table below |

## Tags on every line

| Tag | Means |
|---|---|
| `OBSERVED` | Read directly from `numbers_brief.json` (or a one-slice read of `numbers.json`) or seen unambiguously in a frame |
| `INFERRED` | Reasoned: depth, twist, hidden limbs, intent, anything off-screen |
| `confidence h/m/l` | Per key pose and per channel group (torso, arms, legs, head, prop) |
| `how judged` | `number` (field name) or `eye` (sheet + frame) |

Provenance (`own` / `licensed` / `third-party`) and scale (`match` for own work, else `absolute`) come from the card;
repeat them in §1. Third-party keys are study-only.

## numbers.json: what each field gives you (all in `numbers_brief.json` except the per-frame series)

| Field | Measured meaning | Use it for | Trap |
|---|---|---|---|
| `fps_src`, `fps_analysis`, `frames`, `duration_s` | Source and analysis rate, length | §2; the 60 fps conversion | A 30 fps clip is **±2 f at 60**; a 60 fps clip ±1 f |
| `capture` | True fps, duplicate and dropped frames, stepping (ones/twos/threes) | §2: is "30 fps" really 30? Is the animation on twos? | Stepping counts only **periodic** duplicates (≥ 3 runs of 1 duplicate one drawing apart = twos, of 2 = threes); isolated duplicate runs are holds, and on ones `true_fps` = `fps_analysis`. Duplicates every other frame of a 60 fps file = a 30 fps capture or twos: read `stepping` before calling holds |
| `frame_base`, `trim`, `trim_offset_frames`, `spec_frame_offset` | Frame numbering | Every frame you write | See "Frame numbers" above: 1-based, from the trim start; spec f = brief f − 1 |
| `crop`, `subject_box` | Analysed region, subject bounds | Whether UI or a second actor polluted energy | The box includes a weapon tip only if it stayed in frame |
| `camera` {dx, dy per frame, `moving`, `shake_candidates`} | Global shift by phase correlation | §2 moving camera; §7 shake; camera category | A subject filling the frame can read as camera motion: check the background on the contact sheet |
| `energy` | Subject motion per frame, camera removed, 0..1 | The spacing chart: plateaus near 0 = holds, spikes = strikes/smears, valleys = extremes/reversals | Normalised: compare shapes, not heights, across clips |
| `regions` (3×3 grid; series per cell, which peaks first) | Which part of the subject box moves first | §5 lead/lag: e.g. the centre cell (torso) peaks 2 f before the upper-right (arm) = torso leads by 2 f | Cells are screen areas, not body parts: map them by the key pose, and say so |
| `holds` [[a,b]] | Near-zero subject motion runs | §3 anticipation hold, contact hold, end hold | A "hold" may still be a moving hold (2–5% drift) under the noise floor |
| `peaks` | Energy maxima | §3 strike/contact candidates; §5 speed peaks | Peak ≠ contact: contact is the first frame the limb reaches the target zone, often 1 f after the peak |
| `extremes` | Reversal / extreme-pose candidates | §4 key poses | |
| `smears` | Frames above a smear-speed threshold | §3 strike/smear; §7 VFX fill | Source motion blur can hide or fake them: confirm on strips |
| `hitstop_candidates` [[peak, from, to]] | A peak followed by ≥2 f of near-zero subject motion | §3 hitstop; §8 combat row | Also fits a deliberate pose hold or stepping: call it hitstop only if it follows contact and both actors freeze |
| `cycle` {period_frames, confidence} | Autocorrelation period | §3 loop seam; §8 loco cycle metrics | null for one-shots; confidence under ~0.5 → "weak" in §0 |
| `keypose_candidates` | Frames to inspect for key poses | §4 | Candidates, not answers |
| `audio` (onsets; peak ↔ onset offsets) | Sound events and their offset from motion peaks | §2 audio sync; §7 sound dependence (whoosh 3 f before the smear, impact on contact) | No or silent audio: "not in clip" |
| `timing_60` | The frame lists converted to 60 fps (1-based, from the trim start like f_####) | Every 60 fps number you write | Use these; don't reconvert by hand |
| `notes` | What the analyser couldn't measure | Copy into §0 | |

**60 fps conversion** (what `timing_60` does): `f60 = round((f − 1) × 60 / fps_analysis) + 1`, both 1-based and
counted from the trim start; in the whole source, `f60 + timing_60.trim_offset_frames_60` (and `f + trim_offset_frames`
at `fps_analysis`). ms from the clip start = `(f60 − 1) × 16.7`; durations = frame count × 16.7. Give both source
frames and 60 fps frames in the timing table. State the precision once in §0 (±1 or ±2 f).

## Pose reading order (per key pose)

1. **Camera:** yaw and pitch of the view (floor plane, the character's facing, background). A wrong camera guess
   corrupts every limb angle after it.
2. **Torso:** root height, lean, twist (face and chest front). Check the **head** before trusting a lean.
3. **Limbs:** each limb's direction in the torso's frame → REL angles by the sign table. Blocky limbs make direction in
   the image plane easy; depth is the uncertain part (INFERRED, confidence m/l).
4. **Detachment:** limb gaps in studs (a limb is ~1 stud wide) on fast frames; 0 on holds and contacts.
5. **Confidence:** per channel group; flag depth-ambiguous limbs explicitly.

**Sign table** (REL, CFrame.Angles order): hanging limb `+rx` forward/up · torso/head `-rx` lean/nod forward ·
`+ry` turn to the character's left · right arm `+rz` / left arm `-rz` raise sideways · right leg `+rz` / left leg
`-rz` kick out · R15 lower arm `+rx` elbow bend, lower leg `-rx` knee bend. **Unverified in Studio until Stage 0**
(phase 2): every Breakdown says "signs per the unverified table" in §0 until then.

Rig: R6 = 6 rigid parts, no elbows or knees, one-piece torso; R15 = bending elbows and knees, split torso. Unsure → say so.

## The Breakdown sections (0–13) and how to fill each

| § | Section | Fill from | Must contain |
|---|---|---|---|
| 0 | Trust block | `notes`, `capture`, confidence | Measured (fields used) · read by eye · weak (low confidence, small subject, blur, cuts) · not in the clip · precision ±f · sign-table caveat |
| 1 | What it is | user note, card | One paragraph; the user's note **quoted**; provenance; scale `absolute`/`match`; the one thing the user wants learned |
| 2 | Clip and camera | `fps_*`, `capture`, `camera`, `audio` | fps (claimed vs true), **capture rate and stepping**, rig, camera yaw/pitch estimate, moving camera?, framing, cuts, **audio sync** (offsets) |
| 3 | Timing table | `holds`, `peaks`, `hitstop_candidates`, `cycle`, `timing_60`, strips | Rows: idle, anticipation start→peak, anticipation hold, strike/smear, contact/active, hitstop, overshoot→settle, recovery, control regained / cancel window, loop seam, **transitions** (blend from/into, fade if visible). Columns: source f (the `f_####` numbers), 60 fps f, ms, how judged; when trimmed, one line under the table: `trim offset: +N source frames (start S s)` |
| 4 | Key-pose table | keyposes sheet, strips, ≤2 frames | Per key pose: frame, per-part REL estimate (deg), detachment (studs), line of action, **silhouette from the gameplay camera** (3/4 rear, 30–45° up: does it still read?), confidence h/m/l |
| 5 | Spacing, arcs, overlap | `energy`, `regions`, onion | body mechanics (weight shift, centre-of-mass path, foot contact and slide frames, stepping on ones or twos), speed peaks, which region leads or lags and by how many frames (the region order in `numbers_brief.json`), arcs (clean, broken, linear), breakdown poses (the in-between that shapes each arc, with its frame) and favouring (where the spacing between keys bunches: slow-in at which key, slow-out from which, in frames), the easing per phase in the words of [[Spacing_And_Easing]] and [[Overlap_Offset_And_Arcs]] |
| 6 | Principles observed | `principles.md` vocabulary | Each line cites a theory note by `[[name]]`; good and bad both |
| 7 | VFX, camera, sound dependence | `smears`, `camera.shake_candidates`, `audio` | What the motion leans on: smears filled by VFX, shake, hitstop, sound sync (offsets in frames) |
| 8 | Category specifics | the category file's "what to look for" | combat: frame-data row (startup/active/recovery), cancel windows, hitstop, input to first visible motion (frames), whether the telegraph reads in PvP, and two-actor timing (attacker vs victim) · weapon: tip arc, lead order, grip changes, recoil/reload beats · ability: the beats · reaction: impact frame and direction, two-actor timing (attacker vs victim), displacement, hold, recovery/get-up · loco: cycle metrics · world: mechanism, easing, loop · camera: framing, FOV, cuts, shake |
| 9 | How to replicate | everything above | Beat sheet (phases with frame budgets, key poses in words, markers in the canonical schema **in spec frames, 0-based @60, said so in one line**) + AnimSpec levers (overlap, overshoot, exaggerate, retime, ease, life) with values + delivery notes (easing per key: `Linear`, `Constant`, `CubicV2`, `Elastic`, `Bounce` · `In`/`Out`/`InOut`; never legacy `Cubic`) |
| 10 | What to do better | the move's budget row in `timing.md`; the polish rubric, lint thresholds and house rules in `principles.md` | A checklist; every line states its delta vs the norm: "antic 9 f vs light budget 2–4 f → snap it to 3 f", "arms twinned in recovery vs rule 5 (2–4 f offsets down the chain)", "a hand still 9 f vs rule 13 (no part still ≥ 6 f)" |
| 11 | Transferable lessons | — | `<pattern> — when/context — evidence <ID> (frames) — proposed rule` lines (each is n=1, an observation; the context lets later contradictions be resolved by situation) |
| 12 | User corrections | main thread only | Quoted, dated `USER (<date>)`, binding; the analyst never writes here |
| 13 | Media | sheets | Sheet embeds and the best frame ranges (source and 60 fps) |

## Measurable vs eye-read

| Measurable (numbers.json) | Eye-read (sheets, frames) | Rarely knowable (INFERRED or "not in clip") |
|---|---|---|
| Phase timing, holds, peaks, smears, hitstop candidates, cycle period, camera shift and shake, region lead/lag, audio offsets, capture rate and stepping | Key poses, contact frame, line of action, silhouette, arcs, detachment, grip changes, easing shape (from spacing) | Depth and twist, hidden limbs, exact angles (±10–20°), active frames on the server vs visual contact, input-to-first-frame latency, fade lengths |

## Common analysis mistakes

| Mistake | Fix |
|---|---|
| Calling the energy peak the contact frame | Contact = first frame in the target zone; check strips ±3 |
| Calling a stepped (twos) animation "full of holds" | Read `capture.stepping` first |
| Trusting a lean the head contradicts | Read the head and the floor line first |
| Reading camera shake as body motion | Compare with `camera`; the background moves too |
| Mixing source and 60 fps frames in one column | Two columns, always |
| Precise angles on a depth-ambiguous limb | Give a range and confidence l |
| Writing third-party keys up as a deliverable | Study only: §9 describes our own version |

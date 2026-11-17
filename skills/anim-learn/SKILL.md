---
name: anim-learn
description: animsmith training step, run only by "/anim learn". Files animation references (videos, GIFs, pose images, .rbxm/.rbxmx animations) into the animsmith vault library, has one analyst per reference write a deep Breakdown, gets the user's accept or correction on each, and writes the lessons into the animation pattern library. Not for general Roblox asset imports, VFX, UI or environment references, or any other plugin's learn command.
---

# anim-learn (training)

The user trains animsmith here. Each reference becomes an `ANIM-<CAT>-####` card, a media folder (frames, sheets,
measured `numbers.json` and its short `numbers_brief.json`) and a deep Breakdown (sections 0–13); the user accepts or
corrects every Breakdown; the accepted lessons go into the pattern library. Nothing learned survives a chat unless it
is written to VAULT, so the quality of what ends up in those files *is* the training. Plan §6 and §7.1
(`Anim_Plugin_Plan` in VAULT).

The main thread runs this skill. **Nothing here writes to Roblox Studio, uploads anything, or opens a `.rbxm` in
Studio.** The main thread never opens the images (frames, sheets): the analysts read them once.

## 1. Resolve ROOT and VAULT

Exactly as the router does (`skills/anim/SKILL.md`, first section): ROOT is the plugin root, VAULT comes from
`ANIMSMITH_VAULT` and must hold `11_ASSET_LIBRARY`. If not, stop with the router's message. The inbox is
`VAULT/11_ASSET_LIBRARY/_inbox/anim/` (create it if missing). Use `python` (or `py`/`python3` if that's what exists).
Quote every path; they contain spaces. Today's date as `YYYY-MM-DD` is `<date>` below. `INTAKE` below means
`python "ROOT/kit/scripts/anim_intake.py" --vault "VAULT"`.

## 2. Gather the references into the inbox

**Files attached or named by path in chat:** copy each into the inbox, **keeping its name**. If the user named its
category in words ("these are reload clips"), copy it into `_inbox/anim/<cat>/` instead (for files already in the
inbox, see "A category named in chat" below). If the name is taken, add `-b`, `-c` … before the extension (never `_2`: a `_NN` ending marks a pose-sheet still). Copy, never move, files from
outside the vault. Several stills of one move (`guard_01.png`, `guard_02.png` …) stay together with the same stem:
they become one pose-sheet reference.

**The user's words about a file** (what it is, where it's from, what they like or dislike in it, what to focus on)
go verbatim into a sidecar next to it named after its **full name** plus `.txt` (`slash.mp4` → `slash.mp4.txt`).
One sidecar per file; none if they said nothing about it. The intake script reads it: a first word that is a
category name sets the category; "mine", "my own" or "match" sets `scale: match`; the source the words name sets
`provenance` (own | licensed | third-party; default third-party). Never add words the user didn't say; a category
you inferred goes in the subfolder, not the sidecar.

**Timestamps** ("only 0:02 to 0:05", "the second swing"): turn the times the user gave into one sidecar line
`trim: <start>-<end>` in seconds (`trim: 2.0-5.0`). Frames and analysis then cover only that range; the source is
kept whole. Ask for the times if they only described the moment. One range per file: two moves in one clip are two
references (copy the file again with a `-b` name and its own `trim:` line).

**Videos may not reach you as files.** Claude Code takes images, not video: a clip "sent in chat" often arrives as
nothing, or as a single frame. If the user mentions a video and there is no file path for it, don't guess and don't
work from a still: ask them to drop it into `11_ASSET_LIBRARY/_inbox/anim/` (optionally a category subfolder, with a
one-line `.txt` note next to it) and say "/anim learn, it's in the inbox".

**Images pasted into chat** arrive as pixels with no file behind them, so there is nothing to copy or file. Ask the
same way: the file's path, or a drop into the inbox (stills of one move named `<move>_01.png`, `<move>_02.png` …).
Never save or describe a pasted image as a reference yourself.

**"It's in the vault / the inbox":** nothing to copy; go to §3. If the inbox is empty (no files, no category
subfolders with files), don't show the §2 block as if they had said nothing: ask where the files are (a path, or a
drop into the inbox), and still run the pending sweep (§9).

**A category named in chat for files already in the inbox** ("the clips in the inbox are combat", "slash.mp4 is a
weapon clip"): the intake can't hear chat, so write it down. Append the user's words verbatim as a new last line of
each file's sidecar (create the sidecar if there is none; keep every existing line as it is). Then file them by
category in §3/§4 with `INTAKE --files "<inbox path>" … --category <cat> --json`, one run per category (dry run
first, with the same flags), not with a bare run; the inbox's other files then go in a run of their own
(`--files` naming them). Files the words don't clearly cover go through the normal "no category" question (§4).

**Inbox empty and nothing attached:** show this block, then still run the pending sweep (§9):

> **How to give good references** (quality beats volume: 5–10 good clips per category beat 50 random ones)
> - **One move per clip**, trimmed to **1–4 s**. Can't trim? Give timestamps: a line `trim: 2.0-5.0` (seconds) in
>   the clip's `.txt` note limits the analysis to that range.
> - **60 fps or slow motion**; a 30 fps clip is only good to ±2 frames at 60.
> - **A locked camera from the side or three-quarter**, the **whole body** in frame.
> - **Little UI or VFX** over the body (effects hide the poses).
> - **One line on why** in `clip.mp4.txt` next to it ("I like how the bolt slams", "anticipation too long",
>   "my own recording"). Your line decides what the Breakdown focuses on, and says whose it is.
> - **Data beats video:** your own animations as `.rbxm`/`.rbxmx` teach exact angles and timings; one data file is
>   worth five videos. (FBX/BVH are filed as skipped until phase 4.)
> - Drop them in `11_ASSET_LIBRARY/_inbox/anim/` (or `_inbox/anim/<category>/`), then run `/anim learn`.
> Categories: combat, weapon, ability, reaction (hit-reacts, knockdowns, get-ups), loco, world, camera.

## 3. Dry run, then check provenance and scale

```bash
INTAKE --dry-run --json
```
Add `--rig r6|r15` or `--crop x,y,w,h` only when the user said so. Show the plan in a few lines: how many references
by kind, the category, scale, provenance and trim each will get, what will be skipped and why (FBX/BVH/GLB: phase 4;
"no category": you'll ask), and **every line of `warnings`** (a hub missing its marker, say: that file would fail).
Nothing to file and nothing pending → show the §2 block and stop.

**`gpu_ok` false** in the dry run: show its `gpu_reason` and warn the user before the real run that the GPU decode
path isn't available (the real run would stop with exit 4, §4). Don't add `--gpu off` on your own; ask (the same two
choices as exit 4) and pass `--gpu off` only on "Run on the CPU this time".

**Provenance and scale are guessed from a few words, so check them.** For each result, compare its `scale` and
`provenance` with what the user actually said (the sidecar and the chat): "my own recording" but `third-party`,
"from Mixamo" but `third-party`, a clip of another game but `match`, or nothing said at all about where it is from.
A result with **`provenance_guess: ambiguous`** means the note was unclear: always ask that file's provenance.
On a mismatch, silence or `ambiguous`, ask (AskUserQuestion, one question per file, up to 4 per call; provenance
options "own (my recording or my animation)", "licensed (Mixamo, a bought pack …)", "third-party (another game,
a video found online)", the likeliest first). Provenance decides whether keys may ever ship, so never leave a doubt
unasked. Then:
- **Before filing:** pass the user's answer as `--provenance own|licensed|third-party` and/or
  `--scale absolute|match`. These apply to every file in the run, so files that need different values get separate
  runs, each `INTAKE --files "<inbox path>" … --provenance … --json`.
- **Already filed** (or noticed later): `INTAKE --set-meta <ID> --provenance … --scale … --json` corrects the card's
  frontmatter. Quote the user in that Breakdown's §12 (`USER (<date>): "…"`, what changed).

## 4. Real run

```bash
INTAKE --json
```
(plus the overrides from §3, if any; files that needed different overrides run separately, each with its own
`--files … --provenance … --scale …`). It moves each filed inbox original into `_media/anim/<ID>/source/` (its
sidecar is copied there too and deleted from the inbox), writes frames, sheets, `analysis/numbers.json` and
`numbers_brief.json`, the card, the Breakdown skeleton, the hub line and the index row, then runs `build_mocs` and
`validate`. JSON: `results[]` (`id, kind, category, card, breakdown, media_dir, numbers, numbers_brief, sheets[],
frames[], spec, user_note, scale, provenance, provenance_guess, inbox_kept, reason`), `tools.build_mocs`,
`tools.validate`, `gpu`, `warnings`. Show any `warnings`.

Exit codes:
- **0** ok.
- **1** at least one file failed and was rolled back; the others were filed. Show each failed file's `reason`, then
  carry on with the filed ones. Never hand-make a failed file's card, ID or media.
- **2** bad vault or missing templates: show the message (`error`) and stop.
- **3** (or `tools.validate.ok` false) validate problems: show its `tail` and carry on; fix only what this run made.
- **4** the GPU path failed (`gpu_failed` with its reason; files after it say "not run: GPU failed earlier in this
  run" and stay in the inbox). **Never rerun on the CPU silently.** Ask with AskUserQuestion, showing the reason:
  "Run on the CPU this time (`--gpu off`)" or "Stop; I'll check the GPU". On the first answer rerun the same command
  with `--gpu off`. On "Stop", still go on to §5 for every result that already has an `id` (filed before the
  failure), and say which files wait in the inbox.

Results without an `id`, by `reason`:
- **"no category":** ask the user per file (AskUserQuestion, one question per file, up to 4 per call). List
  all seven categories in the question text (combat, weapon, ability, reaction, loco, world, camera); offer the
  three likeliest from the file name and note as options (the tool adds "Other" for the rest). Then rerun per
  category: `INTAKE --files "<inbox path>" ... --category <cat> --json`, carrying each file's `--provenance` /
  `--scale` answers from §3 (files with different answers go in separate runs), and handle its exit codes as above.
- **"phase 4"** (FBX/BVH/GLB): tell the user they stay in the inbox until the data route lands.
- **"nvdec_unsupported_format"**: the GPU can't decode that one clip's format (4:4:4 chroma or 10-bit, say); the
  GPU itself works, so this is not exit 4. Ask per file (AskUserQuestion): "Decode just this file on the CPU" or
  "Leave it in the inbox (I'll re-export it as 8-bit 4:2:0)". Only on the first answer:
  `INTAKE --files "<inbox path>" --gpu off --json` (with the same `--category`/`--provenance`/`--scale`), exit
  codes as above.
- **Any other `reason`** ("not found", "unsupported type …", "note without a reference file", "no KeyframeSequence
  in the file", "anim_catalog missing", an error text, or one not listed here): show it verbatim with the file name,
  and say the file stays where it is. Never drop a result silently.

A `.rbxm`/`.rbxmx` result may carry a script scan: report any `suspicious` entries to the user (the file was decoded
offline; its scripts never ran and were never copied). A flagged file is stored as `source/<name>.quarantine` and its
card says so: tell the user it was quarantined, and never open, rename or insert it in Studio. A non-empty `inbox_kept` means the file was filed but its inbox
copy couldn't be removed: tell the user.

## 5. One anim-analyst per filed reference, in parallel

Spawn one `anim-analyst` agent per filed reference (every result with an `id`), **all in ONE message**, at most 6
per message (more → batches of 6, the next batch after the previous replies). Each prompt is built from that
reference's result block (from this run, or from `INTAKE --pack <ID> --json` for the sweep and after a refile):
```
ROOT=<root>
VAULT=<vault>
ID=<id>  kind=<kind>  category=<category>
card=<card>
breakdown=<breakdown>
numbers_brief=<numbers_brief>
numbers=<numbers>
spec=<spec, or none>
sheets=
<one path per line>
frames=
<one path per line>
scale=<scale>  provenance=<provenance>
User's note (verbatim): <user_note, or "none">
```
Take `user_note`, `scale` and `provenance` from the result block (the intake copied them from the sidecar and any
override; never paraphrase from the chat). Pass only the `frames` the block lists (at most 6), never the frames
folder. For a `.rbxm`/`.rbxmx` reference (kind roblox), `sheets` and `frames` are empty and `spec` is set: the
analyst reads the decoded keys instead of images.

**A failed analyst** (an error, no reply, a reply starting `MISSING`, or the card or Breakdown still holding
`TODO(analyst)` or `{{` afterwards: grep both files) is retried **once** with the same prompt. If it fails again,
report it with the card path and leave its `breakdown_status` as it is; the next run's sweep picks it up.
If the Agent tool isn't available, follow `ROOT/agents/anim-analyst.md` yourself, one reference at a time.

## 6. Summary per reference (8 lines or fewer each; 9 with a title proposal)

From each analyst's reply (open the Breakdown only to fill a gap, by grepping a section; never the images):
1. `<ID>` · what it is · category · provenance and scale.
2. Timing: the key phases in frames at 60 fps, and the precision the true capture rate allows.
3. Key poses: how many, and their confidence.
4. Lead and lag: which parts lead or drag, by how many frames.
5. Principles: the three strongest, with the theory notes they cite.
6. Replicate: one line (with the delivery facts: priority, root motion or in place). Better: one line.
7. INFERRED: the main guesses (depth, twist, hidden limbs, camera).
8. Card and Breakdown paths.

Pass on any scale or provenance doubt the analyst raised as a question (§3's fixes apply).

**A sentence for a title.** The intake titles a reference from the rest of its note's first line, so a title can be
the user's opinion ("from a youtube showcase, I like how fast the bolt slams") instead of a name. When the filed
`title` reads as a sentence (an opinion, "I"/"my", a source, more than ~6 words), add a line 9 to that summary:
`Title: "<filed title>" → proposed "<short name>"` (2–5 words naming the move, e.g. "Rifle bolt rack"; plain text: no
`[[`, `]]`, `|`, `#` or line breaks, at most 60 characters). Accepting the Breakdown in §7 accepts the title too,
unless the user changes or declines it. On acceptance, change exactly three things, each with the Edit tool on that
one line (Edit keeps the file's line endings; never rewrite a whole file with Write or a shell redirect):
- the card's H1 `# <ID> — <filed title>` → `# <ID> — <short name>` (and a frontmatter `title:` line, if the card has
  one; the template has none);
- the category hub's line starting `- [[<ID>]] — ` (between the `ANIM-CARDS` markers): replace only the title
  between `— ` and the first ` · `;
- the `Asset_Library_Index.md` row starting `| [[<ID>]] |`: replace only the third cell (title).
The user's note (`user_note`, and §1's quote) stays verbatim. Do these together with §7's acceptance edits.

## 7. Accept or correct, per reference

Ask with AskUserQuestion, one question per reference, up to 4 per call, **"Accept" first**, then "Correct it"
(the user types the correction through "Other" or in chat). Plain text if the tool isn't available.

- **Corrections are binding.** They override the analyst's reading, measured numbers included. Edit the facts in
  place in the Breakdown (and the card if it states them), marking each corrected fact `USER (<date>)`. Quote the
  user's words verbatim and dated in Breakdown §12 User corrections as `USER (<date>): "…"`, with what changed.
  Then show the changed lines and ask again. Until accepted, the card's `breakdown_status` stays `in-progress`.
- **Provenance or scale corrections:** `INTAKE --set-meta <ID> --provenance … --scale … --json`, then the quote in
  §12. Keys from a `third-party` source stay study-only whatever else changes.
- **A wrong category** is fixed by the intake (the ID prefix, folder, media, specs, hub line and index row follow
  it); never move or rename vault files yourself.
  1. `INTAKE --refile <ID> --category <cat> --dry-run --json` and show `<ID> → <new id>`.
  2. `INTAKE --refile <ID> --category <cat> --json`. Exit **0**: report `refiled_from` → `id`; from now on use the
     new ID and the result's `card` and `breakdown`. Exit **1** (no such card, or the move failed and was rolled
     back): show `reason`; the old ID stands; quote the correction in its §12 and tell the user. Exit **2** (no or
     unknown category, bad vault): show `error` and stop for this ID. Exit **3**: show `tools.validate.tail`; carry
     on.
  3. Quote the user's correction in §12 of the **new** Breakdown: `USER (<date>): "…"` — refiled from `<old ID>`.
  4. If the Breakdown had no analysis yet (it still holds `TODO(analyst)` everywhere), run `INTAKE --pack <new id>
     --json` and §5 with that block. If it was analysed, its §8 speaks for the old category: replace §8's body with
     one line `TODO(analyst): the <new category> line` and run §5 the same way (the analyst fills only the markers
     left). Then summarise and ask again.
- **Acceptance**, on both notes: `status: draft` → `status: active` and `last_updated: <date>`; on the card
  `breakdown_status: done`; on the Breakdown `user_accepted: yes (<date>)` (add the key if the skeleton has none).
  Note the acceptance in §12. Then edit only that ID's two hub entries:
  - the category hub's line starting `- [[<ID>]]` (between `<!-- ANIM-CARDS:BEGIN -->` and `END`): change
    `breakdown not-started` (or `in-progress`) to `breakdown done <date>`;
  - its row in `11_ASSET_LIBRARY/Asset_Library_Index.md` starting `| [[<ID>]] |`: set the Breakdown column to `done`.
  A reference left unaccepted keeps `status: draft` and gets the same two hub edits with `in-progress`, so the hubs
  never say "not-started" for a filled Breakdown.

Only accepted Breakdowns feed §8 and later builds.

## 8. Write-back: what was learned goes into the vault

This covers **every acceptance in this chat**: this run's and the pending sweep's (§9). Run it once after the last
§7 answer; if it already ran before a later acceptance, run it again for the new IDs only. Skip it if nothing was
accepted.
1. **Numbers:** `python "ROOT/kit/scripts/anim_patterns.py" --vault "VAULT"` (regenerates the measured section of
   `Animation_Pattern_Library.md`). Report a failure; don't hand-edit its AUTO block.
2. **Patterns:** first read the actual table under "Observed patterns (hand-maintained)" in
   `11_ASSET_LIBRARY/Animation_Pattern_Library.md` (header and every row; it sits above the AUTO block, never inside
   it) and keep its columns: `| # | Pattern | Evidence (assets, frames) | Rule for Roblox | Strength |`. Each §11
   "Transferable lessons" line of an accepted Breakdown reads
   `<pattern> — when/context — evidence <ID> (frames) — proposed rule`, and its cells are:
   - **#** = `P<n>`; **Pattern** = `<pattern> (context: <when/context>)`; **Evidence** = `[[<ID>]] f<a>–<b>` (more
     IDs joined with `; `); **Rule for Roblox** = the proposed rule; **Strength** = `observation (n=1)`,
     `candidate (n=2)` or `rule (n=k)`, k ≥ 3, counting distinct supporting IDs.
   - It matches an existing row **in the same context** → append `; [[<ID>]] f…` to that row's Evidence and move
     its Strength up the ladder by the new count (n=2 → `candidate (n=2)`, n≥3 → `rule (n=k)`); keep any trailing
     note in that cell (`(fits research …)`).
   - It's new → append a row at the end of the table with `P<max+1>`: the highest P number in the table plus one,
     whatever the row order (the rows are not in number order; never renumber or reorder existing rows).
   - It contradicts a row → keep both, and write the context that separates them (style, weapon, camera, rig) in
     the new row's Pattern cell.
   Never change the Strength of a `research` or `user rule` row (add evidence only); user corrections from §12
   outrank analyst lessons.
   Then, on that ID's **card**, under `## Lessons → where they went`, add one line per lesson:
   `- <pattern, ≤8 words> → [[Animation_Pattern_Library]] P<n> (<new strength>)`, replacing the template's
   placeholder line.
3. **Hub line:** the category hub line for each accepted ID carries its one-line title, kind and `breakdown done
   <date>` (§7).
4. **Theory notes:** only for a genuinely surprising lesson (one that contradicts or sharpens a theory note), add one
   dated line to that note's Gotchas section citing the ID. Most runs add none.
5. Validate, from VAULT: `python "_meta/tools/validate_vault.py" --folder 11_ASSET_LIBRARY`. Show real problems and
   fix the ones this run caused. If the tool is missing, say validation was skipped; never claim it passed.

## 9. Pending Breakdowns sweep (every run)

After this run's analysts (or straight away when the inbox is empty), leaving out this run's IDs, read each card's
`breakdown_status` in `VAULT/11_ASSET_LIBRARY/Animation/*/ANIM-*.md`. The line carries a comment
(`breakdown_status: done   # not-started | in-progress | done`), so take only the value **before `#`**, never
match the whole line:
```bash
grep -HE "^breakdown_status:[[:space:]]*(not-started|in-progress)([[:space:]]|#|$)" "VAULT/11_ASSET_LIBRARY/Animation/"*/ANIM-*.md
```
Pick up what isn't done:
- `not-started`: the analyst never finished (a crash, an error, a session that ended). For each, run
  `INTAKE --pack <ID> --json` and build the §5 prompt from its block (exit 1 or no block: report the ID and its
  `reason`, skip it). Never list the frames folder yourself. Then §6.
- `in-progress`: grep that ID's Breakdown (`VAULT/11_ASSET_LIBRARY/Breakdowns/Breakdown_<ID>.md`, the card's
  "Breakdown note" link) for `TODO(analyst)` and `{{`. **Either one found** means the analyst died part-way:
  treat it as `not-started` (above: `--pack`, §5, §6). None found: the analyst finished but the user hasn't accepted; show the §6 summary from the Breakdown text (grep
  the sections).

Then §7 and §8 for those IDs (§8 covers every acceptance in this chat).

## 10. Final report

In a few lines: what was learned (per reference, its ID and the one lesson that matters most), the new and upgraded
pattern-library lines (with their new strength), refiles (`old → new`), anything skipped or failed (with its
`reason`), files still in the inbox, Breakdowns still pending, and what to give next (the weakest category, or the
clip spec from §2 if quality was the problem).

## Rules

- **Third-party references are style only**, scored absolute. Their media and game names stay in VAULT, never in
  ROOT, `knowledge/` or benchmarks, and they are never uploaded. Keys decoded from a third-party file are study only.
- **Images are read once, by the analyst.** The main thread works from the replies and the Breakdown text; it opens a
  sheet only if the user disputes something visual, and never a full frame.
- **No Studio writes, no Roblox generators, no uploads** in this step.
- Never hand-make IDs, cards or media folders, and never move, rename or delete vault files: `anim_intake.py` owns
  them (`--refile`, `--set-meta`, `--pack`).

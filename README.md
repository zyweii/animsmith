# animsmith

A Claude Code plugin that learns 3D animation for Roblox from reference videos and real animation data, and (from
phase 3) makes Roblox animations: characters (R15 and R6), guns and weapons, abilities, hit reactions, world
elements (doors, platforms, pickups, props, creatures) and camera moves. One command, `/anim`, runs it.

Training works like this: every reference becomes a card with measured numbers (camera motion removed, per-region
energy, holds, peaks, hit-stop and shake candidates, cycles, the true capture rate, audio onsets), contact sheets
and film strips, and a deep **Breakdown**: a timing table at 60 fps, key poses, spacing and overlap, body mechanics,
the principles at work, how to replicate it and what to do better. You accept or correct each Breakdown, and the
lessons build a pattern library (one reference is an observation, two a candidate, three a rule) that later builds
read first.

The plugin holds the code and generic craft. Everything it learns (cards, Breakdowns, media, the pattern library,
specs, game profiles, the build ledger, build notes) lives in your private vault, so plugin updates never wipe it.
It follows the same layout as its sister plugins for VFX, environments and UI: a router, an intake that reads each
reference once, fresh-context agents, a data spec with one runtime and a linter, hybrid review (a blind panel plus
your verdict) and an approval write-up.

## Status: phases 0–1, version 0.1.0

| Command | What it does | Status |
|---|---|---|
| `/anim learn` | Files references (videos, GIFs, pose images, `.rbxm`/`.rbxmx` animations) as cards with numbers, sheets and a deep Breakdown each; you accept or correct each; lessons go into the pattern library | **Built (phase 1)**; FBX/BVH filed as skipped until phase 4 |
| `/anim find <description>` | Searches the library (BM25 with category, style, rig and kind facets) | **Built (phase 1)** |
| `/anim make <what>` | The build loop in a sandbox place: brief, beat sheet, blocking → timing → polish → delivery, hybrid review | Not built yet (phase 3) |
| `/anim study <ID>` | A blocking rebuild of one reference, compared against its clip, to check its Breakdown | Not built yet (phase 3) |
| `/anim review`, `/anim finish` | The blind panel and your verdict; exports, the ledger line and the approval write-up with a one-shot recipe | Not built yet (phase 3) |
| `/anim port <ID>` | An approved build into a game, through that game's profile and rules, on your word | Not built yet (phase 5) |
| `/anim distill`, `/anim bench` | Recipes and calibration from the ledger; blind benchmarks | Not built yet (phase 5) |

Categories: `combat`, `weapon`, `ability`, `reaction` (hit-reacts, knockdowns, get-ups), `loco`, `world`, `camera`.
animsmith's training command is always `/anim learn`; it never answers a bare `/learn` (another plugin may own
that), and asks before running if you seem to mean it.

## Install

From GitHub:

```
/plugin marketplace add zyweii/animsmith
/plugin install animsmith@animsmith
```

In the Claude desktop app: open the plugin marketplace, choose **Add from a repository**, enter `zyweii/animsmith`,
then install `animsmith`. To get updates: `/plugin marketplace update animsmith`.

For development (changes apply on the next start, no version bump needed):

```
claude --plugin-dir <path-to>/animsmith
```

An installed copy is cached by version: after a change, bump `version` in `.claude-plugin/plugin.json`, then run
`/plugin marketplace update`.

**Requirements:** Python 3.10+ with numpy and Pillow, and ffmpeg/ffprobe on PATH. Decoding and encoding use the GPU
(`-hwaccel cuda`, `h264_nvenc`) by default; if that fails, the intake stops and asks you before any CPU rerun
(`--gpu off`).

## Setup

**Point it at your vault.** Set `ANIMSMITH_VAULT` to the vault root (the folder that holds `11_ASSET_LIBRARY`) in
`~/.claude/settings.json`, then restart Claude Code:

```json
{ "env": { "ANIMSMITH_VAULT": "C:\\path\\to\\your\\vault" } }
```

Without it, or if the folder has no `11_ASSET_LIBRARY`, `/anim` stops and says how to set it, and the SessionStart
hook prints a one-line warning. The vault needs the animsmith templates (`_meta/templates/Template_Anim_*.md`) and
the category hub notes; the intake reports what is missing.

From phase 2 on, builds run only in a sandbox Studio place named **ANIM LAB**; animsmith checks the open place before
any Studio write.

## How to train it efficiently

- **Quality over volume.** 5–10 well-chosen clips per category beat 50 random ones; three references that agree turn
  an observation into a rule. Start with the categories you'll make first.
- **Clip spec:** one move per clip, 1–4 s, 60 fps or slow motion, a locked side or three-quarter camera, the whole
  body in frame, as little UI and VFX over the body as possible. Trim before dropping, or give timestamps: a line
  `trim: 2.0-5.0` (start-end in seconds) in the clip's `.txt` note limits the frames and analysis to that range and
  keeps the source whole.
- **Say whose it is.** "My own recording" files it as yours (`provenance: own`, `scale: match`); a licensed pack
  (Mixamo, say) as `licensed`; anything else is `third-party`, study only. animsmith asks when it isn't sure.
- **One line per clip** on why it's there ("I like how the bolt slams", "the anticipation is too long", "my own
  recording") in a text file next to it (`clip.mp4.txt`) or in chat. It decides what the Breakdown focuses on.
- **Data beats video.** Your own Roblox animations as `.rbxm`/`.rbxmx` teach exact angles and timings; one data file
  teaches more than five videos. (FBX/BVH from Mixamo or mocap: phase 4.)
- **Accept or correct every Breakdown.** Your corrections are binding and are the cheapest training there is.
- **Verdicts are the real training** once building lands: accept / accept with changes / reject, 1–5 scores, a
  sentence. Approved builds produce one-shot recipes.
- **Learn and make in separate chats.** A learn chat fills the vault; a make chat starts clean and reads the map.
- **Good and bad pairs** of the same move teach the thresholds fastest.

Drop clips into `11_ASSET_LIBRARY/_inbox/anim/` (or `_inbox/anim/<category>/`) and run `/anim learn`.

## Honest limits

- **Claude can't watch video.** Claude Code takes images, not video files, so a clip sent in chat may not arrive at
  all, and an image pasted into chat has no file behind it to file. The inbox (or a file path) is the reliable route; `/anim learn` turns every video into frames, sheets and measured numbers,
  and Claude reads those.
- **Training doesn't change the model.** Nothing learned survives a chat unless it's written to the vault; the
  quality of the cards, Breakdowns and pattern lines is the training.
- **From one 2D clip, timing is measured well and poses only roughly.** Depth, twist and hidden limbs are guesses
  and are marked INFERRED. Timing at 60 fps is only as precise as the clip's true capture rate.
- **Nothing has run in Studio yet.** The Studio steps (building, playing and capturing animations) are untested
  until phase 2.
- **Other games' moves are style, not stock.** References teach timing, posing and principles; what ships is your
  own animation. Their media stay in your vault and are never uploaded, and keys decoded from a third-party file are
  study material only. A game's own hard rules win: a game whose arms are physically simulated, for example, can't
  take keyframed arm tracks.

## Layout

| Path | What |
|---|---|
| `commands/anim.md` | `/anim <learn\|find\|make\|study\|review\|finish\|port\|distill\|bench> …` |
| `skills/anim/` | The router: ROOT and VAULT resolution, read-first list, route table, non-negotiables |
| `skills/anim-learn/` | The training step |
| `skills/anim-make`, `anim-review`, `anim-finish`, `anim-port`, `anim-distill` | Stubs until their phases land |
| `agents/anim-analyst.md` | One reference, read once → card + deep Breakdown |
| `knowledge/` | Generic craft: index, gotchas, analysis method, principles, timing, categories (see `knowledge/README.md`) |
| `kit/scripts/` | Intake, analysis, catalog, search, the animation tools, the ledger and the session hook; `tests/` (stdlib unittest) |
| `hooks/hooks.json` | SessionStart status; SessionEnd ledger pause |

## Hooks

- **SessionStart** prints the vault path (or a one-line warning), the reference cards per category, Breakdowns not
  yet accepted, files waiting in the inbox, and builds waiting for their approval write-up or paused.
- **SessionEnd** marks any open build `paused` (`ledger.py pause-open`).

Both are Python 3, standard library only, and never fail a session. One command line runs under bash/sh and under
PowerShell: bash runs the first branch and exits before the PowerShell block comment ends; PowerShell skips that
comment and runs the second branch. `python` must be on PATH.

## Tests

```
python -m unittest discover -s kit/scripts/tests -v
```

Tests use temporary fake vaults and synthetic media only.

## Licence

MIT, by zyweii. See `LICENSE`. Two offline Roblox file decoders come from vfxmith (MIT); see `THIRD_PARTY.md`.

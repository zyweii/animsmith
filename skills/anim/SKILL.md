---
name: anim
description: animsmith router for the /anim command (learn, find, make, study, review, finish, port, distill, bench). Use only when the user runs /anim or names animsmith, to learn from animation references or look them up (and, in later phases, make Roblox animations). Not for general Roblox animation questions, another plugin's learn command, or editing a game's animations outside animsmith.
---

# animsmith (router)

## Resolve ROOT and VAULT first

- `ROOT` = the plugin root: two folders above this skill's base directory (`<base directory>/../..`, also
  `${CLAUDE_PLUGIN_ROOT}`). Every plugin path below is relative to ROOT. Resolve it to an absolute path before
  running anything, and quote it (it may contain spaces).
- `VAULT` = the user's private vault root (the folder that holds `11_ASSET_LIBRARY`), from the environment
  variable `ANIMSMITH_VAULT` (bash: `echo "$ANIMSMITH_VAULT"`; PowerShell: `$env:ANIMSMITH_VAULT`). Everything
  animsmith learns lives there: reference cards, Breakdowns, media, the pattern library, specs, game profiles, the
  ledger, build notes.
- **If `ANIMSMITH_VAULT` is unset, the folder doesn't exist, or it has no `11_ASSET_LIBRARY` folder: stop.** A path
  one level off would silently hide the library and pending work. Tell the user to set it to the vault root (the
  folder that holds `11_ASSET_LIBRARY`) in `~/.claude/settings.json` and restart Claude Code:
  ```json
  { "env": { "ANIMSMITH_VAULT": "C:\\path\\to\\your\\vault" } }
  ```
  Never guess the vault path, and never write learning into ROOT instead.
- Every agent prompt passes `ROOT=` and `VAULT=` explicitly (subagents don't inherit them reliably).

## Read first (keep it short: every turn re-reads what you load)

1. `knowledge/README.md`: what's in `knowledge/`, and what each file is for.
2. `knowledge/gotchas.md`: the dated Studio, toolchain and analysis facts the pipeline relies on, each UNTESTED or
   verified.

For anything else, grep `knowledge/` and read only the matching section. The design lives in the plan note
`Anim_Plugin_Plan` in VAULT (find it by name); read one section at a time, never the whole note.

## Route

The first word of the arguments picks the route.
- **No arguments:** print this table (subcommand, what it does, status) and stop.
- **A bare description of an animation** means `make`. While `make` is not built, report its phase and plan section
  straight away, with no confirm question, and stop. (Once it is built, confirm the reading first.)
- **A bare `/learn` is not animsmith's.** It belongs to another plugin, so never run animsmith on it. If the user
  seems to mean animation training, say that animsmith's command is `/anim learn` and ask whether to run it; run it
  only on their yes.

Categories (everywhere a category is asked or set): `combat`, `weapon`, `ability`, `reaction` (hit-reacts,
knockdowns, get-ups), `loco`, `world`, `camera`. IDs are `ANIM-<CAT>-####` (`ANIM-COMBAT-0001`, `ANIM-REACTION-0001` …).

| Subcommand | What it does (when built) | Skill | Status |
|---|---|---|---|
| `learn` | Files references (videos, GIFs, pose images, `.rbxm`/`.rbxmx` animations) attached in chat or dropped in the inbox as `ANIM-<CAT>-####` cards with measured numbers, sheets and a deep Breakdown each; the user accepts or corrects every Breakdown; lessons go into the pattern library | `anim-learn` | **Built (phase 1).** FBX/BVH files are filed as skipped until phase 4. Plan §6, §7.1 |
| `find <description>` | Searches the vault's animation cards and Breakdowns (BM25 with category, style, rig and kind facets) without building | none (`anim_find.py`, below) | **Built (phase 1).** Plan §7.2 |
| `make <what>` | The build loop: brief (delivery target always asked), references, beat sheet, blocking → timing → polish → delivery passes with numbers and captures in ANIM LAB, the hybrid review | `anim-make` | **Not built yet (phase 3).** Plan §5.1–5.4 |
| `study <ID>` | A blocking rebuild of one reference in ANIM LAB plus `anim_compare` against its clip, to check that its Breakdown is right | `anim-make` (study) | **Not built yet (phase 3).** Plan §5.3, §7.1 |
| `review` | Capture, numbers, the blind panel, then the user's verdict, on a build or any animation in ANIM LAB | `anim-review` | **Not built yet (phase 3).** Plan §5.4 |
| `finish` | Exports, the user's hand edits read back, the ledger line, the approval write-up with the one-shot recipe | `anim-finish` | **Not built yet (phase 3).** Plan §5.5, §5.7 |
| `port <ID>` | An approved build into a game through that game's profile and rules, in the game's own chat, on the user's word | `anim-port` | **Not built yet (phase 5).** Plan §5.8 |
| `distill` | Ledger and write-ups into recipes, calibration and pattern-library promotions | `anim-distill` | **Not built yet (phase 5).** Plan §6 |
| `bench` | The frozen benchmark briefs, built by the current plugin, the previous tag and plain Claude; the user picks blind | `anim-distill` (bench) | **Not built yet (phase 5).** Plan §6 |

**`find` (no skill; the main thread runs it):** search, report, never build.
```bash
python "ROOT/kit/scripts/anim_find.py" --vault "VAULT" "<the description in the user's words>" [--cat C] [--style S] [--rig R] [--kind K] [--k 5]
```
Pass a facet only when the user names one (`--cat weapon`, `--rig r15`, `--kind video`, `--style snappy`). Report
the results in a few lines: per hit, id, title, score, category, its `snippet` (the best-matching line, a timing
row when one matched; quote it as given) and the card and sheet paths, and whether its Breakdown is accepted
(`breakdown_status: done`). Don't open sheets or frames unless the user
asks to see one. With no cards or no matches, say so and suggest `/anim learn` or fewer words. Nothing is built, and
nothing is written to Studio or the vault.

**While a subcommand is "not built yet":** say so in one or two lines, name its phase and the plan section, and stop.
Don't improvise a build, a review, a port or a search by other means, and don't write to Studio, the vault or a game.
When a phase lands, its row's status changes here and the stub skill gets its real instructions.

If the skills are not loaded (plain folder use), open `skills/<name>/SKILL.md` and follow it as instructions.

## Non-negotiables

- **ANIM LAB only.** Builds run in the user's sandbox place, ANIM LAB. Before any Studio write, call
  `list_roblox_studios` and confirm the open place is ANIM LAB; otherwise refuse and ask the user to open it. The one
  exception is a port, which runs in a chat opened in the game's own folder, after the user's yes for that build
  (plan §5.8). `learn` and `find` never touch Studio.
- **Third-party references are style only.** They teach timing, posing and principles; what ships is our own
  animation, scored on the absolute ("inspired by") scale. Only the user's own recordings and sketches can be
  "match". Their media stay in VAULT and are **never uploaded** to Roblox or anywhere else. Keys decoded from a
  third-party file (a downloaded `.rbxm`, say: card `provenance: third-party`) are **study only**: never exported,
  delivered or shipped. Only `own` or `licensed` data may become shipped keys. Third-party game names stay in VAULT,
  never in this repo, `knowledge/` or benchmarks.
- **A game profile's hard rules beat everything here** (`Animation/_games/<Game>_Anim_Profile.md` in VAULT). For
  example, a game whose arms are physically simulated can't take keyframed arm tracks: only the targets its profile
  allows (legs and torso data, gun-part curves, camera curves, world motion), and arm reference curves only where
  the user has made an exception for that move.
- **Hybrid review, 2 panel rounds per build.** The user checks blocking alone; panel round 1 after polish, round 2
  at delivery, each followed by the user. Three blind reviewers per round, one lens each. The user's verdict wins and
  is recorded structured (accept / accept with changes / reject; 1–5 per lens, fidelity, Overall; their words).
- **Every approved build gets its write-up** with the one-shot recipe (plan §5.7). A build waits at
  `final-pending-writeup` until it is done, across chats if needed.
- **Learning goes to VAULT; only generic craft goes to ROOT.** Plugin changes are made in the source repo, never in
  the installed plugin cache.
- **GPU first** for every decode, encode, render and ML step. If the GPU path fails, ask the user before any CPU
  rerun; never fall back silently.

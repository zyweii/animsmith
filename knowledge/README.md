# knowledge/ (index)

Seed knowledge that ships with the plugin: generic animation craft only (techniques, numbers, checks, process).
Reference media, Breakdowns, specs, game profiles, style profiles, the pattern library, the ledger and anything
learned per build live in the user's vault (`ANIMSMITH_VAULT`), never here, because this repo is public. No game
names, no vault paths, no place ids in these files.

All frame counts are **at 60 fps** unless a line says `@30`. `f` = frames. Convert: `f60 = f_src × 60 / fps_src`.

## The ladder (every rule carries one status)

| Status | Means | How a rule gets there |
|---|---|---|
| `UNTESTED` | Claude's reasoned starting guess, no source | Written at seed time; say "reasoned" |
| `SOURCED` (`Note_Name`) | From the user's theory notes (cited by note name in backticks) | Seed distillation |
| `MEASURED n=…` | Measured from n references (median or range) | `/anim learn` + the pattern script |
| `RULE` | 3+ agreeing references, or a user verdict | Distill or the user's word |
| `HOUSE` | The user's binding house rule; beats every other status | The user only |

A rule moves up only with evidence. A contradiction is resolved in place ("Use X; Y is stale because …"), never
appended. Facts in `gotchas.md` carry a fact tag instead: `verified <date>` or `UNTESTED (phase/Stage 0)`.

## Files

| File | What it's for | Read when |
|---|---|---|
| `README.md` | This index | Always (router read-first 1) |
| `gotchas.md` | Dated engine and toolchain facts | Always (router read-first 2) |
| `principles.md` | The 12 principles + the polish rubric as checkable rules with thresholds | Reviewing, linting, writing "Principles observed" |
| `timing.md` | Frame budgets per category, easing per phase, hitstop, fades, springs (corrected settle times) | Writing a beat sheet; checking timing |
| `analysis-method.md` | How to mine one reference into Breakdown sections 0–13; reading `numbers.json` | Every `/anim learn` analyst run |
| `spec-format.md` | AnimSpec v1 (as built) + v2 (PLANNED): actors, root curve, markers, delivery targets | Writing or reading a spec |
| `lenses.md` | Reviewer lenses A/B/C, fidelity, Overall, score anchors, absolute vs match | Spawning a panel; recording a verdict |
| `proposals.md` | Behaviour changes waiting for a second approved build (n=2) | Building (hints); writing up an approved build |
| `categories/combat.md` | Unarmed attacks, combos, frame data | combat references and builds |
| `categories/weapon.md` | Guns (equip → reload) and melee weapons | weapon references and builds |
| `categories/ability.md` | Specials, ultimates, dashes, casts, counters | ability references and builds |
| `categories/reaction.md` | Hit-reacts, stagger, knockdown, get-up, KO | reaction references and builds |
| `categories/loco.md` | Idle, walk/run/sprint, jump/land, dash, turns | loco references and builds |
| `categories/world.md` | Doors, lifts, platforms, pickups, breakables, creatures | world references and builds (mostly UNTESTED) |
| `categories/camera.md` | Push-in, dolly, FOV kick, cuts, shake | camera references and builds (mostly UNTESTED) |

Each category file has the same sections: anatomy/phases, starting numbers, easing, markers (canonical + aliases),
common mistakes, what to look for in a reference, and **GAPS** (what training must fill). Each file is one read.

## The user's house rules (binding everywhere; status `HOUSE`)

1. **Every part keeps moving.** No part slower than 1.5°/s in the world AND against its parent for ≥100 ms (6 f).
   Holds are moving holds (2–5% drift). Exception: none so far; `stepped` only waives the whole-body dead-hold check. Two stillness carve-outs are proposed but **pending the user's ruling**, so do not assume them: machines at rest (`categories/world.md`) and the KO final pose (`categories/reaction.md`).
2. **R15 limbs stay straight, R6-like.** Bends only where R6 cheated (crouch, landing compress, knee plant).
   No default elbow bend on retarget.
3. **Delivery rig is R15.** R6 references are recreated in R6 first (faithful), then retargeted.
4. **Mine each reference once, fully.** One move per asset. Never overwrite a spec version; one hypothesis per
   version; about 6 versions per session at most.
5. **Preview on the browser bench before Studio.** Hybrid review: panel (2 rounds max), then the user's verdict wins.
6. **References are for the look only.** Third-party keys are study-only; nothing from another game ships.
7. **Prefer 60 fps originals and side or three-quarter views** over resolution.
8. **Dashes: no foot plant before the dash's end marker.**
9. **Mocap retimed for the game's gravity:** time scale `s = √(k·9.81/g′)` (g′ = the game's gravity in its units,
   k = studs per metre of the rig). Physical arms (where a game has them) follow arm curves loosely, never as joint writes.
10. **GPU first** for every decode, encode, render and ML step; never fall back to the CPU silently.

## Provenance (every reference and spec)

| Provenance | May ship as keys? | Review scale |
|---|---|---|
| `own` (the user's recording, sketch or animation) | yes | `match` allowed |
| `licensed` (licence allows games: e.g. a stock mocap library's game licence) | yes, within the licence | `absolute` |
| `third-party` (another game's clip or file) | **no**: study only; a faithful copy may exist in the lab to learn how it works | `absolute` |

## How this folder changes

Only three things edit these files: **approval write-ups** (generic lessons from approved builds, through
`proposals.md` at n=1 → applied at n=2), **`/anim distill`** (medians and rules from the vault's pattern library,
generic parts only) and **benchmarks** (`/anim bench` blind picks). Learned data stays in the vault; only the
generic lesson comes here, with its ladder status raised. `spec-format.md` changes with the runtime, in the same step.

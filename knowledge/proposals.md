# Proposals (waiting for a second approved build)

Behaviour changes that came from **one** approved build's write-up. One approval is evidence, not a rule, so a change
that would alter how the plugin behaves (lint thresholds, `lenses.md` and the reviewer prompts, agent and skill
prompts, the spec schema, delivery exporters, a number in `timing.md` or a category file) is written here first, at
`n=1`.

- The builder reads this file as **hints, never enforced**.
- A proposal is **applied** once it holds in **2 approved builds** (`n=2`), or sooner if the user says so. Applying
  it means making the change in its real home, raising that rule's ladder status, and marking the entry `applied`
  with the plugin version; the entry stays here as the record.
- A proposal that a later approved build contradicts is marked `contradicted` with that build's id, not deleted.
- A change to lenses A–C is mirrored into the vault's calibration note in the same step.
- Measured timing from references (not builds) goes to the vault's pattern library (observation n=1 → candidate n=2
  → rule n≥3); only the generic rule comes here, through `/anim distill`.
- No reference media, game names or per-game values here; they live in the vault.

Entry format:

```
### P-### <one-line change>
- Target: <repo path the change would edit>
- Evidence: <ANIM-BUILD id> (n=1): <what in the build notes or the user's words supports it>
- Scope: <category x style, or generic>
- Status: proposed | applied (vX.Y.Z, n=2: <build ids>) | contradicted (<build id>)
```

## Open proposals

None yet.

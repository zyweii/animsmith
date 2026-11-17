---
name: anim-finish
description: animsmith finish step, run only by "/anim finish". Closes an animsmith build (exports, the user's hand edits, the ledger line and the approval write-up with its one-shot recipe). Not for general notes or other ledgers.
---

# anim-finish (finish and write-up)

Closes a build: runs the exporters for its delivery targets, reads the user's hand edits from the Animation Editor back into the spec, writes the ledger line and, when the user approved it, the approval write-up `Animation/_builds/ANIM-BUILD-####_Build_Notes.md` with the one-shot recipe (the shortest path from the prompt to the approved result).

**Not built yet (phase 3; plan §5.5 and §5.7, in the `Anim_Plugin_Plan` note in the vault).** Report that and stop; don't export, write up or write anything in Studio, the vault or a game by other means.

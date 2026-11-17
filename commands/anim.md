---
description: "animsmith's /anim command: learn Roblox animation from references (videos, GIFs, pose images, .rbxm animations), look them up, and later make, review, finish and port animations with the animsmith pipeline. Use only when the user types /anim or names animsmith."
argument-hint: <learn | find <description> | make <what to animate> | study <ID> | review | finish | port <ID> | distill | bench>
---

Read `${CLAUDE_PLUGIN_ROOT}/skills/anim/SKILL.md` and follow it (it is also the `anim` skill of the animsmith
plugin). Arguments: $ARGUMENTS

- **No arguments:** print the skill's route table, each subcommand with its status, and stop.
- **First word is a subcommand** (`learn`, `find`, `make`, `study`, `review`, `finish`, `port`, `distill`, `bench`):
  follow that row of the route table and its status exactly.
- **Anything else** is a description of an animation, so it means `make`. While `make` is not built, report its
  phase and plan section straight away, with no confirm question, and stop.

A subcommand marked "not built yet" is reported as such, with its phase and the plan section; nothing is built,
searched or improvised by other means.

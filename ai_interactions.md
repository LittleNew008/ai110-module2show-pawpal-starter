# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agent Workflow (SF7)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

Design the main objects for the PawPal+ pet care app described in the README (what each holds and what actions it performs), then turn the design into a UML diagram and Python class stubs. Follow-up decisions: plans use clock times, and a required task that does not fit is flagged. Also asked it to keep this log and `reflection.md` updated at each interaction.

**What did the agent do?**

1. Read `README.md`, `app.py`, `diagrams/uml.mmd`, `reflection.md`, and `ai_interactions.md` (read-only, in plan mode).
2. Proposed the objects (Owner, Pet, Task, Scheduler, DailyPlan, ScheduledItem) with their data, actions, relationships, and edge cases, and saved the plan.
3. After approval, wrote the Mermaid UML in `diagrams/uml.mmd`.
4. After the two design decisions, created `pawpal_system.py` (dataclass and enum stubs, no logic), added `flagged` / `flagged_tasks()` to the UML, and filled in `reflection.md` and this file.
5. Asked to produce the Mermaid class diagram from the brainstormed attributes and methods. The agent rewrote `diagrams/uml.mmd` to match the stubs (renamed `DailyPlan.date` to `on`, added the missing `ScheduledItem`/`SkippedTask` to `Pet` links). It had no Mermaid CLI, so it replaced nested generics such as `list~tuple~Pet, Task~~` with plain-text return types to avoid a likely parser error. The diagram has not been rendered.
6. Asked to double check `pawpal_system.py` against `diagrams/uml.mmd`. The agent read both, then wrote a throwaway script that parses the diagram's class blocks and compares enum members, attributes, method names and parameter names with the real classes (via `dataclasses.fields` and `inspect`). Result: no differences across all 10 classes. It also found two design gaps the diagram did not show: `Task` equality (identical tasks compare equal and are unhashable) and two overlapping availability fields on `Owner`.
7. Asked to apply the two suggested fixes. The agent added a `uuid`-based `Task.id`, changed `Pet.edit_task` / `remove_task` to take `task_id`, documented that `Owner.day_start`/`day_end` is the source of truth with `available_minutes` as an optional extra cap, and updated the UML to match. It also moved a Mermaid `%%` comment it first placed inline onto its own line, since inline comments in a class member are likely to break parsing. Re-ran the comparison script (see result in the chat) and confirmed identical-field tasks now compare unequal.

**What did you have to verify or fix manually?**

Reviewing the proposed design. The agent recommended that a required task push out lower-priority tasks; I chose flagging instead. Still to check: that the Mermaid diagram renders and matches the stubs, and that `__pycache__/pawpal_system.cpython-314.pyc`, which is tracked in git, should be removed from the repo. No scheduling behavior has been verified yet because none is implemented.

---

## Prompt Comparison (SF11)

> Compare two different prompts (or two different models) on the same task.

Not attempted.

| | Option A | Option B |
|-|----------|----------|
| **Model / tool used** | | |
| **Prompt** | | |
| **Response summary** | | |
| **What was useful** | | |
| **Problems noticed** | | |
| **Decision** | | |

**Which approach did you use in your final implementation and why?**

<!-- Your conclusion -->

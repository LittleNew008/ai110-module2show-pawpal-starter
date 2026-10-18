# PawPal+ Project Reflection

> Status: `pawpal_system.py` is implemented (data classes, validation, scheduler) with 58 passing pytest tests. The Streamlit UI is not wired to it yet, so the closing reflection (section 5) is still **Pending**.

## 1. System Design

**a. Initial design**

The UML ([diagrams/uml.mmd](diagrams/uml.mmd)) started with these classes:

- **Owner**: holds the owner's name, daily availability window, preferences, and list of pets.
- **Pet**: holds pet info (name, species, breed, age, special needs) and its list of tasks.
- **Task**: one unit of care (title, category, duration, priority, optional preferred or fixed time, recurrence, `required` flag, completed).
- **Scheduler**: the only place with planning logic. It filters due tasks, sorts them, places them on the clock, detects conflicts, and explains choices.
- **DailyPlan**: the result, holding `ScheduledItem`s (task placed at a start/end time with a reason) and `SkippedTask`s (task plus why it was dropped).
- Enums `Priority`, `Category`, `Recurrence` keep the task fields constrained.

Owner, Pet and Task are plain data (dataclasses) so they are easy to test; the Scheduler owns the behavior.

**b. Design changes**

The design changed several times before any scheduling logic was written. Each change came from a decision, a cross-check of the code against the UML, or a review of the stubs, and I checked the suspected problems by running small scripts instead of trusting the review alone.

*From my decisions*

1. **Required tasks that don't fit are flagged, not forced in.** `SkippedTask` gained `flagged` and `DailyPlan` gained `flagged_tasks()`. The AI suggested letting a required task push out lower-priority ones; I chose to flag it so the plan stays predictable and the owner sees the problem.
2. **Plans use clock times.** `ScheduledItem` has `start` and `end`, and the owner has a `day_start`/`day_end` window, so conflicts can be detected.

*From checking the stubs against the UML*

3. **Tasks got a unique `id`.** Two "Feeding 10 min" tasks compared equal, so `Pet.edit_task` and `remove_task` could hit the wrong one. They now take a `task_id`.
4. **Owner availability has one source of truth.** The `day_start`/`day_end` window decides when care can happen; `available_minutes` is only an optional extra cap. Two overlapping fields left the scheduler without a rule for when they disagree.

*From reviewing the stubs for missing relationships and bottlenecks*

5. **Recurring tasks work now.** A single `completed` flag cannot work for a daily walk (done today, due again tomorrow). `Task` now has `start_date` and `last_completed`, `mark_complete` takes a date, and `priority_score()` was dropped in favor of a defined sort key (required, then priority, then shorter duration).
6. **`Pet` got an `id`, too.** It had the same equality bug as `Task`; `Owner.remove_pet` now takes a `pet_id`.
7. **`PetTask` replaced the `(Pet, Task)` tuples.** A task does not point back to its pet, and a back-reference would make the dataclass repr and equality recurse forever, so a small typed pair carries both.
8. **UI strings are accepted.** The starter `app.py` passes `"low"`, `"medium"` and `"high"`, which `Priority("high")` rejects. `Priority.from_str` parses them and `Task` converts a string priority itself.
9. **Time math is done in minutes.** `datetime.time` supports neither `time - time` nor `time + timedelta`, so `to_minutes` and `from_minutes` helpers were added. A day must end by 23:59, and `Owner` rejects `day_end <= day_start` (no overnight windows).
10. **Invalid data is rejected early.** `Task`, `Owner` and `ScheduledItem` validate themselves (duration above zero, non-empty title, end after start). `edit_task` may only change whitelisted fields and must re-validate; adding a duplicate id is rejected.
11. **`DailyPlan.warnings` was added.** Fixed-time clashes and flagged required tasks needed somewhere to be reported.
12. **`Owner.preferences` became `preferred_times`.** The untyped dict gave the scheduler no keys it could rely on. It is now a per-category default start time.
13. **`explain_choice` became a private `_build_reason`.** Reasons already live on `ScheduledItem` and `SkippedTask`, and a public method without the context could not produce a useful one.
14. **The scheduling rules are written down as a contract on `Scheduler`.** Fixed-time tasks are placed first; free time is tracked as intervals, not one total; a task that does not fit is skipped and later ones are still tried; the owner is a single resource, so tasks never overlap across pets; `fixed_time` beats `preferred_start`.

*From implementing the logic*

15. **The scheduler gets every pet's tasks from one Owner method.** `Owner.get_all_tasks()` returns a `PetTask` for each task of each pet in one pass, built fresh on every call, and `Scheduler.filter_due_tasks` reads only through it (`[pt for pt in owner.get_all_tasks() if pt.task.is_due(on)]`). I rejected caching an index of tasks because `Pet.tasks` is a public, mutable list, so a cache could go stale when a task is added, edited or removed. The pairs hold the live `Task` objects, so completing a task through one is visible everywhere. (This was first built as a lazy `iter_tasks()` with `get_all_tasks()` as a wrapper; see change 19 for why that was replaced.)
16. **The daily minutes cap is applied in sort order, before placement.** My first thought was to check the cap while placing, but fixed-time tasks are placed first, so a low-priority fixed task could use up minutes a required flexible task needed. Admitting tasks under the cap in sort order lets required and high-priority tasks claim minutes first. The cost is that a task admitted but then unplaceable does not give its minutes back (documented on `Scheduler`).
17. **`edit_task` validates on a copy.** It builds a `dataclasses.replace` copy to run validation, then copies the changed fields onto the original task. This keeps the same `Task` object (so anything holding it stays valid) and a rejected edit leaves the task untouched.
18. **`Task.start_date` defaults to today, and the tests exposed the consequence.** Every placement test failed on the first run because the tests planned for a March date while tasks defaulted to October, so nothing was due. The code was right and the tests were wrong, so I fixed the tests (a helper defaults `start_date` to the test day), but it is a reminder that a task created today will not appear on a plan for an earlier date.

*From auditing the code against the project's component requirements*

19. **Two gaps found and fixed.** (a) The Scheduler never called `get_all_tasks`: I had made it read from the separate `iter_tasks()`, so the one Owner method meant for "every pet's tasks together" was an unused wrapper. A spy subclass of `Owner` confirmed it (the Scheduler called only `iter_tasks`). I removed `iter_tasks` and made `get_all_tasks` the single method the Scheduler reads from. This gives up a lazy iterator whose only benefit was avoiding one temporary list, which was not worth a second public method, and it retracts part of what I claimed in change 15's first version. (b) `Task` exposed completion only as the raw `last_completed` date, with no way to ask for its status. I added `Task.is_completed(on)` (a one-off task stays completed; a recurring one is completed only on the day it was done) and made `is_due` use it, so there is one definition of "completed".

20. **`Task.description` was added.** The requirement describes a Task as having a description, and the code only had a short `title`. I kept `title` as the name shown in plans and added an optional free-text `description` (default empty) for details such as how to give a medication. It is editable through `edit_task`. I placed it after `required` so existing positional arguments keep working. It is not shown in `explain()` or `to_table()` yet, because the UI is not wired up; that is a decision for when `app.py` is connected.

Lesson so far: the biggest design problems (recurrence, identity, time arithmetic) were invisible in the UML and only showed up when I asked what each method would actually have to do, and when I ran the code. The cap-ordering problem (change 16) only appeared while writing the placement loop, and the bypassed `get_all_tasks` (change 19) only appeared when I checked what the Scheduler actually calls instead of what I intended it to call.

Not verified: the Mermaid diagram has not been rendered, and nothing is wired into `app.py` yet.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

Implemented: the scheduler considers the owner's available time window (plus an optional minutes cap), task duration, priority, the `required` flag, fixed or preferred times (a task's own `preferred_start`, else the owner's per-category default), and recurrence (whether a task is due that day). Order of importance: required tasks first, then priority, then shorter duration as a tie-breaker. The cap is applied in that order, then fixed-time tasks are placed, then flexible ones. Required and priority come first because missing meds or feeding matters more than enrichment. The owner is treated as a single person, so tasks never overlap even across pets.

**b. Tradeoffs**

The scheduler places tasks greedily in priority order and does not search for the best combination, and it never bumps an already placed task to make room for a required one that does not fit; that task is skipped and flagged for the owner instead. This is simple, predictable and easy to explain to the user, at the cost of sometimes leaving time unused. Concrete examples of that cost in the current code: flexible tasks go in the earliest free gap, which can split the day into gaps too small for a long task even when enough total time remains (a test pins this behavior), and minutes admitted under the daily cap are not refunded if the task then cannot be placed. A smarter packer could recover some of that time, but it would make the plan much harder to explain.

---

## 3. AI Collaboration

**a. How you used AI**

I used Claude Code through the whole project, in roughly this order:

- **Design:** it read the README and starter files, proposed the main objects with their data and actions, drafted the Mermaid UML, and generated the `pawpal_system.py` class stubs.
- **Review:** I asked it to check the stubs against the UML, to look for missing relationships and bottlenecks, and later to audit the code against the project's component requirements.
- **Implementation:** it wrote the data classes, the scheduler, the tests, the `main.py` demo, the docstrings and the README sections, and filled in this reflection and `ai_interactions.md` as we went.

The most helpful prompts were not "write this" but "check this against that": the code against the UML, the stubs against what each method would really have to do, and the implementation against the requirement list. Those review prompts produced the largest design improvements and caught real mistakes. Asking for the objects, the information each holds, and the actions each performs gave the most useful first draft.

**b. Judgment and verification**

**What the AI suggested**

- The object model (Owner, Pet, Task, Scheduler, DailyPlan and friends), and a recommendation that a required task which does not fit should push lower-priority tasks out to make room.
- A review of the stubs that found 15 issues, among them: a single `completed` flag cannot work for recurring tasks, `Pet` had the same equality bug as `Task`, `datetime.time` cannot do arithmetic, and fixed-time tasks must be placed before flexible ones.
- Implementation choices of its own, such as applying the daily minutes cap in sort order and dropping `priority_score()`.

**What I accepted**

- The overall design and the clock-time plan (an open question it raised, which I answered yes).
- The review findings: I asked for all of them to be applied, so I accepted them as a batch rather than weighing each one. That means I have not individually reviewed every choice Claude made inside that batch (the cap ordering and dropping `priority_score()` are the two I know of).

**What I rejected or changed**

- I rejected the suggestion to push out lower-priority tasks. I decided a required task that does not fit should be flagged instead, so the plan stays predictable and the owner is told when meds or feeding are at risk. The design changed to match (`flagged` on `SkippedTask`, `DailyPlan.flagged_tasks()`).
- I did not act on its suggestion to remove the tracked `.pyc` file from git; that is still open.

**Where the AI was wrong**

- **The Scheduler bypassed the Owner method.** Claude built a separate `iter_tasks()` for the Scheduler, so `get_all_tasks()` (the one method the requirements say the Scheduler must read from) was an unused wrapper. This was its own mistake, and it was only found when I asked it to double check against the requirement list. It then fixed it and withdrew its earlier claim that the lazy iterator was the better design.
- **A false alarm from its own checker.** The UML comparison script reported a difference that did not exist (a bug in the script's handling of enums), which it diagnosed and fixed rather than changing the code.
- **A test setup error.** 36 of the first 53 tests failed because tasks default to today's `start_date` while the tests planned for a March date. The scheduler was right and the tests were wrong.

**How I verified the result**

- **Name-level check against the design:** a script compares every class, attribute, method and parameter in `pawpal_system.py` with `diagrams/uml.mmd`; it reports no differences.
- **Reproduce before fixing:** each review suspicion (equal pets, `time` arithmetic errors, rejected priority strings, unvalidated assignment, the Scheduler's actual calls) was reproduced by running code before a fix was made.
- **Tests that can fail:** 58 pytest tests pass, including random-input invariants. Across several rounds, deliberate bugs were injected into a scratch copy (a broken sort key, no gap search, no flagging, no cap check, a weekly rule that ignores the weekday, a Scheduler that bypasses `get_all_tasks`, a no-op `mark_complete`, an `add_task` that does not append) and the tests caught each one. One further mutation was not aimed at the tests being checked, and I did not count it as evidence for them.
- **End to end:** `python main.py` runs the whole pipeline, and its output is pasted in the README, verified identical to a fresh run.

**What is still not verified**

The Mermaid diagram has never been rendered, nothing is connected to the Streamlit UI, and the random tests check invariants (no overlaps, nothing lost), not that the plan chosen is the best possible one.

---

## 4. Testing and Verification

**a. What you tested**

58 pytest tests in `tests/test_pawpal.py`, all passing:

- **Two basic behaviors, tested directly:** calling `mark_complete()` changes the task's status (starts incomplete, becomes complete, and a different task is unaffected), and adding a task to a pet increases that pet's task count (0, 1, 2, and a rejected duplicate leaves the count unchanged). Each was mutation-checked: making `mark_complete` do nothing, or making `add_task` forget to append, makes the matching test fail.

- **Retrieval:** tasks from every pet come back paired with the right pet, as the live objects, and later additions are seen without a stale cache; only due tasks are selected across pets. A spy subclass of `Owner` proves the Scheduler reads exactly once through `get_all_tasks` and still plans for a pet added after the Scheduler was created.
- **Task rules:** once, daily and weekly due dates, readable completion status that resets for recurring tasks, validation, priority strings, and the time helpers.
- **Management:** identical tasks and same-named pets stay distinct and are removed by id; duplicate ids are rejected; `edit_task` keeps identity, validates, and whitelists fields; invalid availability is rejected.
- **Scheduling:** sort order; a fixed-time task is not displaced by a higher-priority flexible one; fixed-time clashes; a required task that does not fit is flagged and not forced in; a required fixed task outside the window is flagged; fragmented free time; skip-and-continue; the minutes cap; preferred times and owner category preferences; no overlap across pets; a daily task done today returns tomorrow; empty plans; the table and explanation output.
- **Invariants:** 25 seeded random plans check that nothing overlaps, everything stays in the window, fixed tasks start at their fixed time, the cap is respected, and every due task is either scheduled or skipped exactly once.

Separately from the test suite, `main.py` is a manual end-to-end demo: it builds an owner with two pets and six tasks at different times, generates today's plan and prints it, which confirmed that the pieces work together outside of pytest. Its output is pasted into the README's Sample Output section as evidence, and was verified to match a fresh run exactly. It is not an automated check, since nothing asserts on its output.

These matter because the scheduler's value is that its plan can be trusted: a double-booked slot or a silently dropped meds task is worse than no plan.

**b. Confidence**

Fairly confident in the scheduler's core rules for single-day plans, since they are covered by targeted tests, random invariant checks, and a mutation check (five deliberate bugs, all caught). Less confident about everything the tests do not touch: the Streamlit UI is not connected, the Mermaid diagram was never rendered, and the random tests only assert invariants, not that the chosen plan is the best one. Edge cases to test next: tasks on the same pet with the same fixed time, a preferred start that falls outside the window, tasks with seconds in their times (they are truncated to whole minutes), windows ending at 23:59, a pet with no tasks among others that have some, and many tasks (to confirm speed is fine).

---

## 5. Reflection

**a. What went well**

Pending.

**b. What you would improve**

Pending.

**c. Key takeaway**

Pending. Early note: settling open design questions (clock times vs ordering only, what happens to required tasks) before writing code made the stubs straightforward, and reviewing the stubs for what each method would really need caught problems the UML could not show.

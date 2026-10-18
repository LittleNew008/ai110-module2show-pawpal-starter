# PawPal+ Project Reflection

> Status: `pawpal_system.py` is implemented (data classes, validation, scheduler) with 157 passing pytest tests (130 backend, 27 headless UI), including a Phase 5 edge-case round and the Phase 4 algorithms (sorting, filtering, conflict warnings, recurring tasks). `app.py` is connected to it. The closing reflection (section 5) is still **Pending**.

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

5. **Recurring tasks work now (this model was later replaced; see change 25).** A single `completed` flag cannot work for a daily walk (done today, due again tomorrow). `Task` now has `start_date` and `last_completed`, `mark_complete` takes a date, and `priority_score()` was dropped in favor of a defined sort key (required, then priority, then shorter duration).
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

20. **`Task.description` was added.** The requirement describes a Task as having a description, and the code only had a short `title`. I kept `title` as the name shown in plans and added an optional free-text `description` (default empty) for details such as how to give a medication. It is editable through `edit_task`. I placed it after `required` so existing positional arguments keep working. The UI forms let you enter and edit it, but it is not shown in `explain()` or `to_table()`, so it does not appear in the plan table.

*From connecting the UI*

21. **`Owner.set_availability` now takes the minutes cap.** The UI needs to change the window and the cap together, and assigning `owner.available_minutes` directly would skip validation. The method is now `set_availability(start, end, available_minutes=None)`: it replaces all three values, `None` means no cap, and bad input changes nothing. The catch is that calling it without a cap removes an existing cap, so the UI always passes all three.
22. **`Pet` and `Owner` validate their names.** A form hands raw text to `Pet(...)`, and `Pet` accepted a blank name. `Pet` now rejects an empty name or species and a negative age, and `Owner` rejects an empty name, the same way `Task` already validated itself. This keeps the rules in the classes: the UI only catches `ValueError` and shows it. The one rule that stays in the UI is rejecting a duplicate pet name, because the pet pickers show names (the classes themselves still allow two pets with the same name, told apart by id).
23. **How the UI is wired, and why.** The `Owner` lives in `st.session_state` and is created only when the key is missing, because Streamlit re-runs the whole script on every click. Forms call `Owner.add_pet(Pet(...))` and `Pet.add_task(Task(...))`. Buttons use the objects' own methods as `on_click` callbacks (`task.mark_complete`, `pet.remove_task`, `owner.remove_pet`), which run before the page redraws. After a successful form action the app stores a message and calls `st.rerun()`; without that, lists drawn earlier on the page would show stale data until the next click. The plan is rebuilt from the live `Owner` on every run once "Generate schedule" has been pressed, so it cannot go stale, and everything is addressed by id, not by name.

*From Phase 4 (the algorithmic layer)*

25. **Recurrence switched from "recomputed every day" to "a new instance when completed".** Before, a daily task was one `Task` that `is_due` judged afresh each day from a `last_completed` date, and nothing was ever created. Phase 4 asked that completing a daily or weekly task creates a new instance for the next occurrence. Doing both would have duplicated tasks, so I replaced the old model instead of layering on it: `last_completed` became `completed_on`; `is_due` now means "started and not completed"; `Task.mark_complete(on)` returns the next occurrence (a copy with a new id and `start_date = next_due_date(on)`); `Pet.complete_task` adds it to the pet; `Scheduler.mark_task_complete(task_id, on)` finds the right pet; and `is_completed()` lost its date argument because completion now belongs to one occurrence. The next date is calculated with `timedelta`, anchored to the task's own schedule (start date plus whole steps) rather than "completion day plus a week", which gives the same answer when a task is finished on time and keeps a weekly Monday task on Mondays when it is finished late. What this costs: the plan cannot preview a recurring task beyond its next occurrence, and finished occurrences stay in the list as history. What it gains: a real completion history (so "filter by status" means something) and the behavior the spec describes. Six existing tests asserted the old behavior and were rewritten.
26. **Sorting by time and filtering.** `Task.requested_time` (fixed time, else preferred time, else none) gives tasks one time to sort on. `Scheduler.sort_by_time` orders by it with untimed tasks last, and `Scheduler.filter_tasks` filters by pet name and/or completion status. The planner's own ordering (`sort_tasks`: required, priority, shorter) is unchanged, since planning order is about importance, not the clock.
27. **Conflict warnings before planning.** `Scheduler.find_conflicts(on)` returns warning messages for due fixed-time tasks whose time ranges overlap, for the same or different pets, and never raises. The plan already resolved such clashes silently when it was built; this lets the owner see them first, and the UI shows them as soon as a task is added.
28. **Two simplifications from the Step 5 review** (details in section 3b): `detect_conflicts` was changed to compare pairs with `itertools.combinations` and the existing `ScheduledItem.overlaps` (this one was reversed, see change 30), and the `sort_by_time` key lost a redundant element.
29. **UI changes to match.** The Done button now calls `Scheduler.mark_task_complete` and says when the next occurrence is due; the task list is one list built with `filter_tasks` (by pet, and by Open / Done / All) and ordered with `sort_by_time`, instead of one block per pet.

*From trying the UI by hand*

24. **The daily minutes limit was easy to set and then silently ignored.** I tried the UI with a limit of 60 minutes per day and could still add four 20-minute tasks. Reproducing it showed two separate things. First, the scheduler was correct: with the limit saved, the plan scheduled three tasks (60 min) and skipped the fourth with a reason, and adding tasks was never meant to be blocked, because the limit caps what gets scheduled, not what you may record, and a recurring or required task still belongs on the list. Second, the form had a real trap: the number field only took effect if a separate "Limit total care minutes" checkbox was also ticked, so typing 60 without the checkbox saved no limit at all. I removed the checkbox (the field is now "Max care minutes per day", where 0 means no limit), and added a warning in the Tasks section as soon as today's tasks add up to more than the available time. The available time comes from a new `Owner.capacity_minutes()` (the window length or the cap, whichever is smaller), so that rule lives in the class, not in the UI. I chose a warning over blocking the add; blocking would also be a defensible design, and is a decision I can reverse.

*From the last round of requests (conflict-check speed, the diagram, pet tiles)*

30. **`detect_conflicts` is efficient again, and shares its search with `find_conflicts`.** Last round, Claude replaced the sorted sweep with a pairwise `combinations` version because it was shorter, and judged the speed difference imperceptible. I asked for better efficiency instead, so that decision was reversed. The new version is one helper, `_overlapping_pairs`, used by both `detect_conflicts` and `find_conflicts`: sort the spans by start once, then compare each only with the later spans that start before it ends, stopping at the first that does not. The original sweep was itself wasteful, copying a list slice on every pass and repeating the overlap rule, and both are gone. Measured on identical inputs, all three versions returned the same pairs in the same order on 3000 random inputs; on a conflict-free day the new one took 9 microseconds for 50 tasks against 219 for the pairwise version (about 24 times faster), and 212 against 101,170 for 1000 tasks (about 475 times faster), and it is 1.2 to 3 times faster than the original sweep. The cost is a little more code (a helper of about ten lines) and one remaining copy of the overlap rule besides `ScheduledItem.overlaps`, which a test now checks against it.
31. **Pet tiles replace the pet dropdowns.** The pet selector in the task form and the pet filter in the task list were dropdowns; pets are now a grid of bordered tiles (three per row) showing icon, name, species, breed and age, and open and done counts, with Select and Remove buttons. The selected tile is highlighted and decides which pet new tasks go to; a new pet is selected automatically, and removing the selected pet falls back to another. The task list's pet filter became a "Show tasks for: All pets / (name) only" choice. I looked at the real page in a headless browser and found the "Selected" button text cut off when the Select and Remove buttons sat side by side in a narrow tile, so they are now stacked and Remove is a plain text-style button.
32. **The Mermaid diagram was rendered, not just assumed valid.** `diagrams/uml.mmd` now has a rendered picture, `diagrams/uml.png`, shown in the README. Getting there needed a browser: there was none, so I downloaded a headless Chromium and its missing system libraries and fonts into a scratch folder (nothing was installed system-wide or in the project). The first render parsed correctly but had no labels because the machine had no fonts, so a parse success alone would have been misleading; I looked at the image, added a font, and checked that all 11 classes, their attributes and methods, and the relationships appear. The risky-looking parts of the file (`**changes`, the comment lines, the self-link on `Task`) all render correctly.

*From Phase 5 (testing and verification)*

33. **`sort_by_time` now breaks ties ignoring case.** Probing edge cases showed that tasks with the same time and priority were ordered by the raw title, so every capital letter sorted before every lowercase one: `Apple, Cherry, banana, zebra`. I wrote the new test first with the order a person expects, watched it fail, and asked whether the bug was in the test or the code: the test was right, and the code was comparing characters by code. The key now uses `title.casefold()`. The earlier tests had not seen it because they only used lowercase titles.

Lesson so far: the biggest design problems (recurrence, identity, time arithmetic) were invisible in the UML and only showed up when I asked what each method would actually have to do, and when I ran the code. The cap-ordering problem (change 16) only appeared while writing the placement loop, and the bypassed `get_all_tasks` (change 19) only appeared when I checked what the Scheduler actually calls instead of what I intended it to call.

Not verified: the UI has been tried by hand only briefly (which is how change 24 was found), plus headless tests, a server start-up check and a headless-browser screenshot of the layout, so it has not had a proper review in a normal browser (the pet icons in particular could not be seen, because the screenshot browser has no emoji font).

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

Implemented: the scheduler considers the owner's available time window (plus an optional minutes cap), task duration, priority, the `required` flag, fixed or preferred times (a task's own `preferred_start`, else the owner's per-category default), and whether a task is due (it has started and is not completed; completing a daily or weekly task creates its next occurrence). Order of importance: required tasks first, then priority, then shorter duration as a tie-breaker. The cap is applied in that order, then fixed-time tasks are placed, then flexible ones. Required and priority come first because missing meds or feeding matters more than enrichment. The owner is treated as a single person, so tasks never overlap even across pets.

**b. Tradeoffs**

The scheduler places tasks greedily in priority order and does not search for the best combination, and it never bumps an already placed task to make room for a required one that does not fit; that task is skipped and flagged for the owner instead. This is simple, predictable and easy to explain to the user, at the cost of sometimes leaving time unused. Concrete examples of that cost in the current code: flexible tasks go in the earliest free gap, which can split the day into gaps too small for a long task even when enough total time remains (a test pins this behavior), and minutes admitted under the daily cap are not refunded if the task then cannot be placed. A smarter packer could recover some of that time, but it would make the plan much harder to explain.

**Conflict detection (Phase 4).** `find_conflicts` only looks at tasks with a fixed time. A flexible task has no committed slot (the planner moves it to wherever it fits), and a preferred time is only a wish, so checking them would raise warnings about problems the planner will solve itself. The price is that two tasks which merely prefer the same time are not warned about, and a flexible task that cannot be placed shows up as a skipped task in the plan rather than as a conflict. In the other direction, I chose to compare time ranges rather than only exact start times: "same start" would miss a 08:00 to 08:30 walk overlapping an 08:20 medication, which is the more realistic clash, and it costs only a duration comparison per pair.

**Recurring tasks (Phase 4).** A new occurrence is created only when the current one is completed. That keeps exactly one open occurrence per series and gives a clean completion history, but a task that is never completed never produces a next one, and the plan cannot show next week's recurring tasks ahead of time.

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
- For Phase 4: a list of small algorithms (sort by time, filter by pet and status, conflict warnings, instance-based recurrence), and, when asked how a finished algorithm could be simplified, replacing the sorted sweep in `detect_conflicts` with `itertools.combinations` plus the existing `overlaps()`. I later asked for better efficiency instead, and that suggestion was reversed (change 30).

**What I accepted**

- The overall design and the clock-time plan (an open question it raised, which I answered yes).
- The review findings: I asked for all of them to be applied, so I accepted them as a batch rather than weighing each one. That means I have not individually reviewed every choice Claude made inside that batch (the cap ordering and dropping `priority_score()` are the two I know of).
- The UI layout and widget choices, and the small backend additions the forms needed (a cap parameter on `set_availability`, validation on `Pet` and `Owner`), were Claude's choices to implement the wiring I asked for. I have not reviewed them beyond running the app's tests.
- The `detect_conflicts` simplification was accepted on the evidence at the time (identical output on 2000 random inputs; slower, but only 0.27 ms for 50 tasks), and then superseded: I asked for better efficiency, so it was replaced by a shared early-exit sweep (change 30). Accepting a change because the measured cost looks small is a judgment about my own use, and I changed my mind about it.

**What I rejected or changed**

- I rejected the suggestion to push out lower-priority tasks. I decided a required task that does not fit should be flagged instead, so the plan stays predictable and the owner is told when meds or feeding are at risk. The design changed to match (`flagged` on `SkippedTask`, `DailyPlan.flagged_tasks()`).
- I rejected Claude's decision to keep the slower pairwise `detect_conflicts`: I asked for better efficiency, and it was rewritten as a shared early-exit sweep.
- I did not act on its suggestion to remove the tracked `.pyc` file from git; that is still open.

**Where the AI was wrong**

- **The Scheduler bypassed the Owner method.** Claude built a separate `iter_tasks()` for the Scheduler, so `get_all_tasks()` (the one method the requirements say the Scheduler must read from) was an unused wrapper. This was its own mistake, and it was only found when I asked it to double check against the requirement list. It then fixed it and withdrew its earlier claim that the lazy iterator was the better design.
- **A false alarm from its own checker.** The UML comparison script reported a difference that did not exist (a bug in the script's handling of enums), which it diagnosed and fixed rather than changing the code.
- **A test setup error.** 36 of the first 53 tests failed because tasks default to today's `start_date` while the tests planned for a March date. The scheduler was right and the tests were wrong.
- **A UI trap the tests missed.** Claude's form made the minutes limit depend on a separate checkbox, so typing a limit without ticking it silently saved nothing. Its 15 UI tests all ticked the checkbox, so none could notice; I found it only by trying the app by hand (change 24). The checkbox is gone, and there are now tests for the exact scenario I tried.
- **A UI test that could not fail.** Claude's first version of the "Done" button test passed even when the button was deliberately broken to record the wrong day, because it used a one-off task, which counts as completed on any day. A mutation check exposed this; the test now uses a daily task and asserts the exact date, and the same deliberate bug is caught.
- **A sort key with a redundant part.** Claude's first `sort_by_time` key had two elements doing the same job: a flag for "no time" and a `time.max` fallback for the same case. A mutation check exposed it, because replacing the fallback changed nothing and the tests still passed. It kept only the fallback, and the same mutation is now caught.
- **A sweep written too cleverly.** Claude's first version of the new conflict code used a comprehension trick (`for start in [..]`), nested tuple payloads and `# type: ignore` comments to get around its own typing. It was correct but hard to read, which undercut the point of the Step 5 readability lesson, so it was rewritten with a plain loop and a generic helper, and the type-ignore comments were deleted.
- **A test that could not catch the regression it was named for.** Claude's first efficiency test counted calls to `to_minutes`, but the sweep calls that only while building the spans, so changing the early `break` to `continue` (which silently turns it back into a full scan) would not have changed the count. It noticed this before relying on the test, and replaced it with a test of the helper that counts span lookups; a mutation that removes the early exit is now caught by exactly that test.
- **A tile layout with clipped text.** Claude's first pet tile put Select and Remove side by side, and the "Selected" label was cut off ("Selec..."). Tests could not see this; a screenshot of the real page did. The buttons are now stacked.
- **A bug its own tests could not see.** Claude wrote the title tie-break in Phase 4, and its tests used only lowercase titles, so a case-sensitive comparison passed every one of them. It was found only when Phase 5 probed edge cases on purpose, which is the argument for having edge cases planned separately from the code's author's assumptions. It also means my confidence is capped: tests written by the same assistant that wrote the code can share its blind spots.
- **A verification script that misled for a moment.** When checking that the README's pasted test output matched the real output, Claude's script said `False`; the cause was its own regular expression mispairing the code fences. It re-checked with an exact comparison (`True`) instead of accepting either answer.
- **A broken test harness, caught before it misled.** While mutation-checking the new code, Claude's helper script passed the wrong arguments, so nothing was mutated and every run printed "83 passed". It noticed the assertion errors in the output, did not count those runs, fixed the helper and re-ran everything.

**How I verified the result**

- **Name-level check against the design:** a script compares every class, attribute, method and parameter in `pawpal_system.py` with `diagrams/uml.mmd`; it reports no differences.
- **Reproduce before fixing:** each review suspicion (equal pets, `time` arithmetic errors, rejected priority strings, unvalidated assignment, the Scheduler's actual calls) was reproduced by running code before a fix was made.
- **Tests that can fail:** 157 pytest tests pass (130 backend, 27 UI), including random-input invariants. Across several rounds, deliberate bugs were injected into a scratch copy (a broken sort key, no gap search, no flagging, no cap check, a weekly rule that ignores the weekday, a Scheduler that bypasses `get_all_tasks`, a no-op `mark_complete`, an `add_task` that does not append) and the tests caught each one. One further mutation was not aimed at the tests being checked, and I did not count it as evidence for them.
- **End to end:** `python main.py` runs the whole pipeline, and its output is pasted in the README, verified identical to a fresh run.
- **UI integration:** 21 headless tests drive the real `app.py` with Streamlit's `AppTest` (fill a form, click a button) and assert on the `Owner` stored in `st.session_state`, which checks the wiring itself. The real server was also started, and it reported healthy and served the page. Deliberate UI bugs (an `Owner` rebuilt on every run, a task added to the wrong pet, the add-pet form not calling `Owner.add_pet`, the wrong completion date, no rerun after an action) were each caught.
- **Phase 4 algorithms:** eight deliberate bugs in the new backend code (a next date that ignores how late the task was done, a next date always one step from the start, completing never creating the next occurrence, double completion creating a duplicate, untimed tasks sorted first, an inverted status filter, a case-sensitive pet filter, conflicts that only match identical start times) were each caught by at least one test, after the sort-key fix above. Five deliberate bugs in the new UI wiring (the Done message, the time sort, the pet filter, the status filter, the conflict warnings) were also each caught. The `detect_conflicts` simplification was checked for identical output against the old version on 2000 random inputs before it replaced it.
- **Conflict-check speed:** the shared sweep was compared with the pairwise version and the original sweep on 3000 random inputs (identical pairs in identical order) and benchmarked (24 times faster than pairwise at 50 tasks, about 475 times at 1000). Tests check it against a brute-force pairwise check on 20 random inputs, check that on a conflict-free day of 1000 spans it looks at each span about once rather than comparing every pair, and check touching spans. Four deliberate bugs (never stopping early, counting touching spans as overlapping, sorting the wrong way, stopping too early) were each caught.
- **UI tiles:** 4 new UI tests and 3 rewritten ones; six deliberate bugs (a tile click not selecting, tasks always going to the first pet, a new pet not auto-selected, wrong open counts, no fallback selection after a removal, the list scope ignoring the selected pet) were each caught. I also drove the real page in a headless browser (added pets and tasks through the actual forms) and looked at the screenshot, which is how the clipped button label was found.
- **The diagram:** rendered with headless Chromium (see change 32) and inspected, not just parsed.
- **Phase 5 round:** the 12 edge-case probes (11 correct, 1 bug, fixed with a failing test first); then 8 deliberate bugs aimed at the new tests, of which 7 were caught immediately. The survivor changed a comparison in the code that only chooses the explanation for a skipped fixed task, so scheduling was unaffected, but it could have printed "outside the window" for a task that really clashed; a new test now pins the correct message and kills that mutation. The suite passes with `python -m pytest` (exit code 0), and its output is pasted in the README, verified identical to the captured run.

**What is still not verified**

The UI has been tried by hand only briefly (plus headless tests, a server start-up check and one headless-browser screenshot), so it has not had a proper review in a normal browser, and I could not see the pet icons because the screenshot browser has no emoji font; and the random tests check invariants (no overlaps, nothing lost), not that the plan chosen is the best possible one.

---

## 4. Testing and Verification

**a. What you tested**

157 pytest tests, all passing: 130 backend tests in `tests/test_pawpal.py` and 27 headless UI tests in `tests/test_app.py`.

**Test plan (Phase 5).** I could not open a separate chat session for this, so the plan was drafted in the same session, but kept separate from the implementation work. The five core behaviors to verify are: sorting (tasks come back in chronological order), recurrence (completing a daily or weekly task creates the next one), conflict detection (duplicate and overlapping times are flagged), the planning rules (no overlaps, inside the day window, the daily limit respected, required tasks flagged when they cannot fit), and multi-pet retrieval with the UI wiring. For each I listed the happy path and the edge cases most likely to break it: an empty pet or no pets, several tasks at the exact same time, a task exactly touching a window edge or one minute outside it, dates that cross a month, a year or a leap day, a task completed very late, a completed or not-yet-due task, an empty list passed where "no list" was meant, blank input, and a very busy day. Before writing tests for the edge cases I probed them against the real code (12 probes: 11 behaved correctly, 1 revealed a bug), so the new tests describe behavior I had actually seen.

- **Phase 5 edge cases (27 new test cases, counting each parametrized row):** sorting an empty list and a list with no times, ties broken ignoring case, and a plan listing chronologically whatever order tasks were added; next due dates across month, year and leap-day boundaries and a weekly task staying on its weekday after three late completions; identical duplicate times and a three-way clash reporting every pair; fixed tasks starting or ending exactly at the window edges and one minute outside, a flexible task exactly as long as the window, and a clash at closing time being explained as a clash; times with seconds being truncated; a pet with no tasks, an owner with no pets, a plan where every task is completed, an empty list not falling back to every task, a required task bigger than the daily limit, generating a plan twice changing nothing, and a 600-task day keeping every invariant; and in the UI, a pet with no tasks and a schedule with no pets.

- **Two basic behaviors, tested directly:** calling `mark_complete()` changes the task's status (starts incomplete, becomes complete, and a different task is unaffected), and adding a task to a pet increases that pet's task count (0, 1, 2, and a rejected duplicate leaves the count unchanged). Each was mutation-checked: making `mark_complete` do nothing, or making `add_task` forget to append, makes the matching test fail.

- **Retrieval:** tasks from every pet come back paired with the right pet, as the live objects, and later additions are seen without a stale cache; only due tasks are selected across pets. A spy subclass of `Owner` proves the Scheduler reads exactly once through `get_all_tasks` and still plans for a pet added after the Scheduler was created.
- **Task rules:** due means started and not completed (an overdue task stays due), completion status belongs to each occurrence, validation, priority strings, and the time helpers.
- **Recurring tasks:** the next due date for daily and weekly tasks (on time, three days late, weekly finished late on a Wednesday, more than a week late, finished early, and a one-off with none); completing creates a new occurrence with a new id and the same details; a one-off or an already completed task creates nothing and a second completion never duplicates; `Pet.complete_task` adds exactly one occurrence; `Scheduler.mark_task_complete` finds the right pet and chains through three days; a series never has two open occurrences and the plan follows it.
- **Sorting and filtering:** `sort_by_time` orders tasks added out of order, puts untimed tasks last, treats midnight as a real time, breaks ties by priority then title, prefers a fixed time over a preferred one, and leaves its input unchanged; `filter_tasks` by pet (ignoring case and spaces), by status, combined, on a given list, and with an unknown pet.
- **Conflict sweep:** the helper agrees with a brute-force pairwise check on 20 random inputs, does about one lookup per span on a conflict-free day of 1000 spans, and treats touching spans as not overlapping.
- **Conflict warnings:** same-pet and different-pet overlaps, duration-aware overlap versus back-to-back tasks, every overlapping pair reported in time order, flexible/preferred/completed/not-yet-due tasks ignored, nothing raising on empty input, and the planner still resolving a conflict that was warned about.
- **Management:** identical tasks and same-named pets stay distinct and are removed by id; duplicate ids are rejected; `edit_task` keeps identity, validates, and whitelists fields; invalid availability is rejected.
- **Scheduling:** sort order; a fixed-time task is not displaced by a higher-priority flexible one; fixed-time clashes; a required task that does not fit is flagged and not forced in; a required fixed task outside the window is flagged; fragmented free time; skip-and-continue; the minutes cap; preferred times and owner category preferences; no overlap across pets; a daily task done today returns tomorrow; empty plans; the table and explanation output.
- **Invariants:** 25 seeded random plans check that nothing overlaps, everything stays in the window, fixed tasks start at their fixed time, the cap is respected, and every due task is either scheduled or skipped exactly once.
- **UI wiring (`tests/test_app.py`):** the `Owner` is created once and survives reruns; the add-pet form adds to the `Owner` and shows the pet; blank and duplicate pet names and blank task titles show an error and add nothing; a task goes to the selected pet only; the fixed, preferred and flexible timing modes set the right fields; edit, done and remove actions work and a bad edit leaves the task untouched; the availability form saves the window and cap and rejects a bad window; the schedule table covers every pet's tasks, updates as tasks change without pressing the button again, warns about a required task that cannot fit, and drops completed tasks. Pets are tiles: there is one tile with Select and Remove buttons per pet (four pets wrap onto a second row) and no pet dropdown left; a tile shows its icon, details and open and done counts; a new pet is selected automatically; clicking a tile changes which pet gets new tasks; removing the selected pet falls back to another; and the task list's "Show tasks for" choice follows the selected tile. For Phase 4: the Done button on a daily task completes it, adds the next occurrence and says when it is due; the task list is sorted by time and can be filtered by pet and by Open / Done / All; and overlapping fixed-time tasks show a conflict warning (different pets) as soon as they are added, without being refused.

Separately from the test suite, `main.py` is a manual end-to-end demo: it builds an owner with two pets and six tasks at different times, generates today's plan and prints it, which confirmed that the pieces work together outside of pytest. Its output is pasted into the README's Sample Output section as evidence, and was verified to match a fresh run exactly. It is not an automated check, since nothing asserts on its output.

These matter because the scheduler's value is that its plan can be trusted: a double-booked slot or a silently dropped meds task is worse than no plan.

**b. Confidence**

**Four out of five stars.** I am confident in the scheduler's core rules for single-day plans: all 157 tests pass, each of the five core behaviors is covered on its happy path and its edges, random inputs check the rules that must always hold, and dozens of deliberately injected bugs were each caught (one mutation survived in the last round, was explained, and now has its own test). The Phase 5 edge-case round also found and fixed a real bug. I stop short of five because the tests were written by the same assistant that wrote the code and can share its blind spots, and because of everything the tests do not touch: the UI has only been tried by hand briefly, plus headless tests, a server start-up check and one headless-browser screenshot, and the random tests only assert invariants, not that the chosen plan is the best one. Most of the edge cases I had listed to test next are now tested (identical times, windows ending at 23:59 and one minute outside them, a pet with no tasks, seconds in times, a very busy day). Still untested: overnight days and time zones (not supported), code coverage (not measured), plans that are provably the best possible (the planner is greedy by design), and the UI in a normal browser.

---

## 5. Reflection

**a. What went well**

Pending.

**b. What you would improve**

Pending.

**c. Key takeaway**

Pending. Early note: settling open design questions (clock times vs ordering only, what happens to required tasks) before writing code made the stubs straightforward, and reviewing the stubs for what each method would really need caught problems the UML could not show.

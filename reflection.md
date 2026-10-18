# PawPal+ Project Reflection

> Status: design phase (UML + class stubs). Sections that depend on implementation or testing are marked **Pending** and will be filled in as the work happens.

## 1. System Design

**a. Initial design**

The UML ([diagrams/uml.mmd](diagrams/uml.mmd)) has these classes:

- **Owner**: holds the owner's name, daily availability window, preferences, and list of pets.
- **Pet**: holds pet info (name, species, breed, age, special needs) and its list of tasks.
- **Task**: one unit of care (title, category, duration, priority, optional preferred or fixed time, recurrence, `required` flag, completed).
- **Scheduler**: the only place with planning logic. It filters due tasks, sorts them, places them on the clock, detects conflicts, and explains choices.
- **DailyPlan**: the result, holding `ScheduledItem`s (task placed at a start/end time with a reason) and `SkippedTask`s (task plus why it was dropped).
- Enums `Priority`, `Category`, `Recurrence` keep the task fields constrained.

Owner, Pet and Task are plain data (dataclasses) so they are easy to test; the Scheduler owns the behavior.

**b. Design changes**

Pending implementation. Two changes so far. First, the UML was re-synced with the stubs (for example `DailyPlan.date` became `on`, and pet-task pair return types were written as plain text to keep Mermaid's parser happy). Second, made before any logic was written: `SkippedTask` gained a `flagged` field and `DailyPlan` gained `flagged_tasks()`, so a required task (for example meds) that cannot fit is surfaced as a warning rather than being silently dropped like an optional task.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

Planned (not yet implemented): the scheduler considers the owner's available time window, task duration, priority, the `required` flag, fixed or preferred times, and recurrence (whether a task is due that day). Order of importance: required tasks first, then priority, then shorter duration as a tie-breaker. Required and priority come first because missing meds or feeding matters more than enrichment.

**b. Tradeoffs**

Planned tradeoff: the scheduler places tasks greedily by priority and does not search for the best possible combination. It also does not bump lower-priority tasks to make room for a required task that does not fit; that task is dropped and flagged for the owner instead. This is simple and predictable and easy to explain to the user, at the cost of sometimes leaving available time unused. Pending confirmation once implemented.

---

## 3. AI Collaboration

**a. How you used AI**

Claude Code was used for design brainstorming: reading the README and starter files, proposing the main objects with their data and actions, drafting the Mermaid UML, and generating the `pawpal_system.py` class stubs. Asking for the objects, the information each holds, and the actions each performs gave the most useful output.

**b. Judgment and verification**

The AI suggested that a required task that does not fit should push out lower-priority tasks to make room. I did not take that suggestion: I decided a required task that does not fit should instead be flagged, and the design was changed to match (`flagged` on `SkippedTask`). Verification of the stubs so far is limited to checking that the module imports; the scheduling behavior itself is not verified yet.

---

## 4. Testing and Verification

**a. What you tested**

Pending. No logic exists yet. Planned tests: sorting order, fitting tasks into the available window, flagging of required tasks that do not fit, conflict detection for overlapping fixed times, and recurrence.

**b. Confidence**

Pending.

---

## 5. Reflection

**a. What went well**

Pending.

**b. What you would improve**

Pending.

**c. Key takeaway**

Pending. Early note: settling open design questions (clock times vs ordering only, what happens to required tasks) before writing code made the stubs straightforward.

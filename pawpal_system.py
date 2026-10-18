"""PawPal+ core domain classes and the daily scheduler.

Data classes validate their own invariants. All time math is done in whole
minutes since midnight (see `to_minutes`) because `datetime.time` has no
arithmetic.
"""

import dataclasses
import math
from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum
from uuid import uuid4

MINUTES_PER_DAY = 24 * 60


def to_minutes(t: time) -> int:
    """Whole minutes since midnight.

    `datetime.time` supports no arithmetic (no `time - time`, no `+ timedelta`),
    so all scheduling math is done in minutes and converted back for display.
    """
    return t.hour * 60 + t.minute


def from_minutes(minutes: int) -> time:
    """Inverse of `to_minutes`. 24:00 is not representable, so a day ends by 23:59."""
    if not 0 <= minutes < MINUTES_PER_DAY:
        raise ValueError(f"minutes must be in [0, {MINUTES_PER_DAY}), got {minutes}")
    return time(minutes // 60, minutes % 60)


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _new_id() -> str:
    return uuid4().hex


class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @classmethod
    def from_str(cls, value: str) -> "Priority":
        """Parse UI strings such as "low", "Medium" or "HIGH"."""
        try:
            return cls[value.strip().upper()]
        except KeyError:
            raise ValueError(f"unknown priority {value!r}; expected low, medium or high") from None


class Category(Enum):
    WALK = "walk"
    FEEDING = "feeding"
    MEDS = "meds"
    ENRICHMENT = "enrichment"
    GROOMING = "grooming"
    OTHER = "other"


class Recurrence(Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass
class Task:
    title: str
    duration_minutes: int
    priority: Priority = Priority.MEDIUM
    category: Category = Category.OTHER
    # Soft preference: try this time first, else fall back to the earliest free gap.
    preferred_start: time | None = None
    # Hard requirement: wins over preferred_start when both are set.
    fixed_time: time | None = None
    recurrence: Recurrence = Recurrence.ONCE
    required: bool = False
    # Free-text details about the activity (e.g. "half a pill, hidden in cheese").
    # `title` is the short name shown in plans; this is optional extra detail.
    description: str = ""
    # First day the task applies. For ONCE it is the due date; for WEEKLY it also
    # fixes the weekday the task falls on.
    start_date: date = field(default_factory=date.today)
    # Most recent day the task was completed (None = never). Replaces a single
    # `completed` flag, which cannot work for tasks that recur.
    last_completed: date | None = None
    # Unique identity: two tasks with identical fields are still different tasks,
    # so Pet edits and removals look tasks up by this id.
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        """Convert a string priority and reject an empty title or non-positive duration."""
        if isinstance(self.priority, str):  # tolerate raw UI input
            self.priority = Priority.from_str(self.priority)
        if not self.title.strip():
            raise ValueError("task title must not be empty")
        if self.duration_minutes <= 0:
            raise ValueError(f"duration_minutes must be positive, got {self.duration_minutes}")

    def is_due(self, on: date) -> bool:
        """Whether the task applies on `on`.

        - never due before `start_date`
        - ONCE: due until completed (an overdue one stays due)
        - DAILY: due every day, unless already completed on `on`
        - WEEKLY: due on the weekday of `start_date`, unless already completed on `on`
        """
        if on < self.start_date or self.is_completed(on):
            return False
        if self.recurrence is Recurrence.WEEKLY:
            return on.weekday() == self.start_date.weekday()
        return True

    def is_completed(self, on: date) -> bool:
        """Completion status as of `on`. A ONCE task stays completed forever; a
        recurring task counts as completed only for the day it was done, so it
        becomes open again the next time it falls due."""
        if self.last_completed is None:
            return False
        return self.recurrence is Recurrence.ONCE or self.last_completed == on

    def mark_complete(self, on: date) -> None:
        """Record completion on `on` (sets `last_completed`)."""
        self.last_completed = on


# Fields Pet.edit_task may change; `id` is deliberately excluded.
EDITABLE_TASK_FIELDS = frozenset(
    {
        "title",
        "description",
        "duration_minutes",
        "priority",
        "category",
        "preferred_start",
        "fixed_time",
        "recurrence",
        "required",
        "start_date",
        "last_completed",
    }
)


@dataclass
class Pet:
    name: str
    species: str
    breed: str = ""
    age: int | None = None
    special_needs: str = ""
    tasks: list[Task] = field(default_factory=list)
    # Two pets can share a name and species, so removal is by id.
    id: str = field(default_factory=_new_id)

    def _index_of(self, task_id: str) -> int:
        """Position of the task with `task_id`; raises KeyError if this pet has no such task."""
        for i, task in enumerate(self.tasks):
            if task.id == task_id:
                return i
        raise KeyError(f"no task with id {task_id!r} on pet {self.name!r}")

    def add_task(self, task: Task) -> None:
        """Append `task`; reject a task whose id is already on this pet."""
        if any(existing.id == task.id for existing in self.tasks):
            raise ValueError(f"task id {task.id!r} is already on pet {self.name!r}")
        self.tasks.append(task)

    def edit_task(self, task_id: str, **changes) -> None:
        """Change fields of the task with `task_id`, keeping the same Task object.

        Only keys in EDITABLE_TASK_FIELDS are allowed (unknown keys raise). The
        change is validated by building a replaced copy first (which re-runs
        `Task.__post_init__`), and only then copied onto the live task, so a bad
        edit leaves the task untouched.
        """
        task = self.tasks[self._index_of(task_id)]
        unknown = set(changes) - EDITABLE_TASK_FIELDS
        if unknown:
            raise ValueError(f"cannot edit field(s): {', '.join(sorted(unknown))}")
        validated = dataclasses.replace(task, **changes)
        for name in changes:
            setattr(task, name, getattr(validated, name))

    def remove_task(self, task_id: str) -> None:
        """Remove the task with `task_id`; raises KeyError if this pet has no such task."""
        del self.tasks[self._index_of(task_id)]

    def get_tasks(self) -> list[Task]:
        """A copy of the task list (the Task objects themselves are shared)."""
        return list(self.tasks)


@dataclass
class Owner:
    name: str
    # The window [day_start, day_end] is the source of truth for when care can happen.
    day_start: time = time(8, 0)
    day_end: time = time(20, 0)
    # Optional extra cap on total care minutes per day (None = no cap beyond the
    # window). The scheduler uses whichever limit is tighter.
    available_minutes: int | None = None
    # Per-category default start, e.g. {Category.WALK: time(7, 30)}. Used as the
    # preferred_start of tasks in that category that do not set their own.
    preferred_times: dict[Category, time] = field(default_factory=dict)
    pets: list[Pet] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Reject an invalid availability window or minutes cap at construction."""
        self._validate_availability(self.day_start, self.day_end, self.available_minutes)

    @staticmethod
    def _validate_availability(start: time, end: time, cap: int | None) -> None:
        """Raise ValueError unless `end` is after `start` and `cap` is None or positive."""
        if to_minutes(end) <= to_minutes(start):
            raise ValueError("day_end must be after day_start (overnight windows are not supported)")
        if cap is not None and cap <= 0:
            raise ValueError(f"available_minutes must be positive or None, got {cap}")

    def add_pet(self, pet: Pet) -> None:
        """Append `pet`; reject a pet whose id is already on this owner."""
        if any(existing.id == pet.id for existing in self.pets):
            raise ValueError(f"pet id {pet.id!r} is already on owner {self.name!r}")
        self.pets.append(pet)

    def remove_pet(self, pet_id: str) -> None:
        """Remove the pet with `pet_id`; raises KeyError if this owner has no such pet."""
        for i, pet in enumerate(self.pets):
            if pet.id == pet_id:
                del self.pets[i]
                return
        raise KeyError(f"no pet with id {pet_id!r} on owner {self.name!r}")

    def set_availability(self, start: time, end: time) -> None:
        """Replace the window, validating first so a bad window changes nothing."""
        self._validate_availability(start, end, self.available_minutes)
        self.day_start, self.day_end = start, end

    def get_all_tasks(self) -> list["PetTask"]:
        """Every pet's tasks together, each paired with the pet it belongs to.

        This is the single way the Scheduler reads tasks, so it never looks at one
        pet in isolation. It is one pass over the pets' own task lists, built fresh
        on every call: nothing is cached, so there is no stale index to keep in sync
        when tasks are added, edited or removed, and the pairs hold the live Task
        objects (completing one is visible everywhere).
        """
        return [PetTask(pet, task) for pet in self.pets for task in pet.tasks]


@dataclass
class PetTask:
    """A task together with the pet it belongs to.

    A Task does not point back to its Pet (a back-reference would make the
    dataclass repr/eq recurse forever), so code that needs both passes this pair.
    """

    pet: Pet
    task: Task


@dataclass
class ScheduledItem:
    task: Task
    pet: Pet
    start: time
    end: time
    reason: str = ""

    def __post_init__(self) -> None:
        """Reject an item that does not end after it starts."""
        if to_minutes(self.end) <= to_minutes(self.start):
            raise ValueError("a scheduled item must end after it starts")

    def duration(self) -> int:
        """Length in minutes."""
        return to_minutes(self.end) - to_minutes(self.start)

    def overlaps(self, other: "ScheduledItem") -> bool:
        """True if the two items share time; back-to-back items do not overlap."""
        return (
            to_minutes(self.start) < to_minutes(other.end)
            and to_minutes(other.start) < to_minutes(self.end)
        )


@dataclass
class SkippedTask:
    task: Task
    pet: Pet
    reason: str
    flagged: bool = False  # True when a required task could not be scheduled


@dataclass
class DailyPlan:
    on: date
    scheduled_items: list[ScheduledItem] = field(default_factory=list)
    skipped_tasks: list[SkippedTask] = field(default_factory=list)
    # Human-readable notices for the UI: fixed-time clashes, flagged required tasks.
    warnings: list[str] = field(default_factory=list)

    def total_minutes(self) -> int:
        """Total minutes across all scheduled items."""
        return sum(item.duration() for item in self.scheduled_items)

    def flagged_tasks(self) -> list[SkippedTask]:
        """Skipped tasks that were required, i.e. the ones the owner must act on."""
        return [s for s in self.skipped_tasks if s.flagged]

    def summary(self) -> str:
        """One-line count of scheduled, skipped and flagged tasks."""
        text =f"{len(self.scheduled_items)} scheduled ({self.total_minutes()} min), {len(self.skipped_tasks)} skipped"
        flagged = len(self.flagged_tasks())
        return f"{text}, {flagged} required task(s) flagged" if flagged else text

    def explain(self) -> str:
        """The plan as readable text, including why each task was or was not placed."""
        lines = [f"Plan for {self.on.isoformat()}: {self.summary()}"]
        for item in self.scheduled_items:
            lines.append(
                f"  {item.start:%H:%M}-{item.end:%H:%M}  {item.task.title} ({item.pet.name}) - {item.reason}"
            )
        if self.skipped_tasks:
            lines.append("Not scheduled:")
            for s in self.skipped_tasks:
                lines.append(f"  {s.task.title} ({s.pet.name}) - {s.reason}")
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"  ! {w}" for w in self.warnings)
        return "\n".join(lines)

    def to_table(self) -> list[dict]:
        """Rows for `st.table`: scheduled items in time order, then skipped tasks."""
        rows = [
            {
                "status": "scheduled",
                "start": f"{item.start:%H:%M}",
                "end": f"{item.end:%H:%M}",
                "pet": item.pet.name,
                "task": item.task.title,
                "minutes": item.duration(),
                "priority": item.task.priority.name.lower(),
                "reason": item.reason,
            }
            for item in self.scheduled_items
        ]
        rows.extend(
            {
                "status": "FLAGGED" if s.flagged else "skipped",
                "start": "",
                "end": "",
                "pet": s.pet.name,
                "task": s.task.title,
                "minutes": s.task.duration_minutes,
                "priority": s.task.priority.name.lower(),
                "reason": s.reason,
            }
            for s in self.skipped_tasks
        )
        return rows


def _fits_at(free: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(a <= start and end <= b for a, b in free)


def _find_gap(free: list[tuple[int, int]], length: int) -> int | None:
    """Start of the earliest free interval at least `length` long, else None."""
    return next((a for a, b in free if b - a >= length), None)


def _carve(free: list[tuple[int, int]], start: int, end: int) -> list[tuple[int, int]]:
    """Remove [start, end) from the free intervals; it must lie inside one of them."""
    result = []
    for a, b in free:
        if a <= start and end <= b:
            if a < start:
                result.append((a, start))
            if end < b:
                result.append((end, b))
        else:
            result.append((a, b))
    return result


class Scheduler:
    """Builds a DailyPlan for one owner.

    Planning rules (the contract the implementation and tests follow):
    - The owner is a single resource: tasks never overlap, even across pets.
    - Sort key: required first, then higher priority, then shorter duration.
    - `available_minutes`, if set, caps total scheduled minutes. Admission under
      the cap is decided in sort order before placement, so required and
      high-priority tasks claim the minutes first. (A task admitted but then
      unplaceable does not hand its minutes back; that is the cost of the rule.)
    - Fixed-time tasks are placed first, so a flexible task cannot take their slot.
      If two fixed-time tasks clash, the earlier in sort order is kept; the other
      is skipped with a reason, and flagged (plus a plan warning) if it is required.
    - Flexible tasks go into the free intervals left in the window. Free time is
      tracked as a list of intervals, not a single total, because fragmented time
      can fit less than its sum. A task is placed at its preferred time when that
      interval is free, otherwise in the earliest gap that fits.
    - A task that does not fit is skipped, not a stop signal: later, shorter tasks
      are still tried. Required tasks are never bumped to make room for others.
    - Every scheduled or skipped task carries a human-readable reason.
    """

    def __init__(self, owner: Owner):
        """Plan for `owner`; the owner is read on every call, so later changes are seen."""
        self.owner = owner

    def generate_plan(self, on: date) -> DailyPlan:
        """filter_due_tasks -> sort_tasks -> fit_to_available_time -> DailyPlan."""
        ordered = self.sort_tasks(self.filter_due_tasks(on))
        items, skipped = self.fit_to_available_time(ordered)
        warnings = []
        for s in skipped:
            if s.flagged:
                warnings.append(f"REQUIRED task '{s.task.title}' for {s.pet.name} was not scheduled. {s.reason}")
            elif s.task.fixed_time is not None:
                warnings.append(
                    f"'{s.task.title}' for {s.pet.name} could not be placed at its fixed time "
                    f"{s.task.fixed_time:%H:%M}. {s.reason}"
                )
        return DailyPlan(on, items, skipped, warnings)

    def filter_due_tasks(self, on: date) -> list[PetTask]:
        """Due tasks across all pets, read through `Owner.get_all_tasks`."""
        return [pt for pt in self.owner.get_all_tasks() if pt.task.is_due(on)]

    def sort_tasks(self, tasks: list[PetTask]) -> list[PetTask]:
        """Required first, then higher priority, then shorter. Stable, so ties keep
        the owner's pet order and each pet's task order."""
        return sorted(
            tasks,
            key=lambda pt: (not pt.task.required, -pt.task.priority.value, pt.task.duration_minutes),
        )

    def fit_to_available_time(
        self, tasks: list[PetTask]
    ) -> tuple[list[ScheduledItem], list[SkippedTask]]:
        """Place `tasks` on the clock. `tasks` must already be in `sort_tasks`
        order: that order decides who wins a clash or a scarce gap. Returns the
        scheduled items in time order and the skipped tasks in sort order."""
        owner = self.owner
        win_start, win_end = to_minutes(owner.day_start), to_minutes(owner.day_end)
        free = [(win_start, win_end)]
        items: list[ScheduledItem] = []
        skipped: list[tuple[int, SkippedTask]] = []

        def skip(idx: int, pt: PetTask, detail: str) -> None:
            reason = self._build_reason(pt, False, detail)
            skipped.append((idx, SkippedTask(pt.task, pt.pet, reason, flagged=pt.task.required)))

        def place(pt: PetTask, start: int, detail: str) -> None:
            nonlocal free
            end = start + pt.task.duration_minutes
            reason = self._build_reason(pt, True, f"{detail}, {_fmt(start)}-{_fmt(end)}")
            items.append(ScheduledItem(pt.task, pt.pet, from_minutes(start), from_minutes(end), reason))
            free = _carve(free, start, end)

        # Admission under the daily minutes cap, in sort order.
        cap_left = math.inf if owner.available_minutes is None else owner.available_minutes
        admitted: list[tuple[int, PetTask]] = []
        for idx, pt in enumerate(tasks):
            if pt.task.duration_minutes <= cap_left:
                cap_left -= pt.task.duration_minutes
                admitted.append((idx, pt))
            else:
                skip(idx, pt, f"adding {pt.task.duration_minutes} min would exceed the "
                              f"{owner.available_minutes}-minute daily limit")

        # Phase 1: fixed-time tasks.
        for idx, pt in admitted:
            if pt.task.fixed_time is None:
                continue
            start = to_minutes(pt.task.fixed_time)
            end = start + pt.task.duration_minutes
            if _fits_at(free, start, end):
                place(pt, start, "at its fixed time")
            elif start < win_start or end > win_end:
                skip(idx, pt, f"fixed time {_fmt(start)}-{_fmt(end)} is outside the available "
                              f"window {_fmt(win_start)}-{_fmt(win_end)}")
            else:
                clash = next((i for i in items if to_minutes(i.start) < end and start < to_minutes(i.end)), None)
                with_what = (f"'{clash.task.title}' ({clash.pet.name}) at {clash.start:%H:%M}-{clash.end:%H:%M}"
                             if clash else "another task")
                skip(idx, pt, f"fixed time {_fmt(start)}-{_fmt(end)} clashes with {with_what}")

        # Phase 2: flexible tasks into the remaining free intervals.
        for idx, pt in admitted:
            if pt.task.fixed_time is not None:
                continue
            length = pt.task.duration_minutes
            preferred = pt.task.preferred_start
            if preferred is None:
                preferred = owner.preferred_times.get(pt.task.category)
            if preferred is not None and _fits_at(free, to_minutes(preferred), to_minutes(preferred) + length):
                place(pt, to_minutes(preferred), "at its preferred time")
                continue
            start = _find_gap(free, length)
            if start is None:
                largest = max((b - a for a, b in free), default=0)
                skip(idx, pt, f"no free gap of {length} min left (largest gap: {largest} min)")
            else:
                note = "earliest free slot (preferred time unavailable)" if preferred is not None else "earliest free slot"
                place(pt, start, note)

        items.sort(key=lambda i: to_minutes(i.start))
        skipped.sort(key=lambda pair: pair[0])
        return items, [s for _, s in skipped]

    def detect_conflicts(self, items: list[ScheduledItem]) -> list[tuple[ScheduledItem, ScheduledItem]]:
        """Return overlapping pairs. Empty for any plan the scheduler generates
        (clashes are resolved during placement and reported via DailyPlan.warnings),
        so this doubles as an invariant check in tests."""
        ordered = sorted(items, key=lambda i: to_minutes(i.start))
        conflicts = []
        for i, first in enumerate(ordered):
            for second in ordered[i + 1:]:
                if to_minutes(second.start) >= to_minutes(first.end):
                    break  # sorted by start, so nothing later can overlap `first`
                conflicts.append((first, second))
        return conflicts

    def _build_reason(self, pet_task: PetTask, placed: bool, detail: str) -> str:
        """Single place that words scheduled/skipped reasons for `fit_to_available_time`."""
        task = pet_task.task
        tags = ", ".join(filter(None, ["required" if task.required else "", f"{task.priority.name.lower()} priority"]))
        return f"{'Scheduled' if placed else 'Skipped'} ({tags}): {detail}"

"""PawPal+ core domain classes and the daily scheduler.

Data classes validate their own invariants. All time math is done in whole
minutes since midnight (see `to_minutes`) because `datetime.time` has no
arithmetic.
"""

import dataclasses
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import Enum
from pathlib import Path
from typing import TypeVar
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


# Version of the data.json layout; bump it if the layout changes so old files are rejected clearly.
DATA_VERSION = 1


def _iso(value: date | time | None) -> str | None:
    """A date or time as ISO text for JSON (None stays None)."""
    return None if value is None else value.isoformat()


def _parse(parser, text):
    """Apply `parser` (such as date.fromisoformat) to ISO text, passing None through."""
    return None if text is None else parser(text)


def _describe(err: Exception) -> str:
    """A short readable reason for a data error (a bare KeyError would just say 'title')."""
    return f"missing field {err.args[0]!r}" if isinstance(err, KeyError) else str(err)


E = TypeVar("E", bound=Enum)


def _enum_by_name(enum_cls: type[E], name: str) -> E:
    """Look up a member of `enum_cls` by name, with a readable error for bad data.

    Generic, so a type checker knows `_enum_by_name(Priority, ...)` is a `Priority`, not just an `Enum`."""
    try:
        return enum_cls[name]
    except KeyError:
        raise ValueError(f"unknown {enum_cls.__name__} {name!r}") from None


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


# Gap between consecutive occurrences of a recurring task (ONCE has none).
_RECURRENCE_STEP = {Recurrence.DAILY: timedelta(days=1), Recurrence.WEEKLY: timedelta(weeks=1)}


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
    # Day this occurrence becomes due. It stays due until completed. A recurring task
    # (DAILY/WEEKLY) gets a new occurrence with a later start_date when completed.
    start_date: date = field(default_factory=date.today)
    # Day this occurrence was completed (None = still open).
    completed_on: date | None = None
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

    @property
    def requested_time(self) -> time | None:
        """The time of day the owner asked for: `fixed_time`, else `preferred_start`, else None."""
        return self.fixed_time if self.fixed_time is not None else self.preferred_start

    def is_due(self, on: date) -> bool:
        """Whether the task still needs doing on `on`: it has started and is not completed.

        An overdue task stays due until it is completed. A recurring task is not "due every
        day": completing it creates the next occurrence (see `mark_complete`), so at most one
        open occurrence of a series exists at a time.
        """
        return self.completed_on is None and on >= self.start_date

    def is_completed(self) -> bool:
        """True once this occurrence has been marked complete."""
        return self.completed_on is not None

    def next_due_date(self, on: date) -> date | None:
        """Due date of the next occurrence after completing on `on`; None for a ONCE task.

        Occurrences stay on the task's own schedule (`start_date` plus whole steps of one day
        or one week), so a weekly Monday task finished late on Wednesday is next due the
        following Monday, not 7 days after Wednesday. Finished on its due day, this is simply
        `on + timedelta(days=1)` (daily) or `on + timedelta(weeks=1)` (weekly).
        """
        step = _RECURRENCE_STEP.get(self.recurrence)
        if step is None:
            return None
        elapsed = (max(on, self.start_date) - self.start_date) // step  # whole steps already passed
        return self.start_date + (elapsed + 1) * step

    def mark_complete(self, on: date) -> "Task | None":
        """Mark this occurrence complete on `on`; return the new next occurrence, or None.

        A daily or weekly task returns a fresh copy (new id, due on `next_due_date`) that the
        caller must add to the pet; `Pet.complete_task` does this. A ONCE task, or one that is
        already complete, returns None, so completing twice never creates a duplicate.
        """
        if self.is_completed():
            return None
        self.completed_on = on
        next_due = self.next_due_date(on)
        if next_due is None:
            return None
        return dataclasses.replace(self, id=_new_id(), start_date=next_due, completed_on=None)

    def to_dict(self) -> dict:
        """The task as plain JSON-safe data: enums by name, times and dates as ISO text."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "duration_minutes": self.duration_minutes,
            "priority": self.priority.name,
            "category": self.category.name,
            "recurrence": self.recurrence.name,
            "required": self.required,
            "preferred_start": _iso(self.preferred_start),
            "fixed_time": _iso(self.fixed_time),
            "start_date": self.start_date.isoformat(),
            "completed_on": _iso(self.completed_on),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Rebuild a task from `to_dict` data. It goes through the constructor, so all validation
        runs again; any problem is raised as a ValueError that names the task."""
        try:
            return cls(
                title=data["title"],
                duration_minutes=data["duration_minutes"],
                priority=_enum_by_name(Priority, data.get("priority", "MEDIUM")),
                category=_enum_by_name(Category, data.get("category", "OTHER")),
                preferred_start=_parse(time.fromisoformat, data.get("preferred_start")),
                fixed_time=_parse(time.fromisoformat, data.get("fixed_time")),
                recurrence=_enum_by_name(Recurrence, data.get("recurrence", "ONCE")),
                required=bool(data.get("required", False)),
                description=data.get("description", ""),
                start_date=date.fromisoformat(data["start_date"]),
                completed_on=_parse(date.fromisoformat, data.get("completed_on")),
                id=data.get("id") or _new_id(),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise ValueError(f"invalid task {data.get('title')!r}: {_describe(err)}") from err


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
        "completed_on",
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

    def __post_init__(self) -> None:
        """Reject an empty name or species and a negative age."""
        if not self.name.strip():
            raise ValueError("pet name must not be empty")
        if not self.species.strip():
            raise ValueError("pet species must not be empty")
        if self.age is not None and self.age < 0:
            raise ValueError(f"pet age must not be negative, got {self.age}")

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

    def complete_task(self, task_id: str, on: date) -> Task | None:
        """Complete the task with `task_id` on `on`; add and return its next occurrence, if any."""
        next_task = self.tasks[self._index_of(task_id)].mark_complete(on)
        if next_task is not None:
            self.tasks.append(next_task)
        return next_task

    def get_tasks(self) -> list[Task]:
        """A copy of the task list (the Task objects themselves are shared)."""
        return list(self.tasks)

    def to_dict(self) -> dict:
        """The pet and all its tasks as plain JSON-safe data."""
        return {
            "id": self.id,
            "name": self.name,
            "species": self.species,
            "breed": self.breed,
            "age": self.age,
            "special_needs": self.special_needs,
            "tasks": [task.to_dict() for task in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Pet":
        """Rebuild a pet and its tasks from `to_dict` data (validated; ValueError on bad data)."""
        try:
            pet = cls(
                name=data["name"],
                species=data["species"],
                breed=data.get("breed", ""),
                age=data.get("age"),
                special_needs=data.get("special_needs", ""),
                id=data.get("id") or _new_id(),
            )
            for task_data in data.get("tasks", []):
                pet.add_task(Task.from_dict(task_data))  # add_task also rejects duplicate ids
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise ValueError(f"invalid pet {data.get('name')!r}: {_describe(err)}") from err
        return pet


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
        """Reject an empty name or an invalid availability window or minutes cap at construction."""
        if not self.name.strip():
            raise ValueError("owner name must not be empty")
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

    def set_availability(self, start: time, end: time, available_minutes: int | None = None) -> None:
        """Replace the window and the optional minutes cap (None = no cap), validating
        first so bad input changes nothing."""
        self._validate_availability(start, end, available_minutes)
        self.day_start, self.day_end, self.available_minutes = start, end, available_minutes

    def capacity_minutes(self) -> int:
        """Care minutes available per day: the window length, or the cap if that is smaller."""
        window = to_minutes(self.day_end) - to_minutes(self.day_start)
        return window if self.available_minutes is None else min(window, self.available_minutes)

    def get_all_tasks(self) -> list["PetTask"]:
        """Every pet's tasks together, each paired with the pet it belongs to.

        This is the single way the Scheduler reads tasks, so it never looks at one
        pet in isolation. It is one pass over the pets' own task lists, built fresh
        on every call: nothing is cached, so there is no stale index to keep in sync
        when tasks are added, edited or removed, and the pairs hold the live Task
        objects (completing one is visible everywhere).
        """
        return [PetTask(pet, task) for pet in self.pets for task in pet.tasks]

    def to_dict(self) -> dict:
        """The owner, their settings, and every pet with its tasks, as plain JSON-safe data."""
        return {
            "name": self.name,
            "day_start": self.day_start.isoformat(),
            "day_end": self.day_end.isoformat(),
            "available_minutes": self.available_minutes,
            "preferred_times": {category.name: t.isoformat() for category, t in self.preferred_times.items()},
            "pets": [pet.to_dict() for pet in self.pets],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Owner":
        """Rebuild an owner from `to_dict` data. The constructor validates the window and name, and
        pets and tasks are re-validated as they are added, so bad data raises a ValueError."""
        try:
            owner = cls(
                name=data["name"],
                day_start=time.fromisoformat(data["day_start"]),
                day_end=time.fromisoformat(data["day_end"]),
                available_minutes=data.get("available_minutes"),
                preferred_times={_enum_by_name(Category, name): time.fromisoformat(text)
                                 for name, text in data.get("preferred_times", {}).items()},
            )
            for pet_data in data.get("pets", []):
                owner.add_pet(Pet.from_dict(pet_data))  # add_pet also rejects duplicate ids
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise ValueError(f"invalid owner data: {_describe(err)}") from err
        return owner

    def save_to_json(self, path: str | os.PathLike = "data.json") -> None:
        """Save the owner, pets and tasks to a JSON file so they survive between runs.

        The file is written to a temporary name and then moved over the real one, so a crash or a
        full disk during the write can never leave a half-written data file behind."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"version": DATA_VERSION, "owner": self.to_dict()}, indent=2, ensure_ascii=False) + "\n"
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load_from_json(cls, path: str | os.PathLike = "data.json") -> "Owner":
        """Load an owner saved by `save_to_json`.

        A missing file raises FileNotFoundError (callers usually treat that as "first run").
        Anything wrong with the contents (not JSON, the wrong version, a missing field, a value the
        classes reject) raises a ValueError with a readable reason, and nothing is half-loaded."""
        text = Path(path).read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as err:
            raise ValueError(f"{Path(path).name} is not valid JSON: {err}") from err
        if not isinstance(payload, dict) or payload.get("version") != DATA_VERSION:
            raise ValueError(f"{Path(path).name} is not a PawPal+ data file (expected version {DATA_VERSION})")
        if not isinstance(payload.get("owner"), dict):
            raise ValueError(f"{Path(path).name} has no owner data")
        return cls.from_dict(payload["owner"])


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


T = TypeVar("T")


def _overlapping_pairs(spans: list[tuple[int, int, T]]) -> list[tuple[tuple[int, int, T], tuple[int, int, T]]]:
    """Every pair of overlapping spans, the earlier-starting one first.

    A span is `(start minute, end minute, item)`. `spans` must be sorted by start, and each
    must be longer than zero. Because they are
    sorted, a span can only overlap the later spans that start before it ends, so the inner
    loop stops at the first one that does not. That makes the work proportional to the number
    of spans plus the number of overlaps, instead of comparing every pair. Spans that merely
    touch do not overlap.
    """
    pairs = []
    for i, first in enumerate(spans):
        for j in range(i + 1, len(spans)):
            if spans[j][0] >= first[1]:  # starts at or after `first` ends, and so does everything later
                break
            pairs.append((first, spans[j]))
    return pairs


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

    def sort_by_time(self, tasks: list[PetTask]) -> list[PetTask]:
        """Order tasks by the time of day they ask for, earliest first; tasks with no time go last.

        The key is a lambda returning a tuple: the requested time, with `time.max` standing in
        for "no time" so that such tasks sort last without ever comparing a time with None, then
        higher priority, then title ignoring case, which makes the order predictable. Times are `datetime.time`
        values, which compare correctly as they are; zero-padded "HH:MM" strings would sort the
        same way, but a string like "9:30" would not. Returns a new list and leaves `tasks` unchanged.
        """
        return sorted(
            tasks,
            key=lambda pt: (pt.task.requested_time or time.max, -pt.task.priority.value, pt.task.title.casefold()),
        )

    def filter_tasks(
        self,
        tasks: list[PetTask] | None = None,
        *,
        pet_name: str | None = None,
        completed: bool | None = None,
    ) -> list[PetTask]:
        """Keep tasks for one pet and/or with one completion status; `None` means "any".

        `pet_name` is matched ignoring case. `completed=True` keeps finished tasks and
        `completed=False` keeps open ones. With no `tasks` given it starts from every pet's
        tasks, read through `Owner.get_all_tasks`. An unknown pet name gives an empty list.
        """
        pairs = self.owner.get_all_tasks() if tasks is None else tasks
        wanted = None if pet_name is None else pet_name.strip().lower()
        return [
            pt for pt in pairs
            if (wanted is None or pt.pet.name.lower() == wanted)
            and (completed is None or pt.task.is_completed() == completed)
        ]

    def mark_task_complete(self, task_id: str, on: date) -> Task | None:
        """Complete the task with `task_id` on `on`, wherever it lives, and return its next occurrence.

        Finds the owning pet by reading through `Owner.get_all_tasks`, then lets `Pet.complete_task`
        record the completion and add the new occurrence of a daily or weekly task (None otherwise).
        Raises KeyError if no pet has that task.
        """
        for pt in self.owner.get_all_tasks():
            if pt.task.id == task_id:
                return pt.pet.complete_task(task_id, on)
        raise KeyError(f"no task with id {task_id!r} on any pet")

    def find_conflicts(self, on: date) -> list[str]:
        """Warn about due tasks whose fixed times overlap, for the same pet or different pets.

        A lightweight check that returns plain warning messages and never raises or changes
        anything. It compares due tasks that have a `fixed_time`, because only those have a
        committed slot, and it uses duration: two tasks conflict when their time ranges
        overlap, not only when they start in the same minute. Flexible tasks are skipped
        because the planner moves them around; `generate_plan` also resolves fixed-time clashes
        when it builds the plan, and these warnings let the owner see them before that.
        The pair search is the shared early-exit sweep in `_overlapping_pairs`.
        """
        spans: list[tuple[int, int, PetTask]] = []
        for pt in self.filter_due_tasks(on):
            if pt.task.fixed_time is not None:
                start = to_minutes(pt.task.fixed_time)
                spans.append((start, start + pt.task.duration_minutes, pt))
        spans.sort(key=lambda span: (span[0], span[2].task.title))

        warnings = []
        for (a_start, a_end, a), (b_start, b_end, b) in _overlapping_pairs(spans):
            scope = "same pet" if a.pet.id == b.pet.id else "different pets"
            warnings.append(
                f"Conflict ({scope}): '{a.task.title}' ({a.pet.name}, {_fmt(a_start)}-{_fmt(a_end)}) "
                f"overlaps '{b.task.title}' ({b.pet.name}, {_fmt(b_start)}-{_fmt(b_end)})"
            )
        return warnings

    def next_available_slot(
        self, on: date, minutes: int, not_before: time | None = None
    ) -> tuple[time, time] | None:
        """The earliest free slot of `minutes` on `on`, as `(start, end)`, or None if there is none.

        "Free" means free in the plan as it stands: the day window minus every task that plan
        schedules, so a new task placed in the slot cannot clash with or move anything. The scan
        goes through the free gaps in time order and takes the first one that is long enough, so
        it finds the earliest slot, not just a slot. `not_before` skips anything earlier (a slot
        may start part-way into a gap). The daily limit counts: if scheduling `minutes` more would
        go over `available_minutes`, there is no slot. A slot may end exactly when the day ends.
        """
        if minutes <= 0:
            raise ValueError(f"minutes must be positive, got {minutes}")
        plan = self.generate_plan(on)
        cap = self.owner.available_minutes
        if cap is not None and plan.total_minutes() + minutes > cap:
            return None
        window_start = to_minutes(self.owner.day_start)
        earliest = window_start if not_before is None else max(window_start, to_minutes(not_before))
        free = [(window_start, to_minutes(self.owner.day_end))]
        for item in plan.scheduled_items:
            free = _carve(free, to_minutes(item.start), to_minutes(item.end))
        for gap_start, gap_end in free:
            start = max(gap_start, earliest)
            if gap_end - start >= minutes:
                return from_minutes(start), from_minutes(start + minutes)
        return None

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
        so this doubles as an invariant check in tests.

        Sorts by start time once, then uses the early-exit sweep in `_overlapping_pairs`: the
        cost is about O(n log n) for the sort plus the number of overlaps found, so a plan with
        no conflicts is checked in a single pass."""
        spans = sorted(((to_minutes(i.start), to_minutes(i.end), i) for i in items), key=lambda span: span[0])
        return [(a, b) for (_, _, a), (_, _, b) in _overlapping_pairs(spans)]

    def _build_reason(self, pet_task: PetTask, placed: bool, detail: str) -> str:
        """Single place that words scheduled/skipped reasons for `fit_to_available_time`."""
        task = pet_task.task
        tags = ", ".join(filter(None, ["required" if task.required else "", f"{task.priority.name.lower()} priority"]))
        return f"{'Scheduled' if placed else 'Skipped'} ({tags}): {detail}"

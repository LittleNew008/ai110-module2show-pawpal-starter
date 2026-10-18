"""PawPal+ core domain classes. Stubs only: no scheduling logic yet."""

from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum
from uuid import uuid4


class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


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
    preferred_start: time | None = None
    fixed_time: time | None = None
    recurrence: Recurrence = Recurrence.ONCE
    required: bool = False
    completed: bool = False
    # Unique identity: two tasks with identical fields are still different tasks,
    # so Pet edits and removals look tasks up by this id.
    id: str = field(default_factory=lambda: uuid4().hex)

    def is_due(self, on: date) -> bool:
        raise NotImplementedError

    def mark_complete(self) -> None:
        raise NotImplementedError

    def priority_score(self) -> int:
        raise NotImplementedError


@dataclass
class Pet:
    name: str
    species: str
    breed: str = ""
    age: int | None = None
    special_needs: str = ""
    tasks: list[Task] = field(default_factory=list)

    def add_task(self, task: Task) -> None:
        raise NotImplementedError

    def edit_task(self, task_id: str, **changes) -> None:
        raise NotImplementedError

    def remove_task(self, task_id: str) -> None:
        raise NotImplementedError

    def get_tasks(self) -> list[Task]:
        raise NotImplementedError


@dataclass
class Owner:
    name: str
    # The window [day_start, day_end] is the source of truth for when care can happen.
    day_start: time = time(8, 0)
    day_end: time = time(20, 0)
    # Optional extra cap on total care minutes per day (None = no cap beyond the
    # window). The scheduler uses whichever limit is tighter.
    available_minutes: int | None = None
    preferences: dict = field(default_factory=dict)
    pets: list[Pet] = field(default_factory=list)

    def add_pet(self, pet: Pet) -> None:
        raise NotImplementedError

    def remove_pet(self, pet: Pet) -> None:
        raise NotImplementedError

    def set_availability(self, start: time, end: time) -> None:
        raise NotImplementedError

    def get_all_tasks(self) -> list[tuple[Pet, Task]]:
        raise NotImplementedError


@dataclass
class ScheduledItem:
    task: Task
    pet: Pet
    start: time
    end: time
    reason: str = ""

    def duration(self) -> int:
        raise NotImplementedError

    def overlaps(self, other: "ScheduledItem") -> bool:
        raise NotImplementedError


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

    def total_minutes(self) -> int:
        raise NotImplementedError

    def flagged_tasks(self) -> list[SkippedTask]:
        raise NotImplementedError

    def summary(self) -> str:
        raise NotImplementedError

    def explain(self) -> str:
        raise NotImplementedError

    def to_table(self) -> list[dict]:
        raise NotImplementedError


class Scheduler:
    def __init__(self, owner: Owner):
        self.owner = owner

    def generate_plan(self, on: date) -> DailyPlan:
        raise NotImplementedError

    def filter_due_tasks(self, on: date) -> list[tuple[Pet, Task]]:
        raise NotImplementedError

    def sort_tasks(self, tasks: list[tuple[Pet, Task]]) -> list[tuple[Pet, Task]]:
        raise NotImplementedError

    def fit_to_available_time(
        self, tasks: list[tuple[Pet, Task]]
    ) -> tuple[list[ScheduledItem], list[SkippedTask]]:
        raise NotImplementedError

    def detect_conflicts(self, items: list[ScheduledItem]) -> list[tuple[ScheduledItem, ScheduledItem]]:
        raise NotImplementedError

    def explain_choice(self, task: Task, scheduled: bool) -> str:
        raise NotImplementedError

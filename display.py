"""Presentation helpers shared by the Streamlit app and the command-line demo.

They turn the scheduler's objects into friendly text: an emoji for each kind of task and pet,
colour-coded priority and status badges, and table rows. There is no scheduling logic here.

Every emoji used is a single code point that is two terminal cells wide, so `tabulate` tables stay
aligned (emoji that carry an invisible variation selector, such as the warning sign, do not, and
`tests/test_display.py` checks this for every symbol below).
"""

from datetime import date

from tabulate import tabulate

from pawpal_system import Category, DailyPlan, PetTask, Pet, Priority, Recurrence, Task

CATEGORY_ICONS = {
    Category.WALK: "🐕",
    Category.FEEDING: "🍖",
    Category.MEDS: "💊",
    Category.ENRICHMENT: "🎾",
    Category.GROOMING: "🛁",
    Category.OTHER: "📌",
}
SPECIES_ICONS = {"dog": "🐶", "cat": "🐱"}
DEFAULT_PET_ICON = "🐾"
PET_HEADING = DEFAULT_PET_ICON  # the paw print used as the app's mark

# Colour-coded: red is the most urgent, green the least.
PRIORITY_BADGES = {Priority.HIGH: "🔴 High", Priority.MEDIUM: "🟡 Medium", Priority.LOW: "🟢 Low"}

STATUS_SCHEDULED = "✅ Scheduled"
STATUS_SKIPPED = "⛔ Not scheduled"
STATUS_FLAGGED = "🚨 Required, not scheduled"

CLASH_ICON = "🚧"
REPEAT_ICON = "🔁"
SAVED_ICON = "💾"
SLOT_ICON = "🕒"
DONE_ICON = "✅"
LATER_ICON = "⏳"
OVERDUE_ICON = "❗"

# Everything above, for the test that checks they all line up in a terminal.
ALL_SYMBOLS = (
    list(CATEGORY_ICONS.values()) + list(SPECIES_ICONS.values()) + [DEFAULT_PET_ICON]
    + [badge.split()[0] for badge in PRIORITY_BADGES.values()]
    + [s.split()[0] for s in (STATUS_SCHEDULED, STATUS_SKIPPED, STATUS_FLAGGED)]
    + [CLASH_ICON, REPEAT_ICON, SAVED_ICON, SLOT_ICON, DONE_ICON, LATER_ICON, OVERDUE_ICON]
)


def pet_icon(species: str) -> str:
    """The emoji for a species (a paw print for anything unknown)."""
    return SPECIES_ICONS.get(species, DEFAULT_PET_ICON)


def pet_label(pet: Pet) -> str:
    """A pet's name with its species emoji, e.g. "🐶 Biscuit"."""
    return f"{pet_icon(pet.species)} {pet.name}"


def category_icon(category: Category) -> str:
    """The emoji for a kind of task, e.g. a pill for medication."""
    return CATEGORY_ICONS[category]


def task_label(task: Task) -> str:
    """A task's title with its category emoji, e.g. "💊 Heart medication"."""
    return f"{category_icon(task.category)} {task.title}"


def priority_badge(priority: Priority) -> str:
    """A colour-coded priority, e.g. "🔴 High"."""
    return PRIORITY_BADGES[priority]


def when_text(task: Task) -> str:
    """When a task asks to happen: "fixed 08:00", "prefers 07:30" or "any time"."""
    if task.fixed_time is not None:
        return f"fixed {task.fixed_time:%H:%M}"
    if task.preferred_start is not None:
        return f"prefers {task.preferred_start:%H:%M}"
    return "any time"


def repeats_text(task: Task) -> str:
    """How often a task repeats: "once", or "🔁 daily" / "🔁 weekly"."""
    if task.recurrence is Recurrence.ONCE:
        return "once"
    return f"{REPEAT_ICON} {task.recurrence.value}"


def task_status(task: Task, today: date) -> str:
    """Where a task stands today, with an emoji: done, starts later, overdue, or due today."""
    if task.is_completed():
        return f"{DONE_ICON} done {task.completed_on:%b %d}"
    if task.start_date > today:
        return f"{LATER_ICON} starts {task.start_date:%b %d}"
    if task.start_date < today:
        return f"{OVERDUE_ICON} overdue since {task.start_date:%b %d}"
    return "due today"


def task_status_markdown(task: Task, today: date) -> str:
    """`task_status` coloured for Streamlit markdown: green when done, blue if later, red if overdue."""
    text = task_status(task, today)
    if task.is_completed():
        return f":green[{text}]"
    if task.start_date > today:
        return f":blue[{text}]"
    if task.start_date < today:
        return f":red[{text}]"
    return text


def task_rows(pairs: list[PetTask], today: date) -> list[dict]:
    """One row per task for a table: what, who, when, how often, how important, and its status."""
    return [
        {
            "Task": task_label(pt.task),
            "Pet": pet_label(pt.pet),
            "When": when_text(pt.task),
            "Repeats": repeats_text(pt.task),
            "Priority": priority_badge(pt.task.priority) + (" ⭐" if pt.task.required else ""),
            "Status": task_status(pt.task, today),
        }
        for pt in pairs
    ]


def schedule_rows(plan: DailyPlan) -> list[dict]:
    """The scheduled part of a plan, in time order, as table rows."""
    return [
        {
            "Status": STATUS_SCHEDULED,
            "Time": f"{item.start:%H:%M}–{item.end:%H:%M}",
            "Pet": pet_label(item.pet),
            "Task": task_label(item.task),
            "Min": item.duration(),
            "Priority": priority_badge(item.task.priority),
            "Why": item.reason,
        }
        for item in plan.scheduled_items
    ]


def not_scheduled_rows(plan: DailyPlan) -> list[dict]:
    """The tasks a plan could not schedule, as table rows; a required task is marked in red."""
    return [
        {
            "Status": STATUS_FLAGGED if skipped.flagged else STATUS_SKIPPED,
            "Pet": pet_label(skipped.pet),
            "Task": task_label(skipped.task),
            "Min": skipped.task.duration_minutes,
            "Priority": priority_badge(skipped.task.priority),
            "Why": skipped.reason,
        }
        for skipped in plan.skipped_tasks
    ]


def render_table(rows: list[dict], wrap_column: str = "Why", wrap_width: int = 44) -> str:
    """Rows as a boxed text table for the terminal (`tabulate`), wrapping one long column.

    Columns line up even with emoji because every symbol here is two cells wide. An empty list
    gives "(none)" instead of an empty box."""
    if not rows:
        return "(none)"
    widths = [wrap_width if header == wrap_column else None for header in rows[0]]
    aligns = ["right" if header == "Min" else "left" for header in rows[0]]
    return tabulate(rows, headers="keys", tablefmt="rounded_outline", disable_numparse=True,
                    maxcolwidths=widths, colalign=aligns)

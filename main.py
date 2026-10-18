"""Demo: build an owner with two pets, then show sorting, filtering, conflict
warnings, today's schedule and recurring tasks in the terminal.

Run from the project root:  python main.py
"""

from datetime import date, time

from pawpal_system import Category, DailyPlan, Owner, Pet, PetTask, Recurrence, Scheduler, Task

RULE = "=" * 72


def build_owner() -> Owner:
    owner = Owner("Jordan", day_start=time(7, 0), day_end=time(20, 0))

    biscuit = Pet("Biscuit", "dog", breed="Golden Retriever", age=4)
    mochi = Pet("Mochi", "cat", breed="Siamese", age=2)

    # Tasks are added deliberately OUT of time order, so the sorting below has work to do.
    biscuit.add_task(Task(
        "Evening fetch", 25, priority="medium", category=Category.ENRICHMENT,
        preferred_start=time(18, 0),
    ))
    biscuit.add_task(Task(
        "Lunch feeding", 10, priority="high", category=Category.FEEDING,
        fixed_time=time(12, 0), recurrence=Recurrence.DAILY,
    ))
    mochi.add_task(Task(
        "Laser-pointer play", 20, priority="medium", category=Category.ENRICHMENT,
        preferred_start=time(15, 30),
    ))
    biscuit.add_task(Task(
        "Heart medication", 5, priority="high", category=Category.MEDS, required=True,
        fixed_time=time(8, 0), recurrence=Recurrence.DAILY,
        description="One pill, hidden in a bit of cheese",
    ))
    mochi.add_task(Task("Flea treatment", 5, priority="low"))  # no time at all
    mochi.add_task(Task(
        "Vet check-in call", 15, priority="medium",
        fixed_time=time(12, 0),  # same time as Biscuit's lunch: a deliberate clash
    ))
    biscuit.add_task(Task(
        "Morning walk", 30, priority="high", category=Category.WALK,
        preferred_start=time(7, 30), recurrence=Recurrence.DAILY,
    ))
    mochi.add_task(Task(
        "Brush fur", 15, priority="low", category=Category.GROOMING,
        preferred_start=time(9, 0), recurrence=Recurrence.WEEKLY,
    ))

    owner.add_pet(biscuit)
    owner.add_pet(mochi)
    return owner


def when(task: Task) -> str:
    """The time a task asks for, as text."""
    if task.fixed_time is not None:
        return f"fixed at {task.fixed_time:%H:%M}"
    if task.preferred_start is not None:
        return f"prefers {task.preferred_start:%H:%M}"
    return "no set time"


def show_tasks(title: str, pairs: list[PetTask]) -> None:
    print(title)
    if not pairs:
        print("  (none)")
    for pt in pairs:
        state = f", done {pt.task.completed_on:%b %d}" if pt.task.is_completed() else f", due {pt.task.start_date:%b %d}"
        print(f"  {pt.task.title} ({pt.pet.name}) - {when(pt.task)}, {pt.task.recurrence.value}{state}")
    print()


def print_schedule(owner: Owner, plan: DailyPlan) -> None:
    print(f"Today's Schedule - {plan.on:%A, %B %d, %Y}")
    print(f"Owner: {owner.name} | Pets: {', '.join(p.name for p in owner.pets)}")
    print(f"Available: {owner.day_start:%H:%M}-{owner.day_end:%H:%M}")
    print(RULE)

    for item in plan.scheduled_items:
        required = " [REQUIRED]" if item.task.required else ""
        print(f"{item.start:%H:%M}-{item.end:%H:%M}  {item.task.title} ({item.pet.name}), "
              f"{item.duration()} min, {item.task.priority.name.lower()} priority{required}")
        if item.task.description:
            print(f"             note: {item.task.description}")
        print(f"             why: {item.reason}")

    if plan.skipped_tasks:
        print("-" * 72)
        print("Not scheduled:")
        for skipped in plan.skipped_tasks:
            print(f"  {skipped.task.title} ({skipped.pet.name}): {skipped.reason}")
    if plan.warnings:
        print("-" * 72)
        for warning in plan.warnings:
            print(f"WARNING: {warning}")

    print(RULE)
    print(plan.summary())


def main() -> None:
    owner = build_owner()
    scheduler = Scheduler(owner)
    today = date.today()

    print(RULE)
    show_tasks("1. Tasks in the order they were added (out of time order):", owner.get_all_tasks())

    show_tasks("2. Sorted by time - Scheduler.sort_by_time():", scheduler.sort_by_time(owner.get_all_tasks()))

    show_tasks("3. Filtered by pet - Scheduler.filter_tasks(pet_name='mochi'):",
               scheduler.filter_tasks(pet_name="mochi"))

    print("4. Conflict warnings - Scheduler.find_conflicts():")
    conflicts = scheduler.find_conflicts(today)
    for message in conflicts or ["No conflicts."]:
        print(f"  {message}")
    print()

    print(RULE)
    print_schedule(owner, scheduler.generate_plan(today))
    print()

    print(RULE)
    print("5. Recurring tasks - Scheduler.mark_task_complete():")
    for pt in scheduler.sort_by_time(owner.get_all_tasks()):
        if pt.task.title in ("Heart medication", "Brush fur", "Flea treatment"):
            next_task = scheduler.mark_task_complete(pt.task.id, today)
            if next_task is None:
                print(f"  {pt.task.title} ({pt.pet.name}) is {pt.task.recurrence.value}: done, nothing new created.")
            else:
                print(f"  {pt.task.title} ({pt.pet.name}) is {pt.task.recurrence.value}: done today, "
                      f"new one due {next_task.start_date:%A, %B %d}.")
    print()
    show_tasks("6. Filtered by status - completed=True:", scheduler.filter_tasks(completed=True))
    show_tasks("   Filtered by status - completed=False (open):",
               scheduler.sort_by_time(scheduler.filter_tasks(completed=False)))


if __name__ == "__main__":
    main()

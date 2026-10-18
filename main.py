"""Demo: build an owner with two pets, then show sorting, filtering, conflict warnings, the next free
slot, today's schedule, recurring tasks and saving to data.json in the terminal.

Run from the project root:  python main.py
"""

import tempfile
from datetime import date, time
from pathlib import Path

import display
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


def show_tasks(title: str, pairs: list[PetTask], today: date) -> None:
    print(title)
    print(display.render_table(display.task_rows(pairs, today)))
    print()


def print_schedule(owner: Owner, plan: DailyPlan) -> None:
    print(f"{display.PET_HEADING} Today's Schedule - {plan.on:%A, %B %d, %Y}")
    print(f"Owner: {owner.name} | Pets: {', '.join(display.pet_label(p) for p in owner.pets)}")
    print(f"Available: {owner.day_start:%H:%M}-{owner.day_end:%H:%M}")
    print(RULE)
    print(display.render_table(display.schedule_rows(plan)))
    if plan.skipped_tasks:
        print("\nNot scheduled:")
        print(display.render_table(display.not_scheduled_rows(plan)))
    for skipped in plan.skipped_tasks:
        icon = display.STATUS_FLAGGED.split()[0] if skipped.flagged else display.CLASH_ICON
        print(f"{icon} {skipped.task.title} ({skipped.pet.name}): {skipped.reason}")
    print(RULE)
    print(plan.summary())


def main() -> None:
    owner = build_owner()
    scheduler = Scheduler(owner)
    today = date.today()

    print(RULE)
    show_tasks("1. Tasks in the order they were added (out of time order):", owner.get_all_tasks(), today)

    show_tasks("2. Sorted by time - Scheduler.sort_by_time():", scheduler.sort_by_time(owner.get_all_tasks()), today)

    show_tasks("3. Filtered by pet - Scheduler.filter_tasks(pet_name='mochi'):",
               scheduler.filter_tasks(pet_name="mochi"), today)

    print("4. Conflict warnings - Scheduler.find_conflicts():")
    for message in scheduler.find_conflicts(today) or ["No conflicts."]:
        print(f"  {display.CLASH_ICON} {message}")
    print()

    print("5. Next free slot - Scheduler.next_available_slot():")
    vet = next(pt.task for pt in owner.get_all_tasks() if pt.task.title == "Vet check-in call")
    plan = scheduler.generate_plan(today)
    for label, minutes, after in (
        ("A new 30-minute task", 30, None),
        (f"'{vet.title}' ({vet.duration_minutes} min), after its 12:00 clash", vet.duration_minutes, vet.fixed_time),
    ):
        slot = scheduler.next_available_slot(today, minutes, not_before=after)
        found = f"{slot[0]:%H:%M}-{slot[1]:%H:%M}" if slot else "none left today"
        print(f"  {display.SLOT_ICON} {label} can go at: {found}")
    print()

    print(RULE)
    print_schedule(owner, plan)
    print()

    print(RULE)
    print("6. Recurring tasks - Scheduler.mark_task_complete():")
    for pt in scheduler.sort_by_time(owner.get_all_tasks()):
        if pt.task.title in ("Heart medication", "Brush fur", "Flea treatment"):
            next_task = scheduler.mark_task_complete(pt.task.id, today)
            if next_task is None:
                print(f"  {display.DONE_ICON} {pt.task.title} ({pt.pet.name}) is {pt.task.recurrence.value}: done, nothing new created.")
            else:
                print(f"  {display.REPEAT_ICON} {pt.task.title} ({pt.pet.name}) is {pt.task.recurrence.value}: done today, "
                      f"new one due {next_task.start_date:%A, %B %d}.")
    print()
    show_tasks("7. Filtered by status - completed=True:", scheduler.filter_tasks(completed=True), today)
    show_tasks("   Filtered by status - completed=False (open):",
               scheduler.sort_by_time(scheduler.filter_tasks(completed=False)), today)

    print("8. Saving and loading - Owner.save_to_json() / Owner.load_from_json():")
    with tempfile.TemporaryDirectory() as folder:  # a temporary folder, so the demo never touches a real data.json
        path = Path(folder) / "data.json"
        owner.save_to_json(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        print(f"  {display.SAVED_ICON} Saved {len(owner.pets)} pets and {len(owner.get_all_tasks())} tasks to data.json "
              f"({path.stat().st_size} bytes, {len(lines)} lines). The start of the file:")
        for line in [l for l in lines if '"id"' not in l][:12]:  # skip the random ids so the output repeats
            print(f"      {line}")
        print("      ...")
        loaded = Owner.load_from_json(path)
        print(f"  {display.SAVED_ICON} Loaded it back: {len(loaded.pets)} pets and {len(loaded.get_all_tasks())} tasks; "
              f"identical to the original: {loaded == owner}")


if __name__ == "__main__":
    main()

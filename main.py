"""Demo: build an owner with two pets and print today's schedule.

Run from the project root:  python main.py
"""

from datetime import date, time

from pawpal_system import Category, DailyPlan, Owner, Pet, Scheduler, Task


def build_owner() -> Owner:
    owner = Owner("Jordan", day_start=time(7, 0), day_end=time(20, 0))

    biscuit = Pet("Biscuit", "dog", breed="Golden Retriever", age=4)
    biscuit.add_task(Task(
        "Morning walk", 30, priority="high", category=Category.WALK,
        preferred_start=time(7, 30),
    ))
    biscuit.add_task(Task(
        "Heart medication", 5, priority="high", category=Category.MEDS,
        required=True, fixed_time=time(8, 0),
        description="One pill, hidden in a bit of cheese",
    ))
    biscuit.add_task(Task("Lunch feeding", 10, priority="high", category=Category.FEEDING,
                          fixed_time=time(12, 0)))
    biscuit.add_task(Task(
        "Evening fetch", 25, priority="medium", category=Category.ENRICHMENT,
        preferred_start=time(18, 0),
    ))

    mochi = Pet("Mochi", "cat", breed="Siamese", age=2)
    mochi.add_task(Task("Brush fur", 15, priority="low", category=Category.GROOMING,
                        preferred_start=time(9, 0)))
    mochi.add_task(Task("Laser-pointer play", 20, priority="medium", category=Category.ENRICHMENT,
                        preferred_start=time(15, 30)))

    owner.add_pet(biscuit)
    owner.add_pet(mochi)
    return owner


def print_schedule(owner: Owner, plan: DailyPlan) -> None:
    print(f"Today's Schedule - {plan.on:%A, %B %d, %Y}")
    print(f"Owner: {owner.name} | Pets: {', '.join(p.name for p in owner.pets)}")
    print(f"Available: {owner.day_start:%H:%M}-{owner.day_end:%H:%M}")
    print("=" * 72)

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

    print("=" * 72)
    print(plan.summary())


def main() -> None:
    owner = build_owner()
    plan = Scheduler(owner).generate_plan(date.today())
    print_schedule(owner, plan)


if __name__ == "__main__":
    main()

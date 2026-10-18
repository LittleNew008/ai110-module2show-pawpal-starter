import random
from datetime import date, time

import pytest

from pawpal_system import (
    Category,
    DailyPlan,
    Owner,
    Pet,
    PetTask,
    Priority,
    Recurrence,
    ScheduledItem,
    Scheduler,
    from_minutes,
    to_minutes,
)
from pawpal_system import Task as _Task

DAY = date(2026, 3, 2)  # a Monday


def Task(*args, **kwargs):
    """Task whose start_date defaults to DAY (the real default is today, which
    would make every test task 'not due yet' on DAY)."""
    kwargs.setdefault("start_date", DAY)
    return _Task(*args, **kwargs)


def t(h, m=0):
    return time(h, m)


def make_owner(*pets, start=t(8), end=t(20), cap=None, **kw):
    return Owner("Jordan", day_start=start, day_end=end, available_minutes=cap, pets=list(pets), **kw)


def plan_for(owner, on=DAY):
    return Scheduler(owner).generate_plan(on)


def titles(plan):
    return [i.task.title for i in plan.scheduled_items]


def skipped_titles(plan):
    return [s.task.title for s in plan.skipped_tasks]


# ---------- retrieval across pets ----------


def test_get_all_tasks_spans_every_pet_with_owner_pairing():
    walk, feed, groom = Task("Walk", 20), Task("Feed", 10), Task("Groom", 15)
    dog = Pet("Rex", "dog", tasks=[walk, feed])
    cat = Pet("Mochi", "cat", tasks=[groom])
    owner = make_owner(dog, cat)

    pairs = owner.get_all_tasks()

    assert [(p.pet.name, p.task.title) for p in pairs] == [("Rex", "Walk"), ("Rex", "Feed"), ("Mochi", "Groom")]
    assert all(isinstance(p, PetTask) for p in pairs)


def test_retrieval_returns_live_tasks_not_copies():
    task = Task("Feed", 10, recurrence=Recurrence.DAILY, start_date=DAY)
    owner = make_owner(Pet("Rex", "dog", tasks=[task]))

    owner.get_all_tasks()[0].task.mark_complete(DAY)

    assert task.last_completed == DAY


def test_get_all_tasks_reflects_later_changes_without_a_stale_cache():
    pet = Pet("Rex", "dog")
    owner = make_owner(pet)
    assert owner.get_all_tasks() == []
    pet.add_task(Task("Walk", 20))
    assert [p.task.title for p in owner.get_all_tasks()] == ["Walk"]
    owner.add_pet(Pet("Mochi", "cat", tasks=[Task("Feed", 10)]))
    assert [p.task.title for p in owner.get_all_tasks()] == ["Walk", "Feed"]


class SpyOwner(Owner):
    """Owner that records which task-reading method callers use."""

    def __post_init__(self):
        super().__post_init__()
        self.calls = []

    def get_all_tasks(self):
        self.calls.append("get_all_tasks")
        return super().get_all_tasks()


def test_scheduler_reads_every_pets_tasks_through_owner_get_all_tasks():
    owner = SpyOwner(
        "Jordan",
        pets=[Pet("Rex", "dog", tasks=[Task("Walk", 20)]), Pet("Mochi", "cat", tasks=[Task("Feed", 10)])],
    )
    scheduler = Scheduler(owner)

    plan = scheduler.generate_plan(DAY)

    assert owner.calls == ["get_all_tasks"]  # exactly one read, via the Owner method
    assert {(i.pet.name, i.task.title) for i in plan.scheduled_items} == {("Rex", "Walk"), ("Mochi", "Feed")}
    # a pet added after the Scheduler was built is still planned for
    owner.add_pet(Pet("Kiwi", "bird", tasks=[Task("Seeds", 5)]))
    assert "Seeds" in titles(scheduler.generate_plan(DAY))


def test_filter_due_tasks_only_returns_due_tasks_from_all_pets():
    due = Task("Due", 5, start_date=DAY)
    future = Task("Future", 5, start_date=date(2026, 4, 1))
    done = Task("Done", 5, start_date=DAY, last_completed=DAY)
    owner = make_owner(Pet("A", "dog", tasks=[due, future]), Pet("B", "cat", tasks=[done, Task("B due", 5, start_date=DAY)]))

    result = Scheduler(owner).filter_due_tasks(DAY)

    assert [p.task.title for p in result] == ["Due", "B due"]


# ---------- Task ----------


def test_mark_complete_changes_the_tasks_status():
    task = Task("Walk", 20)
    other = Task("Feed", 10)
    assert not task.is_completed(DAY) and task.last_completed is None  # starts incomplete

    task.mark_complete(DAY)

    assert task.is_completed(DAY)  # status changed
    assert task.last_completed == DAY
    assert not other.is_completed(DAY)  # and only this task changed


def test_adding_a_task_to_a_pet_increases_its_task_count():
    pet = Pet("Mochi", "cat")
    assert len(pet.get_tasks()) == 0

    pet.add_task(Task("Feed", 10))
    assert len(pet.get_tasks()) == 1

    second = Task("Brush", 15)
    pet.add_task(second)
    assert len(pet.get_tasks()) == 2 and len(pet.tasks) == 2
    assert second in pet.get_tasks()

    with pytest.raises(ValueError):  # a rejected duplicate must not change the count
        pet.add_task(second)
    assert len(pet.get_tasks()) == 2


def test_task_due_rules():
    start = date(2026, 3, 2)  # Monday
    once = Task("once", 5, start_date=start)
    assert not once.is_due(date(2026, 3, 1))
    assert once.is_due(start) and once.is_due(date(2026, 3, 9))  # overdue stays due
    once.mark_complete(start)
    assert not once.is_due(start) and not once.is_due(date(2026, 3, 9))

    daily = Task("daily", 5, recurrence=Recurrence.DAILY, start_date=start)
    daily.mark_complete(start)
    assert not daily.is_due(start)
    assert daily.is_due(date(2026, 3, 3))  # due again tomorrow

    weekly = Task("weekly", 5, recurrence=Recurrence.WEEKLY, start_date=start)
    assert weekly.is_due(date(2026, 3, 9))
    assert not weekly.is_due(date(2026, 3, 10))


def test_completion_status_is_readable_and_resets_for_recurring_tasks():
    once = Task("once", 5, start_date=DAY)
    daily = Task("daily", 5, recurrence=Recurrence.DAILY, start_date=DAY)
    assert not once.is_completed(DAY) and not daily.is_completed(DAY)

    once.mark_complete(DAY)
    daily.mark_complete(DAY)

    assert once.is_completed(DAY) and once.is_completed(date(2026, 4, 1))  # done for good
    assert daily.is_completed(DAY)
    assert not daily.is_completed(date(2026, 3, 3))  # open again tomorrow


def test_description_is_optional_and_editable():
    task = Task("Meds", 5)
    assert task.description == ""
    pet = Pet("Rex", "dog", tasks=[task])

    pet.edit_task(task.id, description="half a pill, hidden in cheese")

    assert task.description == "half a pill, hidden in cheese"
    assert Task("Meds", 5, description="with food").description == "with food"


def test_task_validation_and_priority_strings():
    with pytest.raises(ValueError):
        Task("Walk", 0)
    with pytest.raises(ValueError):
        Task("  ", 10)
    assert Task("Walk", 10, priority="high").priority is Priority.HIGH
    with pytest.raises(ValueError):
        Priority.from_str("urgent")


def test_time_helpers_round_trip_and_reject_24h():
    assert to_minutes(t(9, 30)) - to_minutes(t(9)) == 30
    assert from_minutes(to_minutes(t(23, 59))) == t(23, 59)
    with pytest.raises(ValueError):
        from_minutes(1440)


# ---------- Pet / Owner management ----------


def test_identical_tasks_are_distinct_and_removed_by_id():
    a, b = Task("Feed", 10), Task("Feed", 10)
    assert a != b
    pet = Pet("Rex", "dog", tasks=[a, b])
    pet.remove_task(b.id)
    assert pet.tasks == [a] and pet.tasks[0] is a


def test_add_task_rejects_duplicate_id_and_get_tasks_is_a_copy():
    task = Task("Walk", 20)
    pet = Pet("Rex", "dog")
    pet.add_task(task)
    with pytest.raises(ValueError):
        pet.add_task(task)
    pet.get_tasks().clear()
    assert pet.tasks == [task]


def test_edit_task_keeps_identity_validates_and_whitelists():
    task = Task("Walk", 20)
    pet = Pet("Rex", "dog", tasks=[task])

    pet.edit_task(task.id, duration_minutes=45, priority="high")
    assert pet.tasks[0] is task and task.duration_minutes == 45 and task.priority is Priority.HIGH

    with pytest.raises(ValueError):
        pet.edit_task(task.id, duration_minutes=-5)
    assert task.duration_minutes == 45  # bad edit left the task untouched
    with pytest.raises(ValueError):
        pet.edit_task(task.id, id="hijack")
    with pytest.raises(KeyError):
        pet.edit_task("missing", title="x")


def test_pets_with_same_name_are_distinct_and_removed_by_id():
    a, b = Pet("Mochi", "cat"), Pet("Mochi", "cat")
    owner = make_owner(a, b)
    owner.remove_pet(b.id)
    assert owner.pets == [a] and owner.pets[0] is a
    with pytest.raises(ValueError):
        owner.add_pet(a)


def test_owner_availability_validation():
    with pytest.raises(ValueError):
        make_owner(start=t(20), end=t(8))
    with pytest.raises(ValueError):
        make_owner(cap=0)
    owner = make_owner()
    with pytest.raises(ValueError):
        owner.set_availability(t(10), t(9))
    assert (owner.day_start, owner.day_end) == (t(8), t(20))  # unchanged
    owner.set_availability(t(6), t(18))
    assert (owner.day_start, owner.day_end) == (t(6), t(18))


def test_set_availability_updates_the_cap_and_a_bad_cap_changes_nothing():
    owner = make_owner()
    owner.set_availability(t(7), t(19), 90)
    assert (owner.day_start, owner.day_end, owner.available_minutes) == (t(7), t(19), 90)

    with pytest.raises(ValueError):
        owner.set_availability(t(6), t(18), 0)
    assert (owner.day_start, owner.day_end, owner.available_minutes) == (t(7), t(19), 90)

    owner.set_availability(t(7), t(19))  # no cap given means no cap
    assert owner.available_minutes is None


def test_capacity_minutes_is_the_window_or_the_smaller_cap():
    assert make_owner(start=t(8), end=t(10)).capacity_minutes() == 120  # no cap: the window
    assert make_owner(start=t(8), end=t(20), cap=60).capacity_minutes() == 60  # cap is tighter
    assert make_owner(start=t(8), end=t(9), cap=500).capacity_minutes() == 60  # window is tighter


def test_pet_and_owner_reject_blank_names_and_negative_age():
    with pytest.raises(ValueError):
        Pet("  ", "dog")
    with pytest.raises(ValueError):
        Pet("Rex", "")
    with pytest.raises(ValueError):
        Pet("Rex", "dog", age=-1)
    with pytest.raises(ValueError):
        Owner("  ")
    assert Pet("Rex", "dog", age=0).age == 0


# ---------- ScheduledItem ----------


def test_scheduled_item_duration_and_overlap():
    task, pet = Task("x", 30), Pet("p", "dog")
    a = ScheduledItem(task, pet, t(9), t(9, 30))
    assert a.duration() == 30
    assert a.overlaps(ScheduledItem(task, pet, t(9, 15), t(10)))
    assert not a.overlaps(ScheduledItem(task, pet, t(9, 30), t(10)))  # back-to-back is fine
    with pytest.raises(ValueError):
        ScheduledItem(task, pet, t(9), t(9))


# ---------- sorting ----------


def test_sort_order_required_then_priority_then_shorter():
    pet = Pet("Rex", "dog")
    specs = [
        ("low-short", 5, Priority.LOW, False),
        ("high-long", 60, Priority.HIGH, False),
        ("high-short", 10, Priority.HIGH, False),
        ("req-low", 30, Priority.LOW, True),
    ]
    pairs = [PetTask(pet, Task(n, d, priority=p, required=r)) for n, d, p, r in specs]

    ordered = Scheduler(make_owner(pet)).sort_tasks(pairs)

    assert [p.task.title for p in ordered] == ["req-low", "high-short", "high-long", "low-short"]


# ---------- placement ----------


def test_basic_plan_is_back_to_back_from_window_start_with_reasons():
    pet = Pet("Rex", "dog", tasks=[Task("Walk", 30, priority="high"), Task("Feed", 10, priority="medium")])
    plan = plan_for(make_owner(pet))

    assert [(i.task.title, i.start, i.end) for i in plan.scheduled_items] == [
        ("Walk", t(8), t(8, 30)),
        ("Feed", t(8, 30), t(8, 40)),
    ]
    assert all(i.reason.startswith("Scheduled") for i in plan.scheduled_items)
    assert plan.total_minutes() == 40 and not plan.skipped_tasks and not plan.warnings


def test_fixed_time_task_is_not_displaced_by_higher_priority_flexible_task():
    pet = Pet("Rex", "dog", tasks=[
        Task("Big walk", 60, priority="high"),
        Task("Meds", 10, priority="low", fixed_time=t(8, 30)),
    ])
    plan = plan_for(make_owner(pet))
    by_title = {i.task.title: i for i in plan.scheduled_items}

    assert (by_title["Meds"].start, by_title["Meds"].end) == (t(8, 30), t(8, 40))
    assert by_title["Big walk"].start == t(8, 40)  # moved after the fixed slot, not on top of it
    assert Scheduler(make_owner(pet)).detect_conflicts(plan.scheduled_items) == []


def test_fixed_time_clash_keeps_the_required_task_and_warns_about_the_other():
    pet = Pet("Rex", "dog", tasks=[
        Task("Meds", 20, required=True, fixed_time=t(9)),
        Task("Training", 20, priority="high", fixed_time=t(9, 10)),
    ])
    plan = plan_for(make_owner(pet))

    assert titles(plan) == ["Meds"]
    assert skipped_titles(plan) == ["Training"] and "clashes with 'Meds'" in plan.skipped_tasks[0].reason
    assert not plan.skipped_tasks[0].flagged
    assert any("Training" in w and "fixed time" in w for w in plan.warnings)


def test_required_task_that_cannot_fit_is_flagged_not_forced_in():
    pet = Pet("Rex", "dog", tasks=[
        Task("Meds A", 20, required=True),
        Task("Meds B", 20, required=True),
        Task("Play", 5, priority="high"),
    ])
    plan = plan_for(make_owner(pet, start=t(8), end=t(8, 30)))

    assert titles(plan) == ["Meds A", "Play"]  # optional task did not bump required one
    flagged = plan.flagged_tasks()
    assert [f.task.title for f in flagged] == ["Meds B"] and flagged[0].flagged
    assert any("REQUIRED" in w and "Meds B" in w for w in plan.warnings)
    assert "flagged" in plan.summary()


def test_required_fixed_task_outside_window_is_flagged():
    pet = Pet("Rex", "dog", tasks=[Task("Meds", 10, required=True, fixed_time=t(22))])
    plan = plan_for(make_owner(pet))
    assert not plan.scheduled_items
    assert plan.skipped_tasks[0].flagged and "outside the available window" in plan.skipped_tasks[0].reason


def test_fragmented_free_time_cannot_fit_a_task_that_total_free_time_would():
    pet = Pet("Rex", "dog", tasks=[
        Task("Meds", 20, fixed_time=t(8, 20)),
        Task("Long walk", 30),
    ])
    plan = plan_for(make_owner(pet, start=t(8), end=t(9)))  # 20 + 20 free around the fixed task

    assert titles(plan) == ["Meds"]
    assert "no free gap of 30 min" in plan.skipped_tasks[0].reason and "largest gap: 20" in plan.skipped_tasks[0].reason


def test_task_that_does_not_fit_is_skipped_and_later_shorter_tasks_still_placed():
    pet = Pet("Rex", "dog", tasks=[Task("Too long", 40, priority="high"), Task("Short", 20, priority="low")])
    plan = plan_for(make_owner(pet, start=t(8), end=t(8, 30)))
    assert titles(plan) == ["Short"] and skipped_titles(plan) == ["Too long"]


def test_minutes_cap_is_claimed_by_required_then_priority_in_sort_order():
    pet = Pet("Rex", "dog", tasks=[
        Task("Low", 10, priority="low"),
        Task("High", 20, priority="high"),
        Task("Meds", 20, required=True),
    ])
    plan = plan_for(make_owner(pet, cap=30))

    assert sorted(titles(plan)) == ["Low", "Meds"]
    assert skipped_titles(plan) == ["High"] and "30-minute daily limit" in plan.skipped_tasks[0].reason
    assert plan.total_minutes() <= 30


def test_preferred_time_is_used_when_free_else_falls_back_to_earliest_gap():
    pet = Pet("Rex", "dog", tasks=[
        Task("Walk", 30, priority="high", preferred_start=t(12)),
        Task("Run", 30, priority="medium", preferred_start=t(12, 15)),  # overlaps the walk
    ])
    plan = plan_for(make_owner(pet))
    by_title = {i.task.title: i for i in plan.scheduled_items}

    assert by_title["Walk"].start == t(12) and "preferred time" in by_title["Walk"].reason
    assert by_title["Run"].start == t(8) and "preferred time unavailable" in by_title["Run"].reason


def test_owner_category_preference_applies_when_task_has_none():
    pet = Pet("Rex", "dog", tasks=[Task("Walk", 30, category=Category.WALK)])
    plan = plan_for(make_owner(pet, preferred_times={Category.WALK: t(17)}))
    assert plan.scheduled_items[0].start == t(17)


def test_tasks_for_different_pets_never_overlap():
    owner = make_owner(
        Pet("Rex", "dog", tasks=[Task("Walk", 30, fixed_time=t(9))]),
        Pet("Mochi", "cat", tasks=[Task("Play", 30, fixed_time=t(9))]),
    )
    plan = plan_for(owner)
    assert len(plan.scheduled_items) == 1 and len(plan.skipped_tasks) == 1
    assert Scheduler(owner).detect_conflicts(plan.scheduled_items) == []


def test_recurring_task_completed_today_is_replanned_tomorrow():
    task = Task("Feed", 10, recurrence=Recurrence.DAILY, start_date=DAY)
    owner = make_owner(Pet("Rex", "dog", tasks=[task]))
    assert titles(plan_for(owner)) == ["Feed"]
    task.mark_complete(DAY)
    assert plan_for(owner).scheduled_items == []
    assert titles(plan_for(owner, date(2026, 3, 3))) == ["Feed"]


def test_empty_owner_gives_empty_plan_with_working_outputs():
    plan = plan_for(make_owner())
    assert plan == DailyPlan(DAY)
    assert plan.to_table() == [] and "0 scheduled" in plan.explain()


def test_plan_outputs_cover_scheduled_and_skipped_rows():
    pet = Pet("Rex", "dog", tasks=[Task("Meds", 20, required=True), Task("Meds2", 20, required=True)])
    plan = plan_for(make_owner(pet, start=t(8), end=t(8, 30)))
    rows = plan.to_table()
    assert [r["status"] for r in rows] == ["scheduled", "FLAGGED"]
    assert rows[0]["start"] == "08:00" and rows[0]["end"] == "08:20" and rows[0]["minutes"] == 20
    text = plan.explain()
    assert "08:00-08:20  Meds (Rex)" in text and "Not scheduled:" in text and "Warnings:" in text


# ---------- invariants over random inputs ----------


@pytest.mark.parametrize("seed", range(25))
def test_random_plans_never_overlap_stay_in_window_respect_cap_and_account_for_every_task(seed):
    rng = random.Random(seed)
    pets = []
    for p in range(rng.randint(1, 3)):
        tasks = []
        for n in range(rng.randint(0, 8)):
            fixed = from_minutes(rng.randrange(7 * 60, 21 * 60, 5)) if rng.random() < 0.3 else None
            tasks.append(Task(
                f"p{p}t{n}", rng.choice([5, 10, 15, 30, 45, 90]),
                priority=rng.choice(list(Priority)), required=rng.random() < 0.25,
                fixed_time=fixed,
                preferred_start=from_minutes(rng.randrange(8 * 60, 19 * 60, 5)) if rng.random() < 0.3 else None,
            ))
        pets.append(Pet(f"pet{p}", "dog", tasks=tasks))
    cap = rng.choice([None, 60, 120, 240])
    owner = make_owner(*pets, cap=cap)

    plan = plan_for(owner)

    assert Scheduler(owner).detect_conflicts(plan.scheduled_items) == []
    for item in plan.scheduled_items:
        assert to_minutes(owner.day_start) <= to_minutes(item.start) < to_minutes(item.end) <= to_minutes(owner.day_end)
        if item.task.fixed_time is not None:
            assert item.start == item.task.fixed_time
    if cap is not None:
        assert plan.total_minutes() <= cap
    due = {pt.task.id for pt in owner.get_all_tasks()}
    accounted = [i.task.id for i in plan.scheduled_items] + [s.task.id for s in plan.skipped_tasks]
    assert sorted(accounted) == sorted(due)  # nothing lost, nothing duplicated
    assert all(s.flagged == s.task.required for s in plan.skipped_tasks)

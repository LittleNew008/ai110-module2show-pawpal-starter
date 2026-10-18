import random
from datetime import date, time, timedelta

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
    _overlapping_pairs,
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

    assert task.completed_on == DAY


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
    done = Task("Done", 5, start_date=DAY, completed_on=DAY)
    owner = make_owner(Pet("A", "dog", tasks=[due, future]), Pet("B", "cat", tasks=[done, Task("B due", 5, start_date=DAY)]))

    result = Scheduler(owner).filter_due_tasks(DAY)

    assert [p.task.title for p in result] == ["Due", "B due"]


# ---------- Task ----------


def test_mark_complete_changes_the_tasks_status():
    task = Task("Walk", 20)
    other = Task("Feed", 10)
    assert not task.is_completed() and task.completed_on is None  # starts incomplete

    task.mark_complete(DAY)

    assert task.is_completed()  # status changed
    assert task.completed_on == DAY
    assert not other.is_completed()  # and only this task changed


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
    start = date(2026, 3, 2)
    task = Task("t", 5, start_date=start)
    assert not task.is_due(date(2026, 3, 1))  # not started yet
    assert task.is_due(start) and task.is_due(date(2026, 3, 9))  # overdue stays due
    task.mark_complete(start)
    assert not task.is_due(start) and not task.is_due(date(2026, 3, 9))  # done


def test_completion_status_belongs_to_each_occurrence():
    once = Task("once", 5)
    daily = Task("daily", 5, recurrence=Recurrence.DAILY)
    assert not once.is_completed() and not daily.is_completed()

    once.mark_complete(DAY)
    next_daily = daily.mark_complete(DAY)

    assert once.is_completed() and daily.is_completed()  # these occurrences are done for good
    assert next_daily is not None and not next_daily.is_completed()  # the next one is open


# ---------- recurring tasks ----------

MON = date(2026, 3, 2)  # a Monday


@pytest.mark.parametrize(
    "recurrence, completed_on, expected",
    [
        (Recurrence.DAILY, MON, date(2026, 3, 3)),  # on time: today + 1 day
        (Recurrence.DAILY, date(2026, 3, 5), date(2026, 3, 6)),  # 3 days late: still tomorrow
        (Recurrence.WEEKLY, MON, date(2026, 3, 9)),  # on time: today + 7 days
        (Recurrence.WEEKLY, date(2026, 3, 4), date(2026, 3, 9)),  # late on Wednesday: next Monday, not next Wednesday
        (Recurrence.WEEKLY, date(2026, 3, 12), date(2026, 3, 16)),  # more than a week late: next Monday after that
        (Recurrence.DAILY, date(2026, 2, 27), date(2026, 3, 3)),  # finished early: first step after start_date
        (Recurrence.ONCE, MON, None),  # a one-off has no next occurrence
    ],
)
def test_next_due_date_uses_timedelta_steps_from_the_tasks_own_schedule(recurrence, completed_on, expected):
    task = Task("t", 5, recurrence=recurrence, start_date=MON)
    assert task.next_due_date(completed_on) == expected


def test_completing_a_recurring_task_creates_the_next_occurrence():
    task = Task("Feed", 10, recurrence=Recurrence.DAILY, start_date=MON, priority="high", required=True,
                fixed_time=t(8), description="wet food", category=Category.FEEDING)

    nxt = task.mark_complete(MON)

    assert task.completed_on == MON
    assert nxt is not None and nxt is not task and nxt.id != task.id  # a new instance
    assert nxt.start_date == date(2026, 3, 3) and nxt.completed_on is None
    for name in ("title", "duration_minutes", "priority", "category", "fixed_time", "recurrence",
                 "required", "description"):
        assert getattr(nxt, name) == getattr(task, name)  # everything else is carried over


def test_completing_a_one_off_or_an_already_completed_task_creates_nothing():
    once = Task("once", 5)
    assert once.mark_complete(MON) is None and once.completed_on == MON

    daily = Task("daily", 5, recurrence=Recurrence.DAILY, start_date=MON)
    assert daily.mark_complete(MON) is not None
    assert daily.mark_complete(date(2026, 3, 9)) is None  # second call: no duplicate...
    assert daily.completed_on == MON  # ...and the original date is kept


def test_pet_complete_task_adds_exactly_one_next_occurrence():
    task = Task("Walk", 20, recurrence=Recurrence.DAILY, start_date=MON)
    pet = Pet("Rex", "dog", tasks=[task])

    nxt = pet.complete_task(task.id, MON)
    pet.complete_task(task.id, MON)  # repeating it changes nothing

    assert pet.tasks == [task, nxt] and nxt is pet.tasks[1]
    assert nxt is not None and nxt.start_date == date(2026, 3, 3)
    with pytest.raises(KeyError):
        pet.complete_task("missing", MON)


def test_scheduler_mark_task_complete_finds_the_pet_and_chains_through_days():
    rex_task = Task("Walk", 20, recurrence=Recurrence.DAILY, start_date=MON)
    mochi = Pet("Mochi", "cat", tasks=[Task("Brush", 15)])
    rex = Pet("Rex", "dog", tasks=[rex_task])
    owner = make_owner(mochi, rex)
    scheduler = Scheduler(owner)

    day, task = MON, rex_task
    for _ in range(3):  # complete it three days in a row
        task = scheduler.mark_task_complete(task.id, day)
        day = day + timedelta(days=1)
        assert task is not None and task.start_date == day

    assert len(rex.tasks) == 4 and [t_.start_date for t_ in rex.tasks] == [MON + timedelta(days=n) for n in range(4)]
    assert len(mochi.tasks) == 1  # the other pet is untouched
    with pytest.raises(KeyError):
        scheduler.mark_task_complete("missing", MON)


def test_recurring_series_has_one_open_occurrence_and_the_plan_follows_it():
    task = Task("Feed", 10, recurrence=Recurrence.DAILY, start_date=DAY)
    owner = make_owner(Pet("Rex", "dog", tasks=[task]))
    assert titles(plan_for(owner)) == ["Feed"]

    Scheduler(owner).mark_task_complete(task.id, DAY)

    assert plan_for(owner).scheduled_items == []  # done today; tomorrow's occurrence is not due yet
    assert titles(plan_for(owner, date(2026, 3, 3))) == ["Feed"]
    open_tasks = Scheduler(owner).filter_tasks(completed=False)
    assert len(open_tasks) == 1  # never two open occurrences of the same series


# ---------- sorting by time ----------


def test_sort_by_time_orders_by_requested_time_with_untimed_tasks_last():
    pet = Pet("Rex", "dog")
    specs = [  # added deliberately out of order
        ("evening", dict(preferred_start=t(18))),
        ("anytime", dict()),
        ("noon", dict(fixed_time=t(12))),
        ("early", dict(fixed_time=t(7, 5))),
        ("midnight", dict(fixed_time=t(0, 0))),
    ]
    pairs = [PetTask(pet, Task(name, 10, **kw)) for name, kw in specs]

    ordered = Scheduler(make_owner(pet)).sort_by_time(pairs)

    assert [p.task.title for p in ordered] == ["midnight", "early", "noon", "evening", "anytime"]
    assert [p.task.title for p in pairs][0] == "evening"  # the input list is not modified


def test_sort_by_time_breaks_ties_by_priority_then_title_and_fixed_beats_preferred():
    pet = Pet("Rex", "dog")
    pairs = [
        PetTask(pet, Task("b", 10, fixed_time=t(9), priority="low")),
        PetTask(pet, Task("a", 10, fixed_time=t(9), priority="low")),
        PetTask(pet, Task("c", 10, fixed_time=t(9), priority="high")),
        PetTask(pet, Task("d", 10, fixed_time=t(6), preferred_start=t(20))),  # fixed wins: 06:00
    ]

    ordered = Scheduler(make_owner(pet)).sort_by_time(pairs)

    assert [p.task.title for p in ordered] == ["d", "c", "a", "b"]


def test_requested_time_is_fixed_then_preferred_then_none():
    assert Task("t", 5, fixed_time=t(9), preferred_start=t(10)).requested_time == t(9)
    assert Task("t", 5, preferred_start=t(10)).requested_time == t(10)
    assert Task("t", 5).requested_time is None


# ---------- filtering ----------


def _filter_owner():
    rex = Pet("Rex", "dog", tasks=[Task("Walk", 20), Task("Feed", 10, completed_on=DAY)])
    mochi = Pet("Mochi", "cat", tasks=[Task("Brush", 15), Task("Play", 10, completed_on=DAY)])
    return make_owner(rex, mochi)


def _names(pairs):
    return [(p.pet.name, p.task.title) for p in pairs]


def test_filter_tasks_by_pet_name_ignores_case_and_spaces():
    scheduler = Scheduler(_filter_owner())
    assert _names(scheduler.filter_tasks(pet_name="mochi")) == [("Mochi", "Brush"), ("Mochi", "Play")]
    assert _names(scheduler.filter_tasks(pet_name="  REX ")) == [("Rex", "Walk"), ("Rex", "Feed")]
    assert scheduler.filter_tasks(pet_name="Nobody") == []


def test_filter_tasks_by_completion_status():
    scheduler = Scheduler(_filter_owner())
    assert _names(scheduler.filter_tasks(completed=False)) == [("Rex", "Walk"), ("Mochi", "Brush")]
    assert _names(scheduler.filter_tasks(completed=True)) == [("Rex", "Feed"), ("Mochi", "Play")]
    assert len(scheduler.filter_tasks()) == 4  # no filter keeps everything


def test_filter_tasks_combines_filters_and_can_refine_a_given_list():
    scheduler = Scheduler(_filter_owner())
    assert _names(scheduler.filter_tasks(pet_name="Rex", completed=True)) == [("Rex", "Feed")]

    only_mochi = scheduler.filter_tasks(pet_name="Mochi")
    assert _names(scheduler.filter_tasks(only_mochi, completed=False)) == [("Mochi", "Brush")]


# ---------- conflict warnings ----------


def _conflict_scheduler(*task_specs):
    """task_specs: (pet name, title, fixed time, minutes). One pet per distinct name."""
    pets = {}
    for pet_name, title, when, minutes in task_specs:
        pets.setdefault(pet_name, Pet(pet_name, "dog")).add_task(Task(title, minutes, fixed_time=when))
    return Scheduler(make_owner(*pets.values()))


def test_find_conflicts_warns_for_the_same_pet_and_for_different_pets():
    same_pet = _conflict_scheduler(("Rex", "Walk", t(9), 30), ("Rex", "Bath", t(9), 20))
    warnings = same_pet.find_conflicts(DAY)
    assert len(warnings) == 1 and "same pet" in warnings[0]
    assert "'Walk' (Rex, 09:00-09:30)" in warnings[0] and "'Bath' (Rex, 09:00-09:20)" in warnings[0]

    two_pets = _conflict_scheduler(("Rex", "Walk", t(9), 30), ("Mochi", "Brush", t(9), 15))
    warnings = two_pets.find_conflicts(DAY)
    assert len(warnings) == 1 and "different pets" in warnings[0]


def test_find_conflicts_uses_duration_not_just_the_start_time():
    overlapping = _conflict_scheduler(("Rex", "Walk", t(8), 30), ("Rex", "Meds", t(8, 20), 10))  # different starts
    assert len(overlapping.find_conflicts(DAY)) == 1

    back_to_back = _conflict_scheduler(("Rex", "Walk", t(8), 30), ("Rex", "Meds", t(8, 30), 10))
    assert back_to_back.find_conflicts(DAY) == []  # touching is not overlapping

    apart = _conflict_scheduler(("Rex", "Walk", t(8), 30), ("Mochi", "Brush", t(15), 15))
    assert apart.find_conflicts(DAY) == []


def test_find_conflicts_reports_every_overlapping_pair_in_time_order():
    scheduler = _conflict_scheduler(
        ("Rex", "C", t(9, 10), 30), ("Rex", "A", t(9), 30), ("Mochi", "B", t(9, 5), 30), ("Mochi", "D", t(12), 10))
    warnings = scheduler.find_conflicts(DAY)
    assert len(warnings) == 3  # A-B, A-C, B-C; D overlaps nothing
    assert "'A'" in warnings[0] and "'B'" in warnings[0]
    assert "'A'" in warnings[1] and "'C'" in warnings[1]
    assert "'B'" in warnings[2] and "'C'" in warnings[2]


def test_find_conflicts_ignores_flexible_completed_and_not_yet_due_tasks_and_never_raises():
    pet = Pet("Rex", "dog", tasks=[
        Task("Fixed", 30, fixed_time=t(9)),
        Task("Flexible", 30),  # no committed time
        Task("Preferred", 30, preferred_start=t(9)),  # only a preference
        Task("Done", 30, fixed_time=t(9), completed_on=DAY),
        Task("Later", 30, fixed_time=t(9), start_date=date(2026, 4, 1)),
    ])
    scheduler = Scheduler(make_owner(pet))
    assert scheduler.find_conflicts(DAY) == []
    assert Scheduler(make_owner()).find_conflicts(DAY) == []  # nothing at all is fine too
    assert len(scheduler.find_conflicts(date(2026, 4, 1))) == 1  # Fixed vs Later, once Later is due


def _random_items(rng, n, span):
    pet = Pet("p", "dog")
    items = []
    for k in range(n):
        start, length = rng.randrange(0, span), rng.choice([5, 10, 20, 30, 60])
        items.append(ScheduledItem(Task(f"t{k}", length), pet, from_minutes(start), from_minutes(min(start + length, 1439))))
    return items


@pytest.mark.parametrize("seed", range(20))
def test_detect_conflicts_matches_a_brute_force_pairwise_check(seed):
    """The early-exit sweep must find exactly the pairs that comparing every pair with
    ScheduledItem.overlaps finds, in the same order, for sparse and crowded days alike."""
    rng = random.Random(seed)
    items = _random_items(rng, rng.randint(0, 40), span=rng.choice([60, 300, 1400]))
    ordered = sorted(items, key=lambda i: to_minutes(i.start))
    expected = [(a.task.id, b.task.id) for k, a in enumerate(ordered) for b in ordered[k + 1:] if a.overlaps(b)]

    found = Scheduler(make_owner()).detect_conflicts(items)

    assert [(a.task.id, b.task.id) for a, b in found] == expected


class _CountingList(list):
    """A list that counts how many times its items are looked up by index."""

    lookups = 0

    def __getitem__(self, index):
        type(self).lookups += 1
        return super().__getitem__(index)


def test_the_sweep_does_work_proportional_to_the_input_not_to_every_pair():
    """On a conflict-free day of 1000 spans the sweep must look at each span about once, not
    compare all ~500,000 pairs. Counting lookups (instead of timing) keeps this deterministic."""
    spans = _CountingList((k, k + 1, k) for k in range(1000))
    _CountingList.lookups = 0

    assert _overlapping_pairs(spans) == []
    assert _CountingList.lookups < 5 * len(spans)


def test_the_sweep_finds_overlaps_without_scanning_past_the_first_non_overlap():
    spans = [(0, 30, "a"), (10, 20, "b"), (25, 40, "c"), (30, 50, "d"), (100, 110, "e")]
    pairs = [(a[2], b[2]) for a, b in _overlapping_pairs(spans)]
    assert pairs == [("a", "b"), ("a", "c"), ("c", "d")]  # a and d only touch at minute 30, so they are not a pair


def test_the_planner_still_resolves_a_conflict_the_warning_reported():
    scheduler = _conflict_scheduler(("Rex", "Walk", t(9), 30), ("Mochi", "Brush", t(9), 15))
    assert scheduler.find_conflicts(DAY)  # warned about up front
    plan = scheduler.generate_plan(DAY)
    assert len(plan.scheduled_items) == 1 and len(plan.skipped_tasks) == 1  # and resolved when planning


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


# =====================================================================
# Phase 5: edge cases
# =====================================================================

# ---------- sorting ----------


def test_sort_by_time_breaks_title_ties_ignoring_case():
    pet = Pet("P", "dog")
    pairs = [PetTask(pet, Task(name, 10)) for name in ("zebra", "Apple", "banana", "Cherry")]

    ordered = Scheduler(make_owner(pet)).sort_by_time(pairs)

    assert [p.task.title for p in ordered] == ["Apple", "banana", "Cherry", "zebra"]


def test_sort_by_time_handles_an_empty_list_and_a_list_with_no_times_at_all():
    scheduler = Scheduler(make_owner())
    assert scheduler.sort_by_time([]) == []

    pet = Pet("P", "dog")
    pairs = [
        PetTask(pet, Task("b", 10, priority="low")),
        PetTask(pet, Task("c", 10, priority="high")),
        PetTask(pet, Task("a", 10, priority="high")),
    ]
    assert [p.task.title for p in scheduler.sort_by_time(pairs)] == ["a", "c", "b"]  # priority, then title


def test_plan_lists_tasks_in_chronological_order_whatever_order_they_were_added():
    pet = Pet("Rex", "dog")
    for title, kwargs in [
        ("evening", dict(preferred_start=t(18))),
        ("noon", dict(fixed_time=t(12))),
        ("anytime", {}),
        ("early", dict(fixed_time=t(7, 30))),
    ]:
        pet.add_task(Task(title, 20, **kwargs))

    plan = plan_for(make_owner(pet, start=t(7), end=t(20)))

    starts = [item.start for item in plan.scheduled_items]
    assert starts == sorted(starts)
    assert [(i.task.title, i.start) for i in plan.scheduled_items] == [
        ("anytime", t(7)), ("early", t(7, 30)), ("noon", t(12)), ("evening", t(18))]


# ---------- recurring tasks ----------


@pytest.mark.parametrize(
    "recurrence, start, expected",
    [
        (Recurrence.DAILY, date(2028, 2, 28), date(2028, 2, 29)),  # into a leap day
        (Recurrence.DAILY, date(2028, 2, 29), date(2028, 3, 1)),  # out of a leap day
        (Recurrence.DAILY, date(2026, 12, 31), date(2027, 1, 1)),  # across a year end
        (Recurrence.WEEKLY, date(2026, 1, 28), date(2026, 2, 4)),  # across a month end
        (Recurrence.WEEKLY, date(2026, 12, 28), date(2027, 1, 4)),  # across a year end
    ],
)
def test_next_due_date_is_right_across_month_year_and_leap_day_boundaries(recurrence, start, expected):
    task = Task("t", 5, recurrence=recurrence, start_date=start)
    assert task.next_due_date(start) == expected


def test_a_weekly_task_stays_on_its_weekday_even_when_completed_late_each_time():
    task = Task("t", 5, recurrence=Recurrence.WEEKLY, start_date=MON)
    pet = Pet("P", "dog", tasks=[task])
    scheduler = Scheduler(make_owner(pet))

    current = task
    for days_late in (2, 3, 1):
        current = scheduler.mark_task_complete(current.id, current.start_date + timedelta(days=days_late))
        assert current is not None and current.start_date.weekday() == MON.weekday()

    assert [x.start_date for x in pet.tasks] == [MON + timedelta(weeks=n) for n in range(4)]


# ---------- conflicts ----------


def test_find_conflicts_flags_identical_duplicate_times_and_every_pair_in_a_three_way_clash():
    duplicates = _conflict_scheduler(("Rex", "Walk", t(9), 30), ("Rex", "Walk", t(9), 30))  # same title, time, length
    assert len(duplicates.find_conflicts(DAY)) == 1

    three_way = _conflict_scheduler(("Rex", "A", t(9), 30), ("Rex", "B", t(9), 30), ("Mochi", "C", t(9), 30))
    assert len(three_way.find_conflicts(DAY)) == 3  # A-B, A-C, B-C


# ---------- the edges of the day ----------


@pytest.mark.parametrize(
    "start, minutes, is_scheduled",
    [
        (t(8), 30, True),  # starts exactly when the window opens
        (t(8, 30), 30, True),  # ends exactly when the window closes
        (t(8, 31), 30, False),  # ends one minute after it closes
        (t(7, 59), 10, False),  # starts one minute before it opens
    ],
)
def test_a_fixed_task_must_lie_completely_inside_the_window(start, minutes, is_scheduled):
    pet = Pet("P", "dog", tasks=[Task("t", minutes, fixed_time=start)])

    plan = plan_for(make_owner(pet, start=t(8), end=t(9)))

    assert bool(plan.scheduled_items) is is_scheduled
    if not is_scheduled:
        assert "outside the available window" in plan.skipped_tasks[0].reason


def test_a_clash_at_closing_time_is_explained_as_a_clash_not_as_being_outside_the_window():
    """Both tasks lie inside the 08:00-09:00 window and end exactly at 09:00; the shorter one is
    placed first, so the longer one must be reported as clashing, not as 'outside the window'."""
    pet = Pet("P", "dog", tasks=[Task("long", 30, fixed_time=t(8, 30)), Task("short", 15, fixed_time=t(8, 45))])

    plan = plan_for(make_owner(pet, start=t(8), end=t(9)))

    assert titles(plan) == ["short"]
    reason = plan.skipped_tasks[0].reason
    assert plan.skipped_tasks[0].task.title == "long"
    assert "clashes with 'short'" in reason and "outside" not in reason


@pytest.mark.parametrize("minutes, is_scheduled", [(60, True), (61, False)])
def test_a_flexible_task_exactly_as_long_as_the_window_fits_but_one_minute_more_does_not(minutes, is_scheduled):
    pet = Pet("P", "dog", tasks=[Task("t", minutes)])
    plan = plan_for(make_owner(pet, start=t(8), end=t(9)))
    assert bool(plan.scheduled_items) is is_scheduled


def test_times_with_seconds_are_truncated_to_the_minute():
    pet = Pet("P", "dog", tasks=[Task("t", 10, fixed_time=time(9, 0, 45))])

    item = plan_for(make_owner(pet)).scheduled_items[0]

    assert (item.start, item.end) == (t(9, 0), t(9, 10))


# ---------- empty and degenerate inputs ----------


def test_a_pet_with_no_tasks_changes_nothing_for_the_other_pets():
    plan = plan_for(make_owner(Pet("Empty", "dog"), Pet("Busy", "cat", tasks=[Task("x", 10)])))
    assert titles(plan) == ["x"] and plan.skipped_tasks == [] and plan.warnings == []


def test_an_owner_with_no_pets_gives_safe_empty_results_from_every_scheduler_method():
    scheduler = Scheduler(make_owner())
    assert scheduler.filter_due_tasks(DAY) == [] and scheduler.filter_tasks() == []
    assert scheduler.sort_by_time([]) == [] and scheduler.find_conflicts(DAY) == []
    assert scheduler.generate_plan(DAY).scheduled_items == []
    with pytest.raises(KeyError):
        scheduler.mark_task_complete("missing", DAY)


def test_a_plan_where_every_task_is_already_completed_is_empty_with_no_warnings():
    task = Task("t", 10)
    task.mark_complete(DAY)
    plan = plan_for(make_owner(Pet("P", "dog", tasks=[task])))
    assert plan.scheduled_items == [] and plan.skipped_tasks == [] and plan.warnings == []


def test_filter_tasks_given_an_empty_list_stays_empty_and_a_blank_pet_name_matches_nothing():
    scheduler = Scheduler(make_owner(Pet("Busy", "cat", tasks=[Task("x", 10)])))
    assert scheduler.filter_tasks([]) == []  # an empty list is not "no list": it must not fall back to every task
    assert scheduler.filter_tasks(pet_name="") == [] and scheduler.filter_tasks(pet_name="   ") == []


def test_a_required_task_longer_than_the_daily_limit_is_flagged_with_a_warning():
    pet = Pet("P", "dog", tasks=[Task("Meds", 30, required=True)])

    plan = plan_for(make_owner(pet, cap=10))

    assert plan.scheduled_items == []
    assert plan.skipped_tasks[0].flagged and "10-minute daily limit" in plan.skipped_tasks[0].reason
    assert any("REQUIRED" in w for w in plan.warnings)


def test_generating_a_plan_twice_gives_the_same_plan_and_changes_no_task():
    pet = Pet("P", "dog", tasks=[Task("a", 20, fixed_time=t(9)), Task("b", 15), Task("c", 30, required=True)])
    scheduler = Scheduler(make_owner(pet))
    before = [(x.id, x.start_date, x.completed_on, x.fixed_time) for x in pet.tasks]

    first, second = scheduler.generate_plan(DAY), scheduler.generate_plan(DAY)

    assert first == second
    assert before == [(x.id, x.start_date, x.completed_on, x.fixed_time) for x in pet.tasks]


def test_a_large_busy_day_still_satisfies_every_planning_invariant():
    rng = random.Random(99)
    pets = [Pet(f"pet{p}", "dog", tasks=[
        Task(f"p{p}t{n}", rng.choice([5, 10, 15, 30]), priority=rng.choice(list(Priority)),
             required=rng.random() < 0.1,
             fixed_time=from_minutes(rng.randrange(8 * 60, 20 * 60, 5)) if rng.random() < 0.3 else None)
        for n in range(200)]) for p in range(3)]  # 600 tasks, far more than fit in one day
    owner = make_owner(*pets)

    plan = plan_for(owner)

    assert Scheduler(owner).detect_conflicts(plan.scheduled_items) == []
    assert plan.total_minutes() <= owner.capacity_minutes()
    starts = [i.start for i in plan.scheduled_items]
    assert starts == sorted(starts)
    accounted = sorted([i.task.id for i in plan.scheduled_items] + [s.task.id for s in plan.skipped_tasks])
    assert accounted == sorted(pt.task.id for pt in owner.get_all_tasks())

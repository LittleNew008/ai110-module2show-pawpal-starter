"""Headless tests of the Streamlit UI (app.py) using streamlit.testing.v1.AppTest.

They drive the real script the way a user would (fill a form, click a button) and
assert on the Owner object stored in st.session_state, so they check the wiring
between the UI and the classes in pawpal_system.py.
"""

from datetime import date, time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pawpal_system import Priority, Recurrence

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
ADD_PET = "FormSubmitter:add_pet_form-Add pet"
ADD_TASK = "FormSubmitter:add_task_form-Add task"
SAVE_OWNER = "FormSubmitter:owner_form-Save availability"


@pytest.fixture
def at():
    return AppTest.from_file(APP_PATH, default_timeout=15).run()


def owner_of(at):
    return at.session_state["owner"]


def add_pet(at, name, species="dog"):
    at.text_input(key="pet_name").set_value(name)
    at.selectbox(key="pet_species").set_value(species)
    at.button(ADD_PET).click().run()
    return at


def add_task(at, title, *, pet_id=None, duration=20, timing=None, when=None, required=False, priority=None,
             recurrence=None):
    if pet_id is not None:
        at.selectbox(key="task_pet").set_value(pet_id)
    if recurrence is not None:
        at.selectbox(key="task_repeat").set_value(recurrence)
    at.text_input(key="task_title").set_value(title)
    at.number_input(key="task_duration").set_value(duration)
    if priority is not None:
        at.selectbox(key="task_priority").set_value(priority)
    if timing is not None:
        at.radio(key="task_timing").set_value(timing)
    if when is not None:
        at.time_input(key="task_time").set_value(when)
    if required:
        at.checkbox(key="task_required").check()
    at.button(ADD_TASK).click().run()
    return at


def table_rows(at):
    return at.table[0].value.to_dict("records")


# ---------- memory: the Owner lives in st.session_state ----------


def test_app_loads_without_errors_and_starts_with_an_empty_owner(at):
    assert not at.exception
    assert owner_of(at).pets == []
    assert any("No pets yet" in i.value for i in at.info)


def test_owner_is_created_once_and_survives_reruns(at):
    first = owner_of(at)
    add_pet(at, "Mochi")
    at.run()  # an unrelated rerun, like any click would trigger

    assert owner_of(at) is first  # reused, not recreated
    assert [p.name for p in owner_of(at).pets] == ["Mochi"]  # data persisted


# ---------- adding pets goes through Owner.add_pet ----------


def test_add_pet_form_adds_a_pet_to_the_owner_and_updates_the_page(at):
    add_pet(at, "  Mochi  ", species="cat")

    pet = owner_of(at).pets[0]
    assert (pet.name, pet.species) == ("Mochi", "cat")  # whitespace stripped
    assert any(s.value == "Added Mochi." for s in at.success)
    assert any("Mochi" in m.value for m in at.markdown)  # the pet list shows it
    assert at.selectbox(key="task_pet").options == ["Mochi (cat)"]  # and the task form can use it


def test_blank_and_duplicate_pet_names_show_an_error_and_add_nothing(at):
    add_pet(at, "   ")
    assert owner_of(at).pets == [] and at.error

    add_pet(at, "Mochi")
    add_pet(at, "mochi")  # same name, different case
    assert len(owner_of(at).pets) == 1
    assert any("already have a pet" in e.value for e in at.error)


def test_remove_pet_button_removes_the_pet(at):
    add_pet(at, "Mochi")
    pet = owner_of(at).pets[0]

    at.button(key=f"remove_pet_{pet.id}").click().run()

    assert owner_of(at).pets == []
    assert any("No pets yet" in i.value for i in at.info)


# ---------- adding and editing tasks goes through Pet.add_task / edit_task ----------


def test_add_task_form_adds_the_task_to_the_selected_pet_only(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi", species="cat")
    rex, mochi = owner_of(at).pets

    add_task(at, "Brush fur", pet_id=mochi.id, duration=15)

    assert rex.tasks == []
    assert [(t.title, t.duration_minutes) for t in mochi.tasks] == [("Brush fur", 15)]


def test_task_form_timing_modes_set_fixed_and_preferred_times(at):
    add_pet(at, "Rex")
    add_task(at, "Meds", timing="Fixed time", when=time(9, 0), required=True, priority=Priority.HIGH)
    add_task(at, "Walk", timing="Preferred time", when=time(17, 30))
    add_task(at, "Play")

    meds, walk, play = owner_of(at).pets[0].tasks
    assert (meds.fixed_time, meds.preferred_start, meds.required, meds.priority) == (time(9), None, True, Priority.HIGH)
    assert (walk.fixed_time, walk.preferred_start) == (None, time(17, 30))
    assert (play.fixed_time, play.preferred_start) == (None, None)


def test_blank_task_title_is_rejected_with_an_error(at):
    add_pet(at, "Rex")
    add_task(at, "   ")

    assert owner_of(at).pets[0].tasks == []
    assert any("title" in e.value for e in at.error)


def test_edit_form_changes_the_task_and_a_bad_edit_shows_an_error(at):
    add_pet(at, "Rex")
    add_task(at, "Walk")
    task = owner_of(at).pets[0].tasks[0]
    save = f"FormSubmitter:edit_{task.id}-Save changes"

    at.text_input(key=f"edit_title_{task.id}").set_value("Long walk")
    at.number_input(key=f"edit_dur_{task.id}").set_value(45)
    at.button(save).click().run()
    assert (task.title, task.duration_minutes) == ("Long walk", 45)
    assert owner_of(at).pets[0].tasks[0] is task  # edited in place

    at.text_input(key=f"edit_title_{task.id}").set_value("  ")
    at.button(save).click().run()
    assert task.title == "Long walk" and at.error  # rejected, task untouched


def test_done_button_completes_the_task_and_remove_button_deletes_it(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", recurrence=Recurrence.DAILY)  # daily, so completion is tied to an exact day
    pet = owner_of(at).pets[0]
    task = pet.tasks[0]
    assert at.button(key=f"done_{task.id}").disabled is False

    at.button(key=f"done_{task.id}").click().run()
    assert task.last_completed == date.today()
    assert task.is_completed(date.today())
    assert at.button(key=f"done_{task.id}").disabled is True

    at.button(key=f"remove_task_{task.id}").click().run()
    assert pet.tasks == []


# ---------- owner availability ----------


def test_owner_form_saves_the_window_and_cap_and_rejects_a_bad_window(at):
    at.time_input(key="day_start").set_value(time(7, 0))
    at.time_input(key="day_end").set_value(time(19, 0))
    at.number_input(key="limit").set_value(90)  # a number is honored directly, no checkbox to forget
    at.button(SAVE_OWNER).click().run()
    owner = owner_of(at)
    assert (owner.day_start, owner.day_end, owner.available_minutes) == (time(7), time(19), 90)

    at.number_input(key="limit").set_value(0)  # 0 means no limit
    at.button(SAVE_OWNER).click().run()
    assert owner.available_minutes is None
    at.number_input(key="limit").set_value(90)
    at.button(SAVE_OWNER).click().run()

    at.time_input(key="day_end").set_value(time(6, 0))  # before the start
    at.button(SAVE_OWNER).click().run()
    assert (owner.day_start, owner.day_end) == (time(7), time(19))  # unchanged
    assert any("day_end" in e.value for e in at.error)


# ---------- the schedule is built by the Scheduler from the live Owner ----------


def test_generate_schedule_shows_the_plan_and_stays_live_as_tasks_change(at):
    add_pet(at, "Rex")
    add_task(at, "Meds", timing="Fixed time", when=time(9, 0), duration=5)
    at.button(key="generate").click().run()

    assert any("1 scheduled" in s.value for s in at.success)
    rows = table_rows(at)
    assert [(r["task"], r["start"], r["end"], r["status"]) for r in rows] == [("Meds", "09:00", "09:05", "scheduled")]

    add_task(at, "Feeding", timing="Fixed time", when=time(12, 0), duration=10)  # no second click needed
    assert [r["task"] for r in table_rows(at)] == ["Meds", "Feeding"]


def test_schedule_covers_every_pets_tasks(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi", species="cat")
    rex, mochi = owner_of(at).pets
    add_task(at, "Walk", pet_id=rex.id, timing="Fixed time", when=time(8, 0))
    add_task(at, "Brush fur", pet_id=mochi.id, timing="Fixed time", when=time(10, 0))
    at.button(key="generate").click().run()

    assert {(r["pet"], r["task"]) for r in table_rows(at)} == {("Rex", "Walk"), ("Mochi", "Brush fur")}


def test_required_task_that_cannot_fit_is_flagged_with_a_warning(at):
    at.time_input(key="day_start").set_value(time(8, 0))
    at.time_input(key="day_end").set_value(time(8, 30))
    at.button(SAVE_OWNER).click().run()
    add_pet(at, "Rex")
    add_task(at, "Meds A", required=True)
    add_task(at, "Meds B", required=True)
    at.button(key="generate").click().run()

    assert [r["status"] for r in table_rows(at)] == ["scheduled", "FLAGGED"]
    assert any("REQUIRED" in w.value and "Meds B" in w.value for w in at.warning)


def test_minutes_limit_warns_when_tasks_exceed_it_and_the_plan_skips_the_extra_task(at):
    """Four 20-minute tasks with a 60-minute limit: all four can be added, the page warns
    once they no longer fit, and the plan schedules three and skips one."""
    at.number_input(key="limit").set_value(60)
    at.button(SAVE_OWNER).click().run()
    assert owner_of(at).available_minutes == 60
    add_pet(at, "Rex")

    for n in (1, 2, 3):
        add_task(at, f"Task {n}", duration=20)
    assert not at.warning  # 60 of 60 minutes still fits
    assert any("60 of 60" in c.value for c in at.caption)

    add_task(at, "Task 4", duration=20)
    assert len(owner_of(at).pets[0].tasks) == 4  # adding is not blocked
    assert any("80 min" in w.value and "60 min" in w.value for w in at.warning)

    at.button(key="generate").click().run()
    rows = table_rows(at)
    assert [r["status"] for r in rows] == ["scheduled", "scheduled", "scheduled", "skipped"]
    assert "60-minute daily limit" in rows[3]["reason"]
    assert any("3 scheduled (60 min), 1 skipped" in s.value for s in at.success)


def test_no_limit_means_no_warning_until_the_day_window_is_exceeded(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", duration=240)
    assert not at.warning  # the default 08:00-20:00 window is 720 minutes

    at.time_input(key="day_end").set_value(time(10, 0))  # shrink the day to 120 minutes
    at.button(SAVE_OWNER).click().run()
    assert any("240 min" in w.value and "120 min" in w.value for w in at.warning)


def test_completed_tasks_drop_out_of_the_plan(at):
    add_pet(at, "Rex")
    add_task(at, "Walk")
    task = owner_of(at).pets[0].tasks[0]
    at.button(key="generate").click().run()
    assert len(table_rows(at)) == 1

    at.button(key=f"done_{task.id}").click().run()

    assert not at.table
    assert any("Nothing is due" in i.value for i in at.info)

"""Headless tests of the Streamlit UI (app.py) using streamlit.testing.v1.AppTest.

They drive the real script the way a user would (fill a form, click a button) and
assert on the Owner object stored in st.session_state, so they check the wiring
between the UI and the classes in pawpal_system.py.
"""

import json
import re
from datetime import date, time, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import display
from pawpal_system import Owner, Priority, Recurrence

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
ADD_PET = "FormSubmitter:add_pet_form-Add pet"
ADD_TASK = "FormSubmitter:add_task_form-Add task"
SAVE_OWNER = "FormSubmitter:owner_form-Save availability"


@pytest.fixture(autouse=True)
def data_file(tmp_path, monkeypatch):
    """Every test saves to its own temporary file, so none can read or overwrite the real data.json."""
    path = tmp_path / "data.json"
    monkeypatch.setenv("PAWPAL_DATA_FILE", str(path))
    return path


@pytest.fixture
def at():
    return AppTest.from_file(APP_PATH, default_timeout=15).run()


def new_session():
    """A fresh browser session: new session state, but the same data file as before."""
    return AppTest.from_file(APP_PATH, default_timeout=15).run()


def owner_of(at):
    return at.session_state["owner"]


def add_pet(at, name, species="dog"):
    at.text_input(key="pet_name").set_value(name)
    at.selectbox(key="pet_species").set_value(species)
    at.button(ADD_PET).click().run()
    return at


def select_pet(at, pet_id):
    """Click a pet's tile (a no-op if it is already the selected one, whose button is disabled)."""
    button = at.button(key=f"select_pet_{pet_id}")
    if not button.disabled:
        button.click().run()
    return at


def add_task(at, title, *, pet_id=None, duration=20, timing=None, when=None, required=False, priority=None,
             recurrence=None):
    if pet_id is not None:
        select_pet(at, pet_id)  # tasks go to the pet whose tile is selected
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


_PLAIN_STATUS = {display.STATUS_SCHEDULED: "scheduled", display.STATUS_SKIPPED: "skipped", display.STATUS_FLAGGED: "FLAGGED"}


def _without_icon(cell):
    """'💊 Heart medication' -> 'Heart medication' (the tables show an emoji before the text)."""
    return re.sub(r"^\S+\s", "", cell)


def tables(at):
    """One list of rows per table on the page (the schedule first, then 'Not scheduled'), with the
    emoji decoration removed so tests can compare plain values. Decoration has its own tests."""
    result = []
    for table in at.table:
        rows = []
        for row in table.value.to_dict("records"):
            start, _, end = row.get("Time", "").partition("–")
            rows.append({
                "status": _PLAIN_STATUS[row["Status"]], "start": start, "end": end,
                "pet": _without_icon(row["Pet"]), "task": _without_icon(row["Task"]),
                "minutes": int(row["Min"]), "priority": _without_icon(row["Priority"]).lower(), "reason": row["Why"],
            })
        result.append(rows)
    return result


def table_rows(at):
    """Every table row on the page, in order."""
    return [row for rows in tables(at) for row in rows]


def metrics(at):
    """The totals shown above a plan, as {label: displayed value}."""
    return {m.label: m.value for m in at.metric}


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
    assert any("Mochi" in m.value for m in at.markdown)  # the pet's tile shows it
    assert at.button(key=f"select_pet_{pet.id}").disabled  # and it is already selected, so tasks can be added


# ---------- pets are shown as tiles ----------


def test_pets_are_shown_as_tiles_not_as_a_dropdown(at):
    for name in ("Rex", "Mochi", "Kiwi", "Biscuit"):  # four pets wrap onto a second row
        add_pet(at, name)
    pets = owner_of(at).pets

    for pet in pets:
        assert f"select_pet_{pet.id}" in [b.key for b in at.button]  # one tile (with a Select button) per pet
        assert f"remove_pet_{pet.id}" in [b.key for b in at.button]
    pet_names = {p.name for p in pets}
    for selectbox in at.selectbox:  # no remaining dropdown lists the pets
        assert not pet_names & set(selectbox.options), selectbox.key
    assert "task_pet" not in [s.key for s in at.selectbox] and "filter_pet" not in [s.key for s in at.selectbox]


def test_tiles_show_icon_details_and_open_and_done_counts(at):
    add_pet(at, "Mochi", species="cat")
    mochi = owner_of(at).pets[0]
    mochi.breed, mochi.age = "Siamese", 2
    add_task(at, "Brush")
    add_task(at, "Play")
    at.button(key=f"done_{mochi.tasks[0].id}").click().run()

    headings = [m.value for m in at.markdown if m.value.startswith("###")]
    assert any("🐱" in h and "Mochi" in h for h in headings)
    assert any("cat" in c.value and "Siamese" in c.value and "2 yr" in c.value for c in at.caption)
    assert any(m.value == "1 open · 1 done" for m in at.markdown)

    add_pet(at, "Kiwi", species="other")
    assert any("🐾" in m.value and "Kiwi" in m.value for m in at.markdown if m.value.startswith("###"))


def test_a_new_pet_is_selected_and_clicking_a_tile_changes_which_pet_gets_tasks(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi", species="cat")
    rex, mochi = owner_of(at).pets
    assert at.session_state["selected_pet_id"] == mochi.id  # the newest pet is selected
    assert at.button(key=f"select_pet_{mochi.id}").disabled and not at.button(key=f"select_pet_{rex.id}").disabled
    assert any("Adding a task for **Mochi**" in m.value for m in at.markdown)

    at.button(key=f"select_pet_{rex.id}").click().run()

    assert at.session_state["selected_pet_id"] == rex.id
    assert at.button(key=f"select_pet_{rex.id}").disabled and not at.button(key=f"select_pet_{mochi.id}").disabled
    assert any("Adding a task for **Rex**" in m.value for m in at.markdown)
    add_task(at, "Walk")
    assert [t.title for t in rex.tasks] == ["Walk"] and mochi.tasks == []


def test_removing_the_selected_tile_selects_another_pet(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi")
    rex, mochi = owner_of(at).pets
    assert at.session_state["selected_pet_id"] == mochi.id

    at.button(key=f"remove_pet_{mochi.id}").click().run()

    assert [p.name for p in owner_of(at).pets] == ["Rex"]
    assert at.session_state["selected_pet_id"] == rex.id  # fell back to the remaining pet
    assert at.button(key=f"select_pet_{rex.id}").disabled


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


def test_done_button_completes_a_daily_task_and_creates_the_next_occurrence(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", recurrence=Recurrence.DAILY)
    pet = owner_of(at).pets[0]
    task = pet.tasks[0]
    assert at.button(key=f"done_{task.id}").disabled is False

    at.button(key=f"done_{task.id}").click().run()

    assert task.completed_on == date.today() and task.is_completed()
    assert len(pet.tasks) == 2  # the new occurrence was added to the pet
    nxt = pet.tasks[1]
    assert nxt.start_date == date.today() + timedelta(days=1) and not nxt.is_completed()
    assert any("next one is due" in s.value for s in at.success)
    keys = [b.key for b in at.button]
    assert f"done_{task.id}" not in keys and f"done_{nxt.id}" in keys  # the default "Open" filter hides the finished one

    at.radio(key="filter_status").set_value("Done").run()
    assert at.button(key=f"done_{task.id}").disabled is True  # it shows under "Done", already completed


def test_done_button_on_a_one_off_task_creates_nothing_and_remove_deletes_a_task(at):
    add_pet(at, "Rex")
    add_task(at, "Vet visit")
    pet = owner_of(at).pets[0]
    task = pet.tasks[0]

    at.button(key=f"done_{task.id}").click().run()
    assert task.is_completed() and len(pet.tasks) == 1  # no next occurrence

    at.radio(key="filter_status").set_value("All").run()
    at.button(key=f"remove_task_{task.id}").click().run()
    assert pet.tasks == []


# ---------- sorting, filtering and conflict warnings in the UI ----------


def bold_title(markdown):
    """The text between the first pair of ** in a task row (the task's title)."""
    match = re.search(r"\*\*(.+?)\*\*", markdown)
    assert match, f"no bold title in {markdown!r}"
    return match.group(1)


def listed_titles(at):
    """Titles of the task-list rows, in the order shown."""
    return [bold_title(m.value) for m in at.markdown
            if " min," in m.value and "**" in m.value and not m.value.startswith("#")]


def test_task_list_is_sorted_by_time_with_untimed_tasks_last(at):
    add_pet(at, "Rex")
    add_task(at, "Evening", timing="Preferred time", when=time(18, 0))
    add_task(at, "Anytime")
    add_task(at, "Noon", timing="Fixed time", when=time(12, 0))
    add_task(at, "Early", timing="Fixed time", when=time(7, 0))

    assert listed_titles(at) == ["Early", "Noon", "Evening", "Anytime"]


def test_task_list_can_be_filtered_by_pet_and_by_status(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi", species="cat")
    rex, mochi = owner_of(at).pets
    add_task(at, "Walk", pet_id=rex.id)
    add_task(at, "Brush", pet_id=mochi.id)
    at.button(key=f"done_{rex.tasks[0].id}").click().run()
    assert sorted(listed_titles(at)) == ["Brush"]  # default: open tasks only

    at.radio(key="filter_status").set_value("All").run()
    assert sorted(listed_titles(at)) == ["Brush", "Walk"]

    select_pet(at, rex.id)
    assert at.radio(key="filter_scope").options == ["All pets", "Rex only"]  # named after the selected tile
    at.radio(key="filter_scope").set_value("selected").run()
    assert listed_titles(at) == ["Walk"]

    at.radio(key="filter_status").set_value("Open").run()
    assert listed_titles(at) == [] and any("No tasks to show" in c.value for c in at.caption)


def test_overlapping_fixed_time_tasks_show_a_conflict_warning_before_planning(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi", species="cat")
    rex, mochi = owner_of(at).pets
    add_task(at, "Walk", pet_id=rex.id, timing="Fixed time", when=time(9, 0), duration=30)
    assert not any("Conflict" in w.value for w in at.warning)

    add_task(at, "Brush", pet_id=mochi.id, timing="Fixed time", when=time(9, 15), duration=15)  # overlaps, other pet

    conflicts = [w.value for w in at.warning if "Conflict" in w.value]
    assert len(conflicts) == 1 and "different pets" in conflicts[0]
    assert "'Walk'" in conflicts[0] and "'Brush'" in conflicts[0]
    assert len(owner_of(at).get_all_tasks()) == 2  # a warning, not a refusal


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

    assert metrics(at) == {"Scheduled": "1", "Care minutes": "5 / 720", "Not scheduled": "0"}
    assert any("Everything fits" in s.value for s in at.success)
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
    assert any("Required task not scheduled" in e.value and "Meds B" in e.value for e in at.error)  # red, not amber
    assert not at.success  # not "everything fits"


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
    assert metrics(at) == {"Scheduled": "3", "Care minutes": "60 / 60", "Not scheduled": "1"}
    assert any("Did not fit today" in i.value and "Task 4" in i.value for i in at.info)


def test_no_limit_means_no_warning_until_the_day_window_is_exceeded(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", duration=240)
    assert not at.warning  # the default 08:00-20:00 window is 720 minutes

    at.time_input(key="day_end").set_value(time(10, 0))  # shrink the day to 120 minutes
    at.button(SAVE_OWNER).click().run()
    assert any("240 min" in w.value and "120 min" in w.value for w in at.warning)


def test_a_pet_with_no_tasks_shows_zero_counts_and_an_empty_schedule_message(at):
    add_pet(at, "Rex")
    assert any(m.value == "0 open · 0 done" for m in at.markdown)

    at.button(key="generate").click().run()

    assert not at.exception and not at.table
    assert any("Nothing is due" in i.value for i in at.info)


def test_generating_a_schedule_with_no_pets_at_all_does_not_crash(at):
    at.button(key="generate").click().run()

    assert not at.exception and not at.table
    assert any("Nothing is due" in i.value for i in at.info)


def test_a_clash_is_shown_as_an_amber_warning_that_says_what_happened_and_what_to_do(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi", species="cat")
    rex, mochi = owner_of(at).pets
    add_task(at, "Lunch", pet_id=rex.id, timing="Fixed time", when=time(12, 0), duration=10, priority=Priority.HIGH)
    add_task(at, "Vet call", pet_id=mochi.id, timing="Fixed time", when=time(12, 0), duration=15)

    # right after adding: the warning plus a plain-language explanation of the consequence and the fix
    assert any("Conflict" in w.value for w in at.warning)
    assert any("keeps the more important task" in c.value and "Edit one task's time" in c.value for c in at.caption)

    at.button(key="generate").click().run()

    clash = [w.value for w in at.warning if "Time clash, not scheduled" in w.value]
    assert len(clash) == 1 and "Vet call" in clash[0] and "Mochi" in clash[0]  # names the task that lost out
    assert "clashes with 'Lunch'" in clash[0] and "Edit its time" in clash[0]  # the cause and the fix
    assert not at.error and not any("Everything fits" in s.value for s in at.success)
    assert metrics(at) == {"Scheduled": "1", "Care minutes": "10 / 720", "Not scheduled": "1"}


def test_the_schedule_and_the_not_scheduled_tasks_are_shown_in_separate_tables(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", timing="Fixed time", when=time(9, 0), duration=30)
    add_task(at, "Bath", timing="Fixed time", when=time(9, 10), duration=20)  # overlaps the walk
    at.button(key="generate").click().run()

    assert len(at.table) == 2
    scheduled, skipped = tables(at)
    # Same priority, so the shorter task is placed first and keeps the slot; the longer one is skipped.
    assert [(r["task"], r["status"]) for r in scheduled] == [("Bath", "scheduled")]
    assert [(r["task"], r["status"]) for r in skipped] == [("Walk", "skipped")]
    assert "clashes with 'Bath'" in skipped[0]["reason"]


def test_when_everything_fits_the_plan_says_so_with_no_warnings_or_extra_table(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", duration=20)
    add_task(at, "Feed", duration=10)
    at.button(key="generate").click().run()

    assert any("Everything fits: all 2 tasks are scheduled." in s.value for s in at.success)
    assert not at.warning and not at.error and len(at.table) == 1
    assert any("Schedule for" in m.value for m in at.markdown)


def test_the_task_list_says_it_is_sorted_by_time(at):
    add_pet(at, "Rex")
    assert any("Sorted by time" in c.value for c in at.caption)


# ---------- sample data ----------


def test_the_sample_data_button_fills_an_empty_app_and_then_goes_away(at):
    assert "load_sample" in [b.key for b in at.button]

    at.button(key="load_sample").click().run()

    owner = owner_of(at)
    assert [p.name for p in owner.pets] == ["Biscuit", "Mochi"] and len(owner.get_all_tasks()) == 8
    assert any("Loaded sample data" in s.value for s in at.success)
    assert "load_sample" not in [b.key for b in at.button]  # only offered while the app is empty
    assert any("Conflict" in w.value for w in at.warning)  # the sample deliberately includes a clash

    at.button(key="generate").click().run()
    assert not at.exception and metrics(at)["Not scheduled"] == "1"  # the clash leaves one task out


def test_completed_tasks_drop_out_of_the_plan(at):
    add_pet(at, "Rex")
    add_task(at, "Walk")
    task = owner_of(at).pets[0].tasks[0]
    at.button(key="generate").click().run()
    assert len(table_rows(at)) == 1

    at.button(key=f"done_{task.id}").click().run()

    assert not at.table
    assert any("Nothing is due" in i.value for i in at.info)


# =====================================================================
# Challenge 2: pets and tasks are remembered between runs (data.json)
# =====================================================================


def assert_saved(at, data_file):
    """What is on disk is exactly what the app is holding."""
    assert Owner.load_from_json(data_file) == owner_of(at)


def test_an_untouched_app_does_not_create_a_data_file(at, data_file):
    assert not data_file.exists()


def test_changes_are_saved_automatically_and_a_new_session_loads_them(at, data_file):
    add_pet(at, "Rex")
    add_task(at, "Walk", timing="Fixed time", when=time(9, 0), required=True)
    assert data_file.is_file()
    assert_saved(at, data_file)

    fresh = new_session()  # like closing the browser and coming back

    assert [p.name for p in owner_of(fresh).pets] == ["Rex"]
    assert [(t.title, t.fixed_time, t.required) for t in owner_of(fresh).pets[0].tasks] == [("Walk", time(9), True)]
    assert any("Loaded 1 pet(s) and 1 task(s)" in s.value for s in fresh.success)
    assert owner_of(fresh) == owner_of(at)  # identical, ids included


def test_every_kind_of_change_is_saved(at, data_file):
    add_pet(at, "Rex")
    add_task(at, "Walk", recurrence=Recurrence.DAILY)
    task = owner_of(at).pets[0].tasks[0]
    assert_saved(at, data_file)

    at.text_input(key=f"edit_title_{task.id}").set_value("Long walk")  # an edit
    at.button(f"FormSubmitter:edit_{task.id}-Save changes").click().run()
    assert_saved(at, data_file)
    assert Owner.load_from_json(data_file).pets[0].tasks[0].title == "Long walk"

    at.button(key=f"done_{task.id}").click().run()  # a completion, which also creates the next occurrence
    assert_saved(at, data_file)
    assert len(Owner.load_from_json(data_file).pets[0].tasks) == 2

    at.time_input(key="day_end").set_value(time(18, 0))  # the owner's hours
    at.button(SAVE_OWNER).click().run()
    assert_saved(at, data_file)
    assert Owner.load_from_json(data_file).day_end == time(18)

    at.button(key=f"remove_pet_{owner_of(at).pets[0].id}").click().run()  # a removal
    assert_saved(at, data_file)
    assert Owner.load_from_json(data_file).pets == []


def test_the_sample_data_is_saved_too(at, data_file):
    at.button(key="load_sample").click().run()
    assert_saved(at, data_file)
    assert len(Owner.load_from_json(data_file).get_all_tasks()) == 8


def test_opening_the_app_with_saved_data_does_not_rewrite_the_file(at, data_file):
    add_pet(at, "Rex")
    before = data_file.stat().st_mtime_ns

    new_session()

    assert data_file.stat().st_mtime_ns == before  # loading is not a change, so nothing is saved


@pytest.mark.parametrize("contents", ["{ not json at all", '{"version": 1, "owner": {}}'])
def test_a_damaged_data_file_is_set_aside_and_never_overwritten(at, data_file, contents):
    data_file.write_text(contents, encoding="utf-8")

    fresh = new_session()

    assert any("Could not read data.json" in e.value and "data.json.damaged" in e.value for e in fresh.error)
    assert owner_of(fresh).pets == []  # started empty
    aside = data_file.with_name("data.json.damaged")
    assert aside.read_text(encoding="utf-8") == contents and not data_file.exists()  # kept for inspection

    add_pet(fresh, "Rex")  # saving after that must not touch the set-aside copy
    assert Owner.load_from_json(data_file).pets[0].name == "Rex"
    assert aside.read_text(encoding="utf-8") == contents


def test_clearing_all_data_needs_a_confirmation_and_empties_the_saved_file(at, data_file):
    add_pet(at, "Rex")
    assert at.button(key="clear_all").disabled  # not until the box is ticked

    at.checkbox(key="confirm_clear").check().run()
    assert not at.button(key="clear_all").disabled
    at.button(key="clear_all").click().run()

    assert owner_of(at).pets == []
    assert Owner.load_from_json(data_file).pets == []
    assert any("cleared" in s.value for s in at.success)
    assert new_session().session_state["owner"].pets == []


def test_a_location_that_cannot_be_written_shows_a_warning_and_the_app_keeps_working(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so nothing can be created inside it")
    monkeypatch.setenv("PAWPAL_DATA_FILE", str(blocker / "data.json"))
    at = new_session()

    add_pet(at, "Rex")

    assert any("Could not save to data.json" in w.value for w in at.warning)
    assert [p.name for p in owner_of(at).pets] == ["Rex"]  # the session still has the data


# =====================================================================
# Challenge 1: next available slot
# =====================================================================


def slot_messages(at):
    return [m.value for m in at.success if "Next free" in m.value] + [m.value for m in at.info if "No free slot" in m.value]


def test_the_free_slot_helper_offers_the_start_of_the_day_when_nothing_is_planned(at):
    add_pet(at, "Rex")
    assert any("Next free 20-minute slot today: **08:00–08:20**" in m for m in slot_messages(at))


def test_the_free_slot_helper_steps_around_planned_tasks_and_follows_its_inputs(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", timing="Fixed time", when=time(8, 0), duration=30)

    assert any("08:30–08:50" in m for m in slot_messages(at))
    at.number_input(key="slot_minutes").set_value(45).run()
    assert any("Next free 45-minute slot today: **08:30–09:15**" in m for m in slot_messages(at))
    at.time_input(key="slot_after").set_value(time(10, 0)).run()
    assert any("**10:00–10:45**" in m for m in slot_messages(at))


def test_the_free_slot_helper_says_so_when_there_is_no_room(at):
    at.number_input(key="limit").set_value(30)
    at.button(SAVE_OWNER).click().run()
    add_pet(at, "Rex")
    add_task(at, "Walk", duration=30)

    assert any("No free slot of that length is left today" in m for m in slot_messages(at))


def test_a_clash_message_suggests_the_next_free_slot_after_the_time_it_wanted(at):
    add_pet(at, "Rex")
    add_pet(at, "Mochi", species="cat")
    rex, mochi = owner_of(at).pets
    add_task(at, "Lunch", pet_id=rex.id, timing="Fixed time", when=time(12, 0), duration=10, priority=Priority.HIGH)
    add_task(at, "Vet call", pet_id=mochi.id, timing="Fixed time", when=time(12, 0), duration=15)

    at.button(key="generate").click().run()

    clash = next(w.value for w in at.warning if "Time clash, not scheduled" in w.value)
    assert "The next free 15-minute slot after 12:00 is 12:10–12:25." in clash  # after the lunch, not 08:00


def test_a_required_task_that_is_left_out_also_gets_a_suggestion(at):
    at.time_input(key="day_end").set_value(time(8, 30))
    at.button(SAVE_OWNER).click().run()
    add_pet(at, "Rex")
    add_task(at, "Meds A", required=True, duration=20)
    add_task(at, "Meds B", required=True, duration=20)
    at.button(key="generate").click().run()

    error = next(e.value for e in at.error if "Required task not scheduled" in e.value)
    assert "No free 20-minute slot is left that day." in error


# =====================================================================
# Challenge 3: emoji, colour-coded badges and tables
# =====================================================================


def test_task_rows_show_a_category_emoji_a_priority_badge_and_a_red_required_tag(at):
    add_pet(at, "Rex")
    at.selectbox(key="task_category").set_value(display.Category.MEDS)
    add_task(at, "Heart meds", timing="Fixed time", when=time(8, 0), required=True, priority=Priority.HIGH)

    row = next(m.value for m in at.markdown if "Heart meds" in m.value and " min," in m.value)

    assert row.startswith("💊 **Heart meds**")
    assert "🔴 High" in row and ":red[**REQUIRED**]" in row and "fixed 08:00" in row


def test_the_category_and_priority_choices_show_their_emoji(at):
    add_pet(at, "Rex")
    assert "💊 Meds" in at.selectbox(key="task_category").options
    assert "🔴 High" in at.selectbox(key="task_priority").options


def test_status_is_colour_coded_green_when_done_blue_when_later_and_red_when_overdue(at):
    add_pet(at, "Rex")
    today = date.today()
    at.date_input(key="task_start").set_value(today - timedelta(days=2))
    add_task(at, "Overdue one")
    at.date_input(key="task_start").set_value(today + timedelta(days=3))
    add_task(at, "Later one")
    add_task(at, "Finished one")
    finished = owner_of(at).pets[0].tasks[2]
    at.button(key=f"done_{finished.id}").click().run()
    at.radio(key="filter_status").set_value("All").run()

    rows = {bold_title(m.value): m.value for m in at.markdown if " min," in m.value and "**" in m.value}

    assert ":red[❗ overdue since" in rows["Overdue one"]
    assert ":blue[⏳ starts" in rows["Later one"]
    assert ":green[✅ done" in rows["Finished one"]


def test_the_plan_tables_are_decorated_with_status_emoji_and_priority_badges(at):
    add_pet(at, "Rex")
    add_task(at, "Walk", timing="Fixed time", when=time(9, 0), duration=30, priority=Priority.HIGH)
    add_task(at, "Bath", timing="Fixed time", when=time(9, 10), duration=20)  # clashes, so one is skipped
    at.button(key="generate").click().run()

    scheduled, skipped = (t.value.to_dict("records") for t in at.table)

    assert scheduled[0]["Status"] == display.STATUS_SCHEDULED and scheduled[0]["Time"] == "09:00–09:30"
    walk = display.category_icon(display.Category.WALK)  # the form's category defaults to its first choice, Walk
    assert scheduled[0]["Task"] == f"{walk} Walk" and scheduled[0]["Priority"] == "🔴 High"
    assert skipped[0]["Status"] == display.STATUS_SKIPPED and skipped[0]["Task"] == f"{walk} Bath"
    assert any(w.icon == display.CLASH_ICON for w in at.warning)  # Streamlit shows a leading emoji as the alert's icon

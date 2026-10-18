"""PawPal+ Streamlit UI.

All planning logic lives in pawpal_system.py. This file only collects input,
calls those classes, and shows the result.
"""

import json
import os
from datetime import date, time
from pathlib import Path

import streamlit as st

import display
from main import build_owner as build_sample_owner  # the same sample data the command-line demo uses
from pawpal_system import Category, DailyPlan, Owner, Pet, Priority, Recurrence, Scheduler, Task

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="wide")

SPECIES = ["dog", "cat", "other"]
TILES_PER_ROW = 3
TIMING_MODES = ["Flexible (earliest free slot)", "Preferred time", "Fixed time"]


def data_file() -> Path:
    """Where pets and tasks are saved: data.json next to app.py, or the file named by PAWPAL_DATA_FILE."""
    return Path(os.environ.get("PAWPAL_DATA_FILE") or Path(__file__).resolve().parent / "data.json")


def snapshot(owner: Owner) -> str:
    """The owner's data as text, used to notice whether anything changed since the last save."""
    return json.dumps(owner.to_dict(), sort_keys=True)


def load_saved_owner() -> Owner:
    """The owner saved last time, or a new empty one. A damaged file is set aside, never overwritten."""
    path = data_file()
    try:
        owner = Owner.load_from_json(path)
    except FileNotFoundError:
        return Owner("Jordan")  # first run: nothing saved yet
    except ValueError as err:
        aside = path.with_name(path.name + ".damaged")
        os.replace(path, aside)  # keep the bad file for inspection so the next save cannot destroy it
        st.session_state.load_problem = f"Could not read {path.name} ({err}). It was kept as {aside.name} and the app started empty."
        return Owner("Jordan")
    except OSError as err:
        st.session_state.load_problem = f"Could not open {path.name} ({err}). The app started empty."
        return Owner("Jordan")
    if owner.pets:
        flash(f"{display.SAVED_ICON} Loaded {len(owner.pets)} pet(s) and {len(owner.get_all_tasks())} task(s) from {path.name}.")
    return owner


def get_owner() -> Owner:
    """The Owner for this browser session, loaded from disk on first use.

    Streamlit re-runs this whole script on every click, so a plain `Owner(...)`
    here would be rebuilt empty each time. `st.session_state` behaves like a
    dictionary that survives re-runs: if the key is already there we reuse the
    stored object, otherwise we load it once (from data.json if it exists).
    """
    if "owner" not in st.session_state:
        st.session_state.owner = load_saved_owner()
        st.session_state.saved_snapshot = snapshot(st.session_state.owner)  # nothing to save until it changes
    return st.session_state.owner


def autosave(owner: Owner) -> None:
    """Save to data.json if anything changed. Called at the end of every run, so every change is kept
    whether it came from a form, a button callback or the sample-data button."""
    current = snapshot(owner)
    if current == st.session_state.get("saved_snapshot"):
        return
    try:
        owner.save_to_json(data_file())
    except OSError as err:
        st.warning(f"Could not save to {data_file().name}: {err}")
    else:
        st.session_state.saved_snapshot = current


def clear_all() -> None:
    """Button callback: forget every pet and task (the next autosave writes the empty state)."""
    st.session_state.owner = Owner("Jordan")
    st.session_state.selected_pet_id = None
    st.session_state.show_plan = False
    st.session_state.confirm_clear = False
    flash("All pets and tasks were cleared.")


def flash(message: str) -> None:
    """Remember a success message across the `st.rerun()` that follows an action."""
    st.session_state.flash = message


def rerun_after(message: str) -> None:
    """Show `message` after the page refreshes, so every list reflects the change."""
    flash(message)
    st.rerun()


def selected_pet(owner: Owner) -> Pet | None:
    """The pet whose tile is selected, falling back to the first pet if that one was removed."""
    ids = [p.id for p in owner.pets]
    if st.session_state.get("selected_pet_id") not in ids:
        st.session_state.selected_pet_id = ids[0] if ids else None
    return next((p for p in owner.pets if p.id == st.session_state.selected_pet_id), None)


def select_pet(pet_id: str) -> None:
    """Button callback: make the tile for `pet_id` the selected one."""
    st.session_state.selected_pet_id = pet_id


def pet_tile(owner: Owner, pet: Pet, is_selected: bool) -> None:
    """One bordered tile: icon, name, details, task counts, and Select / Remove buttons."""
    done = sum(1 for t in pet.tasks if t.is_completed())
    details = " · ".join(x for x in [pet.species, pet.breed, f"{pet.age} yr" if pet.age is not None else ""] if x)
    # The key lets the CSS below highlight the selected tile.
    with st.container(border=True, key=f"tile-{'selected-' if is_selected else ''}{pet.id}"):
        st.markdown(f"### {display.pet_icon(pet.species)} {pet.name}")
        st.caption(details)
        st.write(f"{len(pet.tasks) - done} open · {done} done")
        st.button("✓ Selected" if is_selected else "Select", key=f"select_pet_{pet.id}",
                  type="primary" if is_selected else "secondary", disabled=is_selected,
                  on_click=select_pet, args=(pet.id,), width="stretch")
        # on_click callbacks run before the next re-run, so the page redraws already updated.
        st.button("Remove", key=f"remove_pet_{pet.id}", type="tertiary", on_click=owner.remove_pet,
                  args=(pet.id,), width="stretch")


def load_sample() -> None:
    """Button callback: replace the empty owner with the demo owner (two pets, eight tasks)."""
    sample = build_sample_owner()
    st.session_state.owner = sample
    st.session_state.selected_pet_id = sample.pets[0].id
    flash("Loaded sample data: two pets and eight tasks, including two that clash at 12:00.")


def slot_hint(scheduler: Scheduler, plan: DailyPlan, task: Task) -> str:
    """A sentence suggesting where a task that lost out could go: the next free slot of its length on the
    plan's day, searching after the time it asked for (if it asked for one), or saying there is none."""
    minutes, after = task.duration_minutes, task.fixed_time
    slot = scheduler.next_available_slot(plan.on, minutes, not_before=after)
    where = f" after {after:%H:%M}" if after is not None else ""
    if slot is None:
        return f"{display.SLOT_ICON} No free {minutes}-minute slot is left{where or ' that day'}."
    return f"{display.SLOT_ICON} The next free {minutes}-minute slot{where} is {slot[0]:%H:%M}–{slot[1]:%H:%M}."


def show_plan(plan: DailyPlan, owner: Owner) -> None:
    """Show a plan: totals, then problems (most serious first), then the schedule and what was skipped."""
    scheduler = Scheduler(owner)
    m_scheduled, m_minutes, m_skipped = st.columns(3)
    m_scheduled.metric("Scheduled", len(plan.scheduled_items))
    m_minutes.metric("Care minutes", f"{plan.total_minutes()} / {owner.capacity_minutes()}")
    m_skipped.metric("Not scheduled", len(plan.skipped_tasks))

    # Most serious first: a required task left out is red, a clash is amber, a task that simply did not fit is blue.
    for skipped in plan.flagged_tasks():
        st.error(f"{display.STATUS_FLAGGED.split()[0]} **Required task not scheduled:** {skipped.task.title} "
                 f"({skipped.pet.name}). {skipped.reason} {slot_hint(scheduler, plan, skipped.task)}")
    clashes = [s for s in plan.skipped_tasks if not s.flagged and s.task.fixed_time is not None]
    for skipped in clashes:
        st.warning(f"{display.CLASH_ICON} **Time clash, not scheduled:** {skipped.task.title} ({skipped.pet.name}). "
                   f"{skipped.reason}. Edit its time, or the other task's, to keep both. "
                   f"{slot_hint(scheduler, plan, skipped.task)}")
    did_not_fit = [s for s in plan.skipped_tasks if not s.flagged and s.task.fixed_time is None]
    if did_not_fit:
        st.info("**Did not fit today:**\n" + "\n".join(f"- {s.task.title} ({s.pet.name}): {s.reason}" for s in did_not_fit))
    if not plan.skipped_tasks:
        st.success(f"{display.DONE_ICON} Everything fits: all {len(plan.scheduled_items)} tasks are scheduled.")

    if plan.scheduled_items:
        st.table(display.schedule_rows(plan))  # already in chronological order
    else:
        st.caption("Nothing could be scheduled.")
    if plan.skipped_tasks:
        st.markdown("**Not scheduled**")
        st.table(display.not_scheduled_rows(plan))
    with st.expander("Why this plan?"):
        st.code(plan.explain(), language=None)


def complete_task(task_id: str) -> None:
    """Button callback: complete a task today; a daily or weekly one gets its next occurrence."""
    next_task = Scheduler(get_owner()).mark_task_complete(task_id, date.today())
    flash(f"Done. The next one is due {next_task.start_date:%A, %B %d}." if next_task else "Done.")


def describe_task(task: Task, today: date) -> str:
    """One line for the task list: category emoji, title, colour-coded status, then the details."""
    parts = [f"{task.duration_minutes} min", display.priority_badge(task.priority), task.category.value]
    if task.required:
        parts.append(":red[**REQUIRED**]")
    parts.append(display.when_text(task))
    if task.recurrence is not Recurrence.ONCE:
        parts.append(display.repeats_text(task))
    status = display.task_status_markdown(task, today)
    status = "" if status == "due today" else f" {status}"
    return f"{display.category_icon(task.category)} **{task.title}**{status} - " + ", ".join(parts)


owner = get_owner()
today = date.today()

st.title("🐾 PawPal+")
st.caption("Add your pets and their care tasks, then generate a plan for the day.")

if "load_problem" in st.session_state:
    st.error(st.session_state.pop("load_problem"))
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# ---------------------------------------------------------------- owner
with st.expander("Owner and availability", expanded=not owner.pets):
    with st.form("owner_form"):
        owner_name = st.text_input("Owner name", value=owner.name, key="owner_name")
        col_start, col_end = st.columns(2)
        day_start = col_start.time_input("Day starts", value=owner.day_start, key="day_start")
        day_end = col_end.time_input("Day ends", value=owner.day_end, key="day_end")
        limit = st.number_input(
            "Max care minutes per day (0 = no limit)", min_value=0, max_value=1440,
            value=owner.available_minutes or 0, key="limit",
            help="Caps the total minutes the plan schedules each day. Lower-priority tasks that do not fit are skipped.",
        )
        saved = st.form_submit_button("Save availability")
    if saved:
        try:
            if not owner_name.strip():
                raise ValueError("owner name must not be empty")
            owner.set_availability(day_start, day_end, int(limit) or None)
            owner.name = owner_name.strip()
        except ValueError as err:
            st.error(str(err))
        else:
            rerun_after("Availability saved.")

# ---------------------------------------------------------------- pets
st.subheader("Pets")
with st.form("add_pet_form", clear_on_submit=True):
    c_name, c_species, c_breed, c_age = st.columns([3, 2, 3, 2])
    pet_name = c_name.text_input("Pet name", key="pet_name")
    species = c_species.selectbox("Species", SPECIES, key="pet_species")
    breed = c_breed.text_input("Breed (optional)", key="pet_breed")
    age = c_age.number_input("Age (years)", min_value=0, max_value=40, value=1, key="pet_age")
    add_pet = st.form_submit_button("Add pet")
if add_pet:
    try:
        clean_name = pet_name.strip()
        if any(p.name.lower() == clean_name.lower() for p in owner.pets):
            raise ValueError(f"you already have a pet named {clean_name!r}")
        new_pet = Pet(clean_name, species, breed=breed.strip(), age=int(age))
        owner.add_pet(new_pet)
    except ValueError as err:
        st.error(str(err))
    else:
        select_pet(new_pet.id)  # so its tasks can be added straight away
        rerun_after(f"Added {clean_name}.")

# Highlight the selected tile (containers get a CSS class from their key).
st.markdown(
    "<style>[class*='st-key-tile-selected'] {border: 2px solid #ff4b4b !important; border-radius: 0.6rem;}</style>",
    unsafe_allow_html=True,
)
current_pet = selected_pet(owner)
if not owner.pets:
    st.info("No pets yet. Add one above, or try the app with ready-made sample data.")
    st.button("Load sample data", key="load_sample", on_click=load_sample)
else:
    st.caption("Select a pet's tile to add tasks for it.")
for row_start in range(0, len(owner.pets), TILES_PER_ROW):
    for column, pet in zip(st.columns(TILES_PER_ROW), owner.pets[row_start:row_start + TILES_PER_ROW]):
        with column:
            pet_tile(owner, pet, is_selected=current_pet is not None and pet.id == current_pet.id)

# ---------------------------------------------------------------- tasks
st.subheader("Tasks")
if not owner.pets:
    st.info("Add a pet first, then you can give it tasks.")
else:
    # Adding tasks is never blocked (the cap limits what gets scheduled, not what you
    # may record), so say so up front when today's tasks will not all fit.
    scheduler = Scheduler(owner)
    due_minutes = sum(pt.task.duration_minutes for pt in scheduler.filter_due_tasks(today))
    capacity = owner.capacity_minutes()
    if due_minutes > capacity:
        st.warning(
            f"Today's tasks add up to {due_minutes} min, but only {capacity} min are available "
            f"(see Owner and availability). The plan will skip the lowest-priority tasks that do not fit, "
            f"and flag any required task that cannot be scheduled."
        )
    elif due_minutes:
        st.caption(f"Today: {due_minutes} of {capacity} available minutes are planned.")
    conflicts = scheduler.find_conflicts(today)  # fixed-time tasks that overlap, for any pets
    for conflict in conflicts:
        st.warning(conflict)
    if conflicts:
        st.caption("You cannot do two things at once, so the schedule keeps the more important task and lists the "
                   "other as not scheduled. Edit one task's time below to keep both.")

    with st.expander(f"{display.SLOT_ICON} Find a free slot"):
        c_len, c_after = st.columns(2)
        slot_minutes = int(c_len.number_input("Length (minutes)", min_value=1, max_value=240, value=20, key="slot_minutes"))
        slot_after = c_after.time_input("Not before", value=owner.day_start, key="slot_after")
        slot = scheduler.next_available_slot(today, slot_minutes, not_before=slot_after)
        if slot is None:
            st.info("No free slot of that length is left today. Check the day's hours and the daily limit.")
        else:
            st.success(f"Next free {slot_minutes}-minute slot today: **{slot[0]:%H:%M}–{slot[1]:%H:%M}**")

    assert current_pet is not None  # there is at least one pet in this branch
    st.markdown(f"Adding a task for **{current_pet.name}** (select another pet's tile above to change this).")
    with st.form("add_task_form", clear_on_submit=True):
        title = st.text_input("Task title", value="Morning walk", key="task_title")
        description = st.text_input("Description (optional)", key="task_description")
        c1, c2, c3 = st.columns(3)
        duration = c1.number_input("Duration (minutes)", min_value=1, max_value=240, value=20, key="task_duration")
        priority = c2.selectbox(
            "Priority", list(Priority), index=list(Priority).index(Priority.MEDIUM),
            format_func=display.priority_badge, key="task_priority",
        )
        category = c3.selectbox("Category", list(Category), key="task_category",
                                format_func=lambda c: f"{display.category_icon(c)} {c.value.title()}")
        c4, c5, c6 = st.columns(3)
        recurrence = c4.selectbox("Repeats", list(Recurrence), format_func=lambda r: r.value.title(), key="task_repeat")
        start_date = c5.date_input("Starts on", value=today, key="task_start")
        required = c6.checkbox("Required (e.g. medication)", key="task_required")
        timing = st.radio("When", TIMING_MODES, horizontal=True, key="task_timing")
        when = st.time_input("Time (used for Preferred / Fixed)", value=time(8, 0), key="task_time")
        add_task = st.form_submit_button("Add task")
    if add_task:
        try:
            current_pet.add_task(Task(
                title=title,
                duration_minutes=int(duration),
                priority=priority,
                category=category,
                recurrence=recurrence,
                required=required,
                description=description.strip(),
                start_date=start_date,
                preferred_start=when if timing == "Preferred time" else None,
                fixed_time=when if timing == "Fixed time" else None,
            ))
        except ValueError as err:
            st.error(str(err))
        else:
            rerun_after(f"Added '{title.strip()}'.")

    st.markdown("**Task list**")
    f_scope, f_status = st.columns(2)
    selected_name = current_pet.name  # (a lambda cannot rely on the assert above that it is not None)
    scope = f_scope.radio("Show tasks for", ["all", "selected"], horizontal=True, key="filter_scope",
                          format_func=lambda v: "All pets" if v == "all" else f"{selected_name} only")
    status_filter = f_status.radio("Show", ["Open", "Done", "All"], horizontal=True, key="filter_status")
    shown = scheduler.sort_by_time(scheduler.filter_tasks(
        pet_name=None if scope == "all" else selected_name,
        completed={"Open": False, "Done": True, "All": None}[status_filter],
    ))
    st.caption("Sorted by time; tasks with no set time come last.")
    if not shown:
        st.caption("No tasks to show.")
    for pt in shown:
        pet, task = pt.pet, pt.task
        c_text, c_done, c_remove = st.columns([6, 1, 1])
        c_text.markdown(f"{describe_task(task, today)} - *{pet.name}*")
        c_done.button("Done", key=f"done_{task.id}", on_click=complete_task, args=(task.id,),
                      disabled=task.is_completed())
        c_remove.button("Remove", key=f"remove_task_{task.id}", on_click=pet.remove_task, args=(task.id,))
        with st.expander(f"Edit '{task.title}' ({pet.name})"):
            with st.form(f"edit_{task.id}"):
                new_title = st.text_input("Title", value=task.title, key=f"edit_title_{task.id}")
                new_desc = st.text_input("Description", value=task.description, key=f"edit_desc_{task.id}")
                e1, e2, e3 = st.columns(3)
                new_duration = e1.number_input("Minutes", min_value=1, max_value=240,
                                               value=task.duration_minutes, key=f"edit_dur_{task.id}")
                new_priority = e2.selectbox("Priority", list(Priority), index=list(Priority).index(task.priority),
                                            format_func=lambda p: p.name.title(), key=f"edit_pri_{task.id}")
                new_required = e3.checkbox("Required", value=task.required, key=f"edit_req_{task.id}")
                saved_edit = st.form_submit_button("Save changes")
            if saved_edit:
                try:
                    pet.edit_task(task.id, title=new_title, description=new_desc.strip(),
                                  duration_minutes=int(new_duration), priority=new_priority,
                                  required=new_required)
                except ValueError as err:
                    st.error(str(err))
                else:
                    rerun_after(f"Updated '{new_title.strip()}'.")

# ---------------------------------------------------------------- schedule
st.divider()
st.subheader("Daily schedule")
plan_date = st.date_input("Plan for", value=today, key="plan_date")
if st.button("Generate schedule", key="generate"):
    st.session_state.show_plan = True

if st.session_state.get("show_plan"):
    # The plan is rebuilt from the live Owner on every run, so it never goes stale.
    plan = Scheduler(owner).generate_plan(plan_date)
    st.markdown(f"**Schedule for {plan_date:%A, %B %d}**")
    if not plan.scheduled_items and not plan.skipped_tasks:
        st.info("Nothing is due on this date. Add tasks above, or pick another date.")
    else:
        show_plan(plan, owner)

# ---------------------------------------------------------------- saved data
st.divider()
with st.expander(f"{display.SAVED_ICON} Saved data"):
    st.caption(f"Pets and tasks are saved automatically to `{data_file().name}` and loaded the next time you open the app.")
    confirm = st.checkbox("I understand this deletes every pet and task", key="confirm_clear")
    st.button("Clear all data", key="clear_all", disabled=not confirm, on_click=clear_all)

autosave(owner)  # last, so a change made anywhere above is saved before the run ends

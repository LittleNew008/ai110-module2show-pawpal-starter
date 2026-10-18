"""PawPal+ Streamlit UI.

All planning logic lives in pawpal_system.py. This file only collects input,
calls those classes, and shows the result.
"""

from datetime import date, time

import streamlit as st

from pawpal_system import Category, Owner, Pet, Priority, Recurrence, Scheduler, Task

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

SPECIES = ["dog", "cat", "other"]
TIMING_MODES = ["Flexible (earliest free slot)", "Preferred time", "Fixed time"]


def get_owner() -> Owner:
    """The Owner for this browser session, created on first use.

    Streamlit re-runs this whole script on every click, so a plain `Owner(...)`
    here would be rebuilt empty each time. `st.session_state` behaves like a
    dictionary that survives re-runs: if the key is already there we reuse the
    stored object, otherwise we create it once.
    """
    if "owner" not in st.session_state:
        st.session_state.owner = Owner("Jordan")
    return st.session_state.owner


def flash(message: str) -> None:
    """Remember a success message across the `st.rerun()` that follows an action."""
    st.session_state.flash = message


def rerun_after(message: str) -> None:
    """Show `message` after the page refreshes, so every list reflects the change."""
    flash(message)
    st.rerun()


def pet_by_id(owner: Owner, pet_id: str) -> Pet:
    """The pet with `pet_id`; ids are used instead of names because names can repeat."""
    return next(p for p in owner.pets if p.id == pet_id)


def describe_task(task: Task, today: date) -> str:
    """One-line summary of a task for the task list."""
    parts = [f"{task.duration_minutes} min", f"{task.priority.name.lower()} priority", task.category.value]
    if task.required:
        parts.append("REQUIRED")
    if task.fixed_time is not None:
        parts.append(f"fixed at {task.fixed_time:%H:%M}")
    elif task.preferred_start is not None:
        parts.append(f"prefers {task.preferred_start:%H:%M}")
    if task.recurrence is not Recurrence.ONCE:
        parts.append(task.recurrence.value)
    status = " (done today)" if task.is_completed(today) else ""
    return f"**{task.title}**{status} - " + ", ".join(parts)


owner = get_owner()
today = date.today()

st.title("🐾 PawPal+")
st.caption("Add your pets and their care tasks, then generate a plan for the day.")

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
        owner.add_pet(Pet(clean_name, species, breed=breed.strip(), age=int(age)))
    except ValueError as err:
        st.error(str(err))
    else:
        rerun_after(f"Added {clean_name}.")

if not owner.pets:
    st.info("No pets yet. Add one above.")
for pet in owner.pets:
    c_label, c_remove = st.columns([5, 1])
    details = ", ".join(x for x in [pet.species, pet.breed, f"{pet.age} yr" if pet.age is not None else ""] if x)
    c_label.write(f"**{pet.name}** ({details}) - {len(pet.get_tasks())} task(s)")
    # on_click callbacks run before the next re-run, so the list redraws already updated.
    c_remove.button("Remove", key=f"remove_pet_{pet.id}", on_click=owner.remove_pet, args=(pet.id,))

# ---------------------------------------------------------------- tasks
st.subheader("Tasks")
if not owner.pets:
    st.info("Add a pet first, then you can give it tasks.")
else:
    # Adding tasks is never blocked (the cap limits what gets scheduled, not what you
    # may record), so say so up front when today's tasks will not all fit.
    due_minutes = sum(pt.task.duration_minutes for pt in Scheduler(owner).filter_due_tasks(today))
    capacity = owner.capacity_minutes()
    if due_minutes > capacity:
        st.warning(
            f"Today's tasks add up to {due_minutes} min, but only {capacity} min are available "
            f"(see Owner and availability). The plan will skip the lowest-priority tasks that do not fit, "
            f"and flag any required task that cannot be scheduled."
        )
    elif due_minutes:
        st.caption(f"Today: {due_minutes} of {capacity} available minutes are planned.")

    labels = {p.id: f"{p.name} ({p.species})" for p in owner.pets}
    task_pet_id = st.selectbox("Add a task for", list(labels), format_func=lambda pid: labels[pid], key="task_pet")
    with st.form("add_task_form", clear_on_submit=True):
        title = st.text_input("Task title", value="Morning walk", key="task_title")
        description = st.text_input("Description (optional)", key="task_description")
        c1, c2, c3 = st.columns(3)
        duration = c1.number_input("Duration (minutes)", min_value=1, max_value=240, value=20, key="task_duration")
        priority = c2.selectbox(
            "Priority", list(Priority), index=list(Priority).index(Priority.MEDIUM),
            format_func=lambda p: p.name.title(), key="task_priority",
        )
        category = c3.selectbox("Category", list(Category), format_func=lambda c: c.value.title(), key="task_category")
        c4, c5, c6 = st.columns(3)
        recurrence = c4.selectbox("Repeats", list(Recurrence), format_func=lambda r: r.value.title(), key="task_repeat")
        start_date = c5.date_input("Starts on", value=today, key="task_start")
        required = c6.checkbox("Required (e.g. medication)", key="task_required")
        timing = st.radio("When", TIMING_MODES, horizontal=True, key="task_timing")
        when = st.time_input("Time (used for Preferred / Fixed)", value=time(8, 0), key="task_time")
        add_task = st.form_submit_button("Add task")
    if add_task:
        try:
            pet_by_id(owner, task_pet_id).add_task(Task(
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

    for pet in owner.pets:
        st.markdown(f"**{pet.name}'s tasks**")
        if not pet.get_tasks():
            st.caption("No tasks yet.")
        for task in pet.get_tasks():
            c_text, c_done, c_remove = st.columns([6, 1, 1])
            c_text.markdown(describe_task(task, today))
            c_done.button("Done", key=f"done_{task.id}", on_click=task.mark_complete, args=(today,),
                          disabled=task.is_completed(today))
            c_remove.button("Remove", key=f"remove_task_{task.id}", on_click=pet.remove_task, args=(task.id,))
            with st.expander(f"Edit '{task.title}'"):
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
    if not plan.scheduled_items and not plan.skipped_tasks:
        st.info("Nothing is due on this date. Add tasks above, or pick another date.")
    else:
        st.success(plan.summary())
        for warning in plan.warnings:
            st.warning(warning)
        st.table(plan.to_table())
        with st.expander("Why this plan?"):
            st.code(plan.explain(), language=None)

"""Tests for display.py: emoji, colour-coded badges and the terminal tables."""

from datetime import date, time

import pytest
from wcwidth import wcswidth

import display
from pawpal_system import Category, Owner, Pet, PetTask, Priority, Recurrence, Scheduler, Task

TODAY = date(2026, 3, 2)


def make_plan():
    rex = Pet("Rex", "dog", tasks=[
        Task("Heart meds", 5, priority="high", required=True, category=Category.MEDS, fixed_time=time(8, 0), start_date=TODAY),
        Task("Walk", 30, category=Category.WALK, fixed_time=time(8, 0), start_date=TODAY),  # clashes with the meds
    ])
    mochi = Pet("Mochi", "cat", tasks=[Task("Brush", 15, priority="low", category=Category.GROOMING, start_date=TODAY)])
    owner = Owner("J", pets=[rex, mochi])
    return owner, Scheduler(owner).generate_plan(TODAY)


# ---------- the symbols ----------


@pytest.mark.parametrize("symbol", display.ALL_SYMBOLS)
def test_every_symbol_is_one_code_point_and_two_cells_wide_so_tables_stay_aligned(symbol):
    assert len(symbol) == 1, f"{symbol!r} has a variation selector or is a sequence"
    assert wcswidth(symbol) == 2


def test_every_category_priority_and_status_has_a_distinct_badge():
    assert set(display.CATEGORY_ICONS) == set(Category) and len(set(display.CATEGORY_ICONS.values())) == len(Category)
    assert set(display.PRIORITY_BADGES) == set(Priority) and len(set(display.PRIORITY_BADGES.values())) == len(Priority)
    assert len({display.STATUS_SCHEDULED, display.STATUS_SKIPPED, display.STATUS_FLAGGED}) == 3


def test_priority_is_colour_coded_red_for_high_down_to_green_for_low():
    assert display.priority_badge(Priority.HIGH).startswith("🔴")
    assert display.priority_badge(Priority.MEDIUM).startswith("🟡")
    assert display.priority_badge(Priority.LOW).startswith("🟢")


def test_pets_get_their_species_emoji_and_unknown_species_get_a_paw_print():
    assert display.pet_icon("dog") == "🐶" and display.pet_icon("cat") == "🐱"
    assert display.pet_icon("axolotl") == display.DEFAULT_PET_ICON == "🐾"
    assert display.pet_label(Pet("Rex", "dog")) == "🐶 Rex"


def test_task_labels_start_with_the_category_emoji():
    assert display.task_label(Task("Heart meds", 5, category=Category.MEDS)) == "💊 Heart meds"
    assert display.task_label(Task("Anything", 5)) == "📌 Anything"


# ---------- small text helpers ----------


def test_when_and_repeats_text():
    assert display.when_text(Task("t", 5, fixed_time=time(8, 0), preferred_start=time(9, 0))) == "fixed 08:00"  # fixed wins
    assert display.when_text(Task("t", 5, preferred_start=time(7, 30))) == "prefers 07:30"
    assert display.when_text(Task("t", 5)) == "any time"
    assert display.repeats_text(Task("t", 5)) == "once"
    assert display.repeats_text(Task("t", 5, recurrence=Recurrence.DAILY)) == "🔁 daily"
    assert display.repeats_text(Task("t", 5, recurrence=Recurrence.WEEKLY)) == "🔁 weekly"


def test_status_says_done_later_overdue_or_due_today():
    done = Task("t", 5, start_date=TODAY)
    done.mark_complete(TODAY)
    assert display.task_status(done, TODAY) == "✅ done Mar 02"
    assert display.task_status(Task("t", 5, start_date=date(2026, 3, 5)), TODAY) == "⏳ starts Mar 05"
    assert display.task_status(Task("t", 5, start_date=date(2026, 2, 27)), TODAY) == "❗ overdue since Feb 27"
    assert display.task_status(Task("t", 5, start_date=TODAY), TODAY) == "due today"


def test_status_markdown_is_green_when_done_blue_when_later_red_when_overdue_and_plain_when_due_today():
    done = Task("t", 5, start_date=TODAY)
    done.mark_complete(TODAY)
    assert display.task_status_markdown(done, TODAY) == ":green[✅ done Mar 02]"
    assert display.task_status_markdown(Task("t", 5, start_date=date(2026, 3, 5)), TODAY) == ":blue[⏳ starts Mar 05]"
    assert display.task_status_markdown(Task("t", 5, start_date=date(2026, 2, 27)), TODAY) == ":red[❗ overdue since Feb 27]"
    assert display.task_status_markdown(Task("t", 5, start_date=TODAY), TODAY) == "due today"


# ---------- rows ----------


def test_task_rows_describe_each_task_and_star_the_required_ones():
    owner, _ = make_plan()
    rows = display.task_rows(owner.get_all_tasks(), TODAY)

    meds = rows[0]
    assert meds == {"Task": "💊 Heart meds", "Pet": "🐶 Rex", "When": "fixed 08:00", "Repeats": "once",
                    "Priority": "🔴 High ⭐", "Status": "due today"}
    assert rows[1]["Priority"] == "🟡 Medium"  # no star: not required
    assert [r["Pet"] for r in rows] == ["🐶 Rex", "🐶 Rex", "🐱 Mochi"]


def test_schedule_rows_are_the_scheduled_tasks_in_time_order_with_status_and_badges():
    _, plan = make_plan()
    rows = display.schedule_rows(plan)

    assert [r["Task"] for r in rows] == ["💊 Heart meds", "🛁 Brush"]  # the meds at 08:00, then the grooming in the next gap
    assert rows[0] == {"Status": "✅ Scheduled", "Time": "08:00–08:05", "Pet": "🐶 Rex", "Task": "💊 Heart meds",
                       "Min": 5, "Priority": "🔴 High", "Why": plan.scheduled_items[0].reason}
    assert all(r["Status"] == display.STATUS_SCHEDULED for r in rows)
    assert [r["Time"] for r in rows] == sorted(r["Time"] for r in rows)


def test_not_scheduled_rows_mark_an_optional_task_with_stop_and_a_required_one_in_red():
    _, plan = make_plan()
    rows = display.not_scheduled_rows(plan)
    assert [(r["Task"], r["Status"]) for r in rows] == [("🐕 Walk", display.STATUS_SKIPPED)]
    assert "clashes with 'Heart meds'" in rows[0]["Why"] and rows[0]["Min"] == 30

    big = Pet("P", "dog", tasks=[Task("Meds", 90, required=True, category=Category.MEDS, start_date=TODAY)])
    owner = Owner("J", pets=[big], available_minutes=30)
    flagged = display.not_scheduled_rows(Scheduler(owner).generate_plan(TODAY))
    assert flagged[0]["Status"] == display.STATUS_FLAGGED and flagged[0]["Task"] == "💊 Meds"


def test_row_helpers_give_nothing_for_an_empty_plan():
    plan = Scheduler(Owner("J")).generate_plan(TODAY)
    assert display.schedule_rows(plan) == [] and display.not_scheduled_rows(plan) == []


# ---------- the terminal table ----------


def test_a_table_has_every_header_and_row_and_every_line_is_exactly_as_wide():
    owner, plan = make_plan()
    text = display.render_table(display.schedule_rows(plan))
    lines = text.splitlines()

    for header in ("Status", "Time", "Pet", "Task", "Min", "Priority", "Why"):
        assert header in lines[1]
    assert "💊 Heart meds" in text and "🐶 Rex" in text and "🔴 High" in text
    assert len({wcswidth(line) for line in lines}) == 1, "emoji pushed some lines out of line"


def test_every_kind_of_table_stays_aligned_with_emoji_in_every_column():
    owner, plan = make_plan()
    tables = [
        display.task_rows(owner.get_all_tasks(), TODAY),
        display.schedule_rows(plan),
        display.not_scheduled_rows(plan),
    ]
    for rows in tables:
        lines = display.render_table(rows).splitlines()
        assert len({wcswidth(line) for line in lines}) == 1


def test_the_long_reason_column_wraps_and_the_minutes_are_right_aligned():
    _, plan = make_plan()
    rows = display.schedule_rows(plan)
    rows[0]["Why"] = "word " * 40  # a very long reason

    lines = display.render_table(rows, wrap_width=30).splitlines()

    assert len(lines) > 7  # the long reason took several lines
    assert all(wcswidth(line) < 120 for line in lines)  # and did not stretch the table
    minutes_column = [line.split("│")[5] for line in lines if line.startswith("│") and line.split("│")[5].strip().isdigit()]
    assert minutes_column and all(not cell.endswith("  ") and cell.startswith(" ") for cell in minutes_column)  # right-aligned


def test_an_empty_table_says_none_instead_of_drawing_an_empty_box():
    assert display.render_table([]) == "(none)"

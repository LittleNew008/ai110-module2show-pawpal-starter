"""Smoke tests for the command-line demo (main.py): it runs, shows every feature, and is repeatable."""

import re

import main


def run_demo(capsys):
    main.main()
    return capsys.readouterr().out


def test_the_demo_runs_and_shows_every_feature(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # so a stray write to ./data.json would be noticed

    out = run_demo(capsys)

    for heading in ("1. Tasks in the order they were added", "2. Sorted by time", "3. Filtered by pet",
                    "4. Conflict warnings", "5. Next free slot", "Today's Schedule", "6. Recurring tasks",
                    "7. Filtered by status", "8. Saving and loading"):
        assert heading in out, heading
    assert "🚧 Conflict (different pets)" in out  # the deliberate 12:00 clash
    assert "'Vet check-in call' (15 min), after its 12:00 clash can go at: 12:10-12:25" in out
    assert "7 scheduled (110 min), 1 skipped" in out
    assert "identical to the original: True" in out
    assert not (tmp_path / "data.json").exists()  # the save-and-load demo uses a temporary folder


def test_the_demo_prints_the_same_thing_every_time(capsys):
    assert run_demo(capsys) == run_demo(capsys)  # no random ids or other run-to-run noise


def test_every_table_in_the_demo_is_a_closed_box_of_equal_width_lines(capsys):
    from wcwidth import wcswidth

    out = run_demo(capsys).splitlines()
    boxes, current = [], []
    for line in out:
        if line.startswith(("╭", "│", "├", "╰")):  # (not `line[:1] in "..."`: an empty line would match that)
            current.append(line)
        elif current:
            boxes.append(current)
            current = []
    assert len(boxes) == 7  # as added, sorted, filtered by pet, schedule, not scheduled, completed, open
    for box in boxes:
        assert box[0].startswith("╭") and box[-1].startswith("╰")
        assert len({wcswidth(line) for line in box}) == 1, box[0]


def test_the_demo_uses_emoji_for_task_types_priorities_and_statuses(capsys):
    out = run_demo(capsys)
    for symbol in ("💊", "🐕", "🍖", "🛁", "🔴", "🟡", "🟢", "✅", "⛔", "🔁", "🕒", "💾", "🐶", "🐱"):
        assert symbol in out, symbol
    assert re.search(r"🔴 High ⭐", out)  # the required medication is starred

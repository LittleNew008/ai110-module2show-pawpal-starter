"""Checks that the UML class diagram still matches pawpal_system.py.

The diagram is Mermaid text in diagrams/uml_final.mmd. These tests read it and compare it with the
real classes, so renaming a method or adding an attribute without updating the diagram fails here.
They check names (classes, enum members, attributes, methods and their parameters) and that every
arrow joins two classes that exist. They cannot check that an arrow or a note is *meaningful*.
"""

import dataclasses
import enum
import inspect
import re
from pathlib import Path

import pytest

import pawpal_system as ps

DIAGRAMS = Path(__file__).resolve().parent.parent / "diagrams"
FINAL = DIAGRAMS / "uml_final.mmd"


def parse_diagram(text: str) -> dict[str, dict]:
    """{class name: {"members": enum members, "attrs": set, "methods": {name: [parameter names]}}}."""
    classes = {}
    for name, body in re.findall(r"class (\w+) \{(.*?)\n    \}", text, re.S):
        entry = {"members": [], "attrs": set(), "methods": {}}
        for line in (l.strip() for l in body.strip().splitlines() if l.strip()):
            if line.startswith("<<"):
                continue
            method = re.match(r"\+(\w+)\((.*?)\)", line)
            attribute = re.match(r"\+\S+ (\w+)$", line)
            if method:
                params = [p.strip().lstrip("*") for p in method.group(2).split(",") if p.strip()]
                entry["methods"][method.group(1)] = params
            elif attribute:
                entry["attrs"].add(attribute.group(1))
            else:
                entry["members"].append(line)
        classes[name] = entry
    return classes


def code_classes() -> dict[str, type]:
    return {n: c for n, c in inspect.getmembers(ps, inspect.isclass) if c.__module__ == ps.__name__}


def code_attrs(cls: type) -> set[str]:
    if dataclasses.is_dataclass(cls):
        return {f.name for f in dataclasses.fields(cls)} | {n for n, v in vars(cls).items() if isinstance(v, property)}
    return set(re.findall(r"self\.(\w+) =", inspect.getsource(cls.__init__)))  # Scheduler sets its fields in __init__


def code_methods(cls: type) -> dict[str, list[str]]:
    """Public methods defined on the class itself, including class and static methods."""
    found = {n: getattr(cls, n) for n, raw in vars(cls).items()
             if isinstance(raw, (classmethod, staticmethod)) or inspect.isfunction(raw)}
    return {n: [p for p in inspect.signature(f).parameters if p not in ("self", "cls")]
            for n, f in found.items() if not n.startswith("_")}


DIAGRAM = parse_diagram(FINAL.read_text())


def test_the_final_diagram_exists_and_the_older_copy_is_identical():
    assert FINAL.is_file()
    assert (DIAGRAMS / "uml.mmd").read_text() == FINAL.read_text()  # one design, not two drifting copies


def test_every_class_in_the_code_is_in_the_diagram_and_the_other_way_round():
    assert set(DIAGRAM) == set(code_classes())


@pytest.mark.parametrize("name", sorted(code_classes()))
def test_each_class_matches_its_diagram_box(name):
    cls, box = code_classes()[name], DIAGRAM[name]
    if issubclass(cls, enum.Enum):
        assert set(box["members"]) == {member.name for member in cls}, "enum members differ"
    else:
        assert box["attrs"] == code_attrs(cls), "attributes differ"
    assert box["methods"] == code_methods(cls), "methods or parameter names differ"


def test_every_arrow_joins_two_classes_that_exist():
    text = FINAL.read_text()
    arrows = re.findall(r"^\s{4}(\w+)\s+(?:\"[^\"]*\"\s+)?(?:-->|\.\.>)\s+(?:\"[^\"]*\"\s+)?(\w+)", text, re.M)
    assert len(arrows) >= 20  # the parser is really finding them
    for source, target in arrows:
        assert source in DIAGRAM and target in DIAGRAM, f"{source} -> {target}"


def test_the_diagram_shows_the_relationships_added_while_building():
    text = FINAL.read_text()
    for arrow in ("Owner \"1\" --> \"*\" Pet", "Pet \"1\" --> \"*\" Task", "Task ..> Task : next occurrence",
                  "PetTask --> Pet", "PetTask --> Task", "Scheduler ..> ScheduledItem", "Scheduler ..> SkippedTask",
                  "Scheduler ..> PetTask", "Scheduler --> Owner"):
        assert arrow in text, arrow

"""Design as code: a house written in Python round-trips through the pipeline."""
from pathlib import Path

import pytest

from recognition import model as M, rules
from recognition.design import House

ROOT = Path(__file__).resolve().parent.parent


def small_house(bedroom_x0: float = 7.45) -> House:
    h = House("Test house")
    eg = h.storey("EG", elevation=0.0, height=2.5)
    eg.wall("S", (0, 0), (12, 0), thickness=0.3, external=True)
    eg.wall("E", (12, 0), (12, 10), thickness=0.3, external=True)
    eg.wall("N", (12, 10), (0, 10), thickness=0.3, external=True)
    eg.wall("W", (0, 10), (0, 0), thickness=0.3, external=True)
    eg.wall("I", (bedroom_x0 - 0.075, 0.15), (bedroom_x0 - 0.075, 9.85), thickness=0.15)
    eg.room("Wohnen", [(0.15, 0.15), (bedroom_x0 - 0.15, 0.15), (bedroom_x0 - 0.15, 9.85), (0.15, 9.85)])
    eg.room("Schlafzimmer", [(bedroom_x0, 0.15), (11.85, 0.15), (11.85, 9.85), (bedroom_x0, 9.85)])
    eg.door("Haustür", on="S", at=3.0, width=1.0, height=2.1)
    eg.door("Tür", on="I", at=5.0, width=0.885, height=2.01)
    eg.window("F1", on="W", at=5.0, width=2.0, height=1.2)
    eg.window("F2", on="E", at=5.0, width=2.0, height=1.2)
    eg.window("F3", on="N", at=9.5, width=2.0, height=1.2)
    return h


def test_house_round_trips_through_loader(tmp_path):
    ifc = small_house().write(tmp_path / "house.ifc")
    m = M.load(ifc)
    assert m.schema == "IFC4" and [s.name for s in m.storeys] == ["EG"]
    assert (len(m.walls), len(m.spaces), len(m.doors), len(m.windows)) == (5, 2, 2, 3)
    assert sum(w.is_external for w in m.walls) == 4
    bedroom = next(s for s in m.spaces if s.label == "Schlafzimmer")
    assert bedroom.category == "bedroom" and bedroom.area == pytest.approx(4.4 * 9.7, rel=0.02)
    door = next(d for d in m.doors if d.name == "Tür")
    assert door.width == 0.885 and door.height == 2.01 and door.host_wall is not None and door.is_external is False
    assert {s.label for s in m.spaces_touching(door)} == {"Wohnen", "Schlafzimmer"}
    assert all(w.is_external for w in m.windows)


def test_moving_a_wall_changes_compliance(tmp_path):
    strict = {"name": "strict", "version": "t", "rules": [
        {"id": "ROOM-MIN-AREA", "title": "min area", "severity": "error", "params": {"bedroom": 50.0}}]}
    before = rules.check(M.load(small_house(7.45).write(tmp_path / "a.ifc")), strict)
    after = rules.check(M.load(small_house(6.0).write(tmp_path / "b.ifc")), strict)
    assert [r.element_tag for r in before.errors] == ["R-02"]   # 42.7 m² < 50
    assert after.errors == []                                    # 56.7 m² ≥ 50


def test_example_house_builds_and_passes(tmp_path):
    import runpy
    ns = runpy.run_path(str(ROOT / "design" / "house.py"), run_name="design")
    ifc = ns["h"].write(tmp_path / "house.ifc")
    m = M.load(ifc)
    assert (len(m.walls), len(m.spaces), len(m.doors), len(m.windows)) == (9, 6, 6, 9)
    assert rules.check(m).errors == []


def test_opening_validation():
    h = small_house()
    eg = h.storeys[0]
    with pytest.raises(ValueError):
        eg.door("bad", on="nope", at=1.0)
    with pytest.raises(ValueError):
        eg.door("bad", on="S", at=99.0)
    with pytest.raises(ValueError):
        eg.wall("S", (0, 0), (1, 0))

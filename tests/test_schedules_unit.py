"""Unit tests for recognition.schedules: row content, ordering and serialisation."""
from __future__ import annotations

import csv

from shapely.geometry import box

import factories as F
from recognition import model as M, schedules as S


def house() -> M.Model:
    m = F.rect_house()
    M._infer_external(m)
    M._assign_tags(m)
    return m


def test_room_schedule_rows_are_tag_ordered_and_list_connected_openings():
    rows = S.room_schedule(house())
    assert [r["tag"] for r in rows] == ["R-01", "R-02"]
    living, bath = rows
    assert (living["name"], living["category"]) == ("Wohnen", "living")
    assert living["area_m2"] == 25.38 and living["height_m"] == 2.6
    assert living["doors"] == "D-01 D-02" and living["windows"] == "W-01"
    # the bath is reached through the interior door only
    assert bath["doors"] == "D-02" and bath["windows"] == ""


def test_door_schedule_reports_width_external_flag_and_connected_rooms():
    m = house()
    m.doors[1].is_external = None  # host wall unknown in the IFC -> reported as "?"
    ext, interior = S.door_schedule(m)
    assert (ext["tag"], ext["width_m"], ext["external"]) == ("D-01", 1.0, "yes")
    assert ext["connects"] == "R-01"
    assert interior["external"] == "?"
    assert interior["connects"] == "R-01 / R-02"  # at most the two biggest overlaps
    m.doors[1].is_external = False
    assert S.door_schedule(m)[1]["external"] == "no"


def test_window_schedule_computes_glazing_area_and_serving_room():
    row, = S.window_schedule(house())
    assert (row["tag"], row["width_m"], row["height_m"]) == ("W-01", 2.0, 1.4)
    assert row["glazing_m2"] == 2.8
    assert row["room"] == "R-01"


def test_schedules_leave_unconnected_openings_blank():
    m = F.make_model(doors=[F.opening("D", box(20, 20, 21, 20.3))],
                     windows=[F.opening("W", box(30, 30, 31, 30.3), kind="window")])
    M._assign_tags(m)
    assert S.door_schedule(m)[0]["connects"] == ""
    assert S.window_schedule(m)[0]["room"] == ""


def test_write_csv_writes_header_and_rows(tmp_path):
    path = S.write_csv([{"tag": "R-01", "area_m2": 12.5}], tmp_path / "nested" / "rooms.csv")
    with path.open(encoding="utf-8", newline="") as fh:
        assert list(csv.DictReader(fh)) == [{"tag": "R-01", "area_m2": "12.5"}]


def test_write_csv_of_an_empty_schedule_creates_an_empty_file(tmp_path):
    path = S.write_csv([], tmp_path / "rooms.csv")
    assert path.exists() and path.read_text(encoding="utf-8") == ""


def test_to_markdown_renders_a_table_with_one_row_per_entry():
    md = S.to_markdown([{"tag": "R-01", "name": "Wohnen"}, {"tag": "R-02", "name": "Bad"}], "Room schedule")
    assert md.splitlines() == [
        "## Room schedule", "", "| tag | name |", "|---|---|", "| R-01 | Wohnen |", "| R-02 | Bad |",
    ]


def test_to_markdown_of_an_empty_schedule_says_none():
    assert S.to_markdown([], "Door schedule") == "## Door schedule\n\n_none_\n"


def test_write_all_writes_three_csvs_plus_markdown(tmp_path):
    out = S.write_all(house(), tmp_path)
    assert out["dir"] == tmp_path / "schedules"
    assert (len(out["rooms"]), len(out["doors"]), len(out["windows"])) == (2, 2, 1)
    for name in ("rooms.csv", "doors.csv", "windows.csv"):
        assert (out["dir"] / name).read_text(encoding="utf-8").startswith("tag,storey,")
    md = (out["dir"] / "schedules.md").read_text(encoding="utf-8")
    assert md.startswith("# Schedules")
    assert "## Room schedule" in md and "## Door schedule" in md and "## Window schedule" in md

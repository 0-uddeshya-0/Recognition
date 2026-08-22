import csv
import re

from recognition import rules, schedules
from recognition.sanitize import sanitize_csv_cell


def _split_markdown_row(row: str) -> list[str]:
    return re.split(r"(?<!\\)\|", row)[1:-1]


def test_csv_cells_neutralize_formula_prefixes_and_preserve_numbers():
    assert sanitize_csv_cell("=calculate") == "'=calculate"
    assert sanitize_csv_cell("@calculate") == "'@calculate"
    assert sanitize_csv_cell("\tcalculate") == "'calculate"
    assert sanitize_csv_cell(-1.25) == -1.25


def test_write_csv_sanitizes_cells_without_mutating_rows(tmp_path):
    rows = [{"name": "=calculate", "area_m2": -1.25}]

    schedules.write_csv(rows, tmp_path / "rooms.csv")

    assert rows == [{"name": "=calculate", "area_m2": -1.25}]
    with (tmp_path / "rooms.csv").open(newline="", encoding="utf-8") as fh:
        assert list(csv.DictReader(fh)) == [{"name": "'=calculate", "area_m2": "-1.25"}]


def test_schedule_markdown_escapes_pipes_and_newlines():
    markdown = schedules.to_markdown(
        [{"tag": "R-01", "name": "Kitchen|unsafe", "storey": "Ground\nFloor"}],
        "Room schedule",
    )
    row = next(line for line in markdown.splitlines() if "Kitchen" in line)

    assert r"Kitchen\|unsafe" in row
    assert "Ground Floor" in row
    assert len(_split_markdown_row(row)) == 3


def test_report_markdown_escapes_untrusted_findings():
    result = rules.Result(
        "TEST", "error", "Test", "R-01", "Room|unsafe", "Ground\nFloor",
        None, None, False, "Room|unsafe\ncontains crafted text",
    )
    markdown = rules.to_markdown(rules.Report("Test", "1", "model.ifc", [result]))
    row = next(line for line in markdown.splitlines() if "contains crafted text" in line)

    assert r"Room\|unsafe" in row
    assert "Ground Floor" in row
    assert len(_split_markdown_row(row)) == 7

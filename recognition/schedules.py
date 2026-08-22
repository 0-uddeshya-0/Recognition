"""Room, door and window schedules derived from the model.

Schedules are the most tedious hand-made deliverable in architectural detailing
and the easiest to derive. Output is CSV (for spreadsheets / DXF tables later)
and Markdown (for PRs and reports). Rows are ordered by tag so diffs are stable.
"""
from __future__ import annotations

from pathlib import Path

from .model import Model, Opening
from .writers import markdown_table, write_csv, write_text


def _rooms_for(model: Model, op: Opening) -> list[str]:
    return [s.tag for s in model.spaces_touching(op)]


def _by_tag(elements: list) -> list:
    return sorted(elements, key=lambda e: e.tag)


def _opening_row(op: Opening) -> dict:
    """The columns every opening schedule starts with."""
    return {
        "tag": op.tag, "storey": op.storey, "name": op.name, "type": op.type_name,
        "width_m": round(op.width, 3), "height_m": round(op.height, 3),
    }


def room_schedule(model: Model) -> list[dict]:
    rows = []
    for s in _by_tag(model.spaces):
        doors = [d.tag for d in model.doors_on(s.storey) if s in model.spaces_touching(d)]
        windows = [w.tag for w in model.windows_on(s.storey) if s in model.spaces_touching(w)]
        rows.append({
            "tag": s.tag, "storey": s.storey, "name": s.label, "category": s.category,
            "area_m2": round(s.area, 2), "height_m": round(s.height, 2),
            "doors": " ".join(doors), "windows": " ".join(windows),
        })
    return rows


def door_schedule(model: Model) -> list[dict]:
    rows = []
    for d in _by_tag(model.doors):
        rooms = _rooms_for(model, d)
        rows.append(_opening_row(d) | {
            "external": "yes" if d.is_external else ("no" if d.is_external is False else "?"),
            "connects": " / ".join(rooms[:2]) if rooms else "",
        })
    return rows


def window_schedule(model: Model) -> list[dict]:
    rows = []
    for w in _by_tag(model.windows):
        rooms = _rooms_for(model, w)
        rows.append(_opening_row(w) | {
            "glazing_m2": round(w.width * w.height, 2),
            "room": rooms[0] if rooms else "",
        })
    return rows


def to_markdown(rows: list[dict], title: str) -> str:
    if not rows:
        return f"## {title}\n\n_none_\n"
    cols = list(rows[0].keys())
    out = [f"## {title}", ""] + markdown_table(cols, ([r[c] for c in cols] for r in rows))
    return "\n".join(out) + "\n"


def write_all(model: Model, out_dir: Path) -> dict:
    out_dir = Path(out_dir) / "schedules"
    rooms, doors, windows = room_schedule(model), door_schedule(model), window_schedule(model)
    write_csv(rooms, out_dir / "rooms.csv")
    write_csv(doors, out_dir / "doors.csv")
    write_csv(windows, out_dir / "windows.csv")
    md = "# Schedules\n\n" + to_markdown(rooms, "Room schedule") + "\n" \
        + to_markdown(doors, "Door schedule") + "\n" + to_markdown(windows, "Window schedule")
    write_text(out_dir / "schedules.md", md)
    return {"rooms": rooms, "doors": doors, "windows": windows, "dir": out_dir}

"""Room, door and window schedules derived from the model.

Schedules are the most tedious hand-made deliverable in architectural detailing
and the easiest to derive. Output is CSV (for spreadsheets / DXF tables later)
and Markdown (for PRs and reports). Rows are ordered by tag so diffs are stable.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .model import Model, Opening


def _rooms_for(model: Model, op: Opening) -> list[str]:
    return [s.tag for s in model.spaces_touching(op)]


def room_schedule(model: Model) -> list[dict]:
    rows = []
    for s in sorted(model.spaces, key=lambda s: s.tag):
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
    for d in sorted(model.doors, key=lambda d: d.tag):
        rooms = _rooms_for(model, d)
        rows.append({
            "tag": d.tag, "storey": d.storey, "name": d.name, "type": d.type_name,
            "width_m": round(d.width, 3), "height_m": round(d.height, 3),
            "external": "yes" if d.is_external else ("no" if d.is_external is False else "?"),
            "connects": " / ".join(rooms[:2]) if rooms else "",
        })
    return rows


def window_schedule(model: Model) -> list[dict]:
    rows = []
    for w in sorted(model.windows, key=lambda w: w.tag):
        rooms = _rooms_for(model, w)
        rows.append({
            "tag": w.tag, "storey": w.storey, "name": w.name, "type": w.type_name,
            "width_m": round(w.width, 3), "height_m": round(w.height, 3),
            "glazing_m2": round(w.width * w.height, 2),
            "room": rooms[0] if rooms else "",
        })
    return rows


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return path


def to_markdown(rows: list[dict], title: str) -> str:
    if not rows:
        return f"## {title}\n\n_none_\n"
    cols = list(rows[0].keys())
    out = [f"## {title}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out) + "\n"


def write_all(model: Model, out_dir: Path) -> dict:
    out_dir = Path(out_dir) / "schedules"
    rooms, doors, windows = room_schedule(model), door_schedule(model), window_schedule(model)
    write_csv(rooms, out_dir / "rooms.csv")
    write_csv(doors, out_dir / "doors.csv")
    write_csv(windows, out_dir / "windows.csv")
    md = "# Schedules\n\n" + to_markdown(rooms, "Room schedule") + "\n" \
        + to_markdown(doors, "Door schedule") + "\n" + to_markdown(windows, "Window schedule")
    (out_dir / "schedules.md").write_text(md, encoding="utf-8")
    return {"rooms": rooms, "doors": doors, "windows": windows, "dir": out_dir}

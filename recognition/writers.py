"""Deliverable writing: text, JSON, CSV and Markdown tables.

Every generated artefact goes through here so encoding, JSON formatting and
table layout are identical across schedules, reports and the CLI summary —
which is what keeps the committed `examples/` diffable.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Sequence


def write_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path: Path, data) -> Path:
    return write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def write_csv(rows: list[dict], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return path


def markdown_table(cols: Sequence[str], rows: Iterable[Sequence]) -> list[str]:
    """Table lines (header, separator, one line per row); `None` cells render empty."""
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return out

"""The draft bundle: one JSON per round, nothing lost that a client acts on."""
from __future__ import annotations

import json
from pathlib import Path

from recognition.bundle import MAX_SVG_BYTES, build, write


def _fake_run(tmp: Path) -> Path:
    run = tmp / "Projekt"
    cand = run / "compact"
    (cand / "pkg" / "sheets").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({
        "project": "Projekt", "engine": "local", "winner": "compact",
        "candidates": [{"name": "compact", "label": "Compact core", "error": ""}],
    }))
    (cand / "verdict.json").write_text(json.dumps({
        "ok": False, "checked": 10, "failed": 1, "not_evaluated": 1, "blocking_failures": 1,
        "metrics": {"usable_ratio": 0.8},
        "findings": [
            {"rule_id": "GOOD", "status": "passed", "message": "fine"},
            {"rule_id": "CORRIDOR-WIDTH", "tier": "standard", "status": "failed",
             "element": "R-03 Flur", "message": "1.15 m < 1.2 m",
             "citation": "DIN 18040-2", "url": "https://x", "blocking": True},
            {"rule_id": "SMOKE-DETECTOR", "tier": "law", "status": "not_evaluated",
             "element": "-", "message": "no data", "citation": "BayBO Art. 46 (4)",
             "url": "", "blocking": False},
        ],
    }))
    (cand / "mesh.json").write_text(json.dumps({"elements": [], "bounds": [0, 0, 0, 1, 1, 1]}))
    (cand / "plan.json").write_text(json.dumps({"rationale": "compact spine"}))
    (cand / "pkg" / "sheets" / "A-101.svg").write_text("<svg>sheet</svg>")
    (tmp / "brief.json").write_text(json.dumps({"project": "Projekt", "rooms": []}))
    return run


def test_bundle_carries_what_a_client_acts_on(tmp_path):
    run = _fake_run(tmp_path)
    b = build(run, tmp_path / "brief.json")
    assert b["schema"] == "draftbundle/v1" and b["winner"] == "compact"
    c = b["candidates"][0]
    assert c["sheet_svg"] == "<svg>sheet</svg>"
    assert c["mesh"]["bounds"] == [0, 0, 0, 1, 1, 1]
    assert c["checked"] == 10 and c["blocking_failures"] == 1
    ids = [f["rule_id"] for f in c["findings"]]
    assert "CORRIDOR-WIDTH" in ids and "SMOKE-DETECTOR" in ids
    assert "GOOD" not in ids, "passed findings travel as a count, not a list"
    assert c["findings"][0]["citation"], "citations always travel with failures"
    assert c["rationale"] == "compact spine"
    assert b["brief"]["project"] == "Projekt"


def test_bundle_refuses_a_bloated_sheet(tmp_path):
    run = _fake_run(tmp_path)
    (run / "compact" / "pkg" / "sheets" / "A-101.svg").write_text("x" * (MAX_SVG_BYTES + 10))
    b = build(run)
    assert b["candidates"][0]["sheet_svg"] == "", "an oversized sheet is a bug, not a payload"


def test_bundle_writes_compact_json(tmp_path):
    run = _fake_run(tmp_path)
    out = write(run, tmp_path / "bundle.json", tmp_path / "brief.json")
    doc = json.loads(out.read_text())
    assert doc["candidates"][0]["name"] == "compact"
    assert ": " not in out.read_text()[:200], "bundles ship minified"

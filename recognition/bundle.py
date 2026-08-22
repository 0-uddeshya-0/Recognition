"""Pack one autopilot run into a single JSON the Studio can draw from.

The drafting loop is conversational: brief in, a few structurally different
blueprints back, refine, again. Those rounds must not merge anything — a draft
is a proposal, not a delivery — so instead of publishing to `web/data/` the
draft workflow ships ONE file per round through the relay branch, and the page
renders options straight out of it: the sheet SVG inline, the 3D mesh inline,
the verdict compacted to what a client acts on.

Kept deliberately small: failed and not-evaluated findings travel, passed ones
are counted (they are visible in full when a design is archived). A bundle is
derived output — never hand-edited, always regenerable from the run directory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "draftbundle/v1"
MAX_SVG_BYTES = 400_000        # a sheet beyond this is a bug, not a payload


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sheet_svg(cand_dir: Path) -> str:
    sheets = sorted((cand_dir / "pkg" / "sheets").glob("*.svg")) if (cand_dir / "pkg").is_dir() else []
    if not sheets:
        sheets = sorted(cand_dir.glob("**/*.svg"))
    if not sheets:
        return ""
    text = sheets[0].read_text(encoding="utf-8")
    return text if len(text.encode("utf-8")) <= MAX_SVG_BYTES else ""


def _compact_findings(verdict: dict | None) -> list[dict]:
    """Only what a client acts on: failures with their citations, and the
    declared blind spots. Passed checks travel as a count, not a list."""
    out = []
    for f in (verdict or {}).get("findings", []):
        if f.get("status") == "passed":
            continue
        out.append({k: f.get(k, "") for k in
                    ("rule_id", "tier", "status", "element", "message", "citation", "url", "blocking")})
    return out


def build(run_dir: str | Path, brief_path: str | Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    run = _read_json(run_dir / "run.json") or {}
    brief = _read_json(Path(brief_path)) if brief_path else None

    candidates = []
    for meta in run.get("candidates", []):
        name = meta.get("name", "")
        cand_dir = run_dir / name
        verdict = _read_json(cand_dir / "verdict.json")
        v = verdict or {}
        candidates.append({
            "name": name,
            "label": meta.get("label", name),
            "error": meta.get("error", ""),
            "ok": bool(v.get("ok")),
            "checked": v.get("checked", 0),
            "failed": v.get("failed", 0),
            "not_evaluated": v.get("not_evaluated", 0),
            "blocking_failures": v.get("blocking_failures", 0),
            "metrics": v.get("metrics", {}),
            "findings": _compact_findings(verdict),
            "rationale": (_read_json(cand_dir / "plan.json") or {}).get("rationale", ""),
            "mesh": _read_json(cand_dir / "mesh.json"),
            "sheet_svg": _sheet_svg(cand_dir),
            "devin_session": meta.get("devin_session", ""),
        })

    return {
        "schema": SCHEMA,
        "project": run.get("project", ""),
        "engine": run.get("engine", ""),
        "winner": run.get("winner", ""),
        "critic": run.get("critic", ""),
        "brief": brief,
        "candidates": candidates,
    }


def write(run_dir: str | Path, out_path: str | Path,
          brief_path: str | Path | None = None) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(build(run_dir, brief_path), separators=(",", ":"),
                            ensure_ascii=False), encoding="utf-8")
    return p

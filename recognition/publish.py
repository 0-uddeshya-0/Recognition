"""Turn a completed run into the Studio's static payload.

The Studio is a static site. It cannot run Python, call the pipeline, or hold a
secret, so everything it needs must already be a file: the mesh, the sheet, the
verdict, the plan, the source. This module copies exactly those into `web/data/`
and writes the index the Studio reads on load.

Keeping this separate from the run itself matters -- a run produces artifacts
whether or not anyone ever looks at them, and publishing is a deliberate second
step that can be pointed at a different directory or skipped entirely.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DATA = REPO_ROOT / "web" / "data"

# What the Studio actually loads, and what it does without if a file is absent.
WANTED = {
    "mesh.json": "3D view",
    "verdict.json": "findings",
    "plan.json": "the plan the agent returned",
    "design.py": "the building as code",
}


def slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "project"


def publish_candidate(cand_dir: Path, dest: Path) -> dict:
    """Copy one candidate's artifacts into the site and describe what landed."""
    dest.mkdir(parents=True, exist_ok=True)
    present: list[str] = []
    for name in WANTED:
        src = cand_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
            present.append(name)

    # The sheet lives under pkg/sheets/ with a storey-dependent name; the Studio
    # only ever shows the first, so normalise it to one predictable filename.
    sheets = sorted((cand_dir / "pkg" / "sheets").glob("*.svg")) if (cand_dir / "pkg").is_dir() else []
    if not sheets:
        sheets = sorted(cand_dir.glob("**/*.svg"))
    if sheets:
        shutil.copy2(sheets[0], dest / "sheet.svg")
        present.append("sheet.svg")
    pdfs = sorted((cand_dir / "pkg" / "sheets").glob("*.pdf")) if (cand_dir / "pkg").is_dir() else []
    if pdfs:
        shutil.copy2(pdfs[0], dest / "sheet.pdf")
        present.append("sheet.pdf")

    verdict = {}
    vp = dest / "verdict.json"
    if vp.is_file():
        verdict = json.loads(vp.read_text(encoding="utf-8"))
    return {
        "name": cand_dir.name,
        "files": present,
        "ok": bool(verdict.get("ok")),
        "checked": verdict.get("checked", 0),
        "failed": verdict.get("failed", 0),
        "not_evaluated": verdict.get("not_evaluated", 0),
        "blocking_failures": verdict.get("blocking_failures", 0),
        "metrics": verdict.get("metrics", {}),
    }


def publish_run(run_dir: Path, *, project: str, web_data: Path = WEB_DATA,
                brief: Path | None = None, log=print) -> Path:
    """Publish every candidate of one run, then refresh the site index."""
    run_json = run_dir / "run.json"
    run = json.loads(run_json.read_text(encoding="utf-8")) if run_json.is_file() else {}
    key = slug(project)
    dest_root = web_data / key
    if dest_root.exists():
        shutil.rmtree(dest_root)      # a republish replaces, never merges
    dest_root.mkdir(parents=True, exist_ok=True)

    cands: list[dict] = []
    for cand in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        entry = publish_candidate(cand, dest_root / cand.name)
        meta = next((c for c in run.get("candidates", []) if c.get("name") == cand.name), {})
        entry["label"] = meta.get("label", cand.name)
        entry["error"] = meta.get("error", "")
        cands.append(entry)
        log(f"  · {cand.name}: {', '.join(entry['files']) or 'nothing to publish'}")

    if brief and Path(brief).is_file():
        shutil.copy2(brief, dest_root / "brief.json")

    (dest_root / "run.json").write_text(json.dumps({
        "project": project,
        "engine": run.get("engine", "local"),
        "winner": run.get("winner", ""),
        "critic": run.get("critic", ""),
        "candidates": cands,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    _write_index(web_data)
    return dest_root


def _write_index(web_data: Path) -> Path:
    """List every published project so the Studio can offer them on load."""
    projects = []
    for d in sorted(p for p in web_data.iterdir() if p.is_dir()) if web_data.is_dir() else []:
        rj = d / "run.json"
        if not rj.is_file():
            continue
        run = json.loads(rj.read_text(encoding="utf-8"))
        winner = next((c for c in run.get("candidates", []) if c["name"] == run.get("winner")), None)
        projects.append({
            "key": d.name,
            "project": run.get("project", d.name),
            "winner": run.get("winner", ""),
            "engine": run.get("engine", ""),
            "candidates": len(run.get("candidates", [])),
            "ok": bool(winner and winner.get("ok")),
            "checked": (winner or {}).get("checked", 0),
            "not_evaluated": (winner or {}).get("not_evaluated", 0),
            "failed": (winner or {}).get("failed", 0),
        })
    p = web_data / "index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"projects": projects}, indent=2, ensure_ascii=False), encoding="utf-8")
    return p

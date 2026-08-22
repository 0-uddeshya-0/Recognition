"""Command-line entry point.

    recognition run   MODEL.ifc OUT_DIR [--rules PATH] [--project NAME] [--revision REV]
    recognition check MODEL.ifc         [--rules PATH]      # exit 1 on errors (CI gate)

`run` produces the full detailing package; `check` is the verifier Devin (and CI)
uses to know whether a change is acceptable.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import ifcopenshell.api

from . import __version__
from . import drawings as D
from . import model as M
from . import rules as R
from . import schedules as S


def git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")


def enrich_ifc(model: M.Model, report: R.Report, out_path: Path) -> Path:
    """Write tags and compliance results back into the IFC as a property set,
    so the 3D model round-trips into the architect's tool with the findings attached."""
    f = model.ifc
    findings: dict[str, list[str]] = {}
    for r in report.failures:
        findings.setdefault(r.element_tag, []).append(f"{r.rule_id} ({r.severity})")
    for el in model.spaces + model.doors + model.windows:
        product = f.by_guid(el.guid)
        pset = ifcopenshell.api.run("pset.add_pset", f, product=product, name="Recognition_Detailing")
        ifcopenshell.api.run("pset.edit_pset", f, pset=pset, properties={
            "Tag": el.tag,
            "ComplianceStatus": "FAIL" if el.tag in findings else "PASS",
            "Findings": "; ".join(findings.get(el.tag, [])) or "-",
            "GeneratedBy": f"Recognition {__version__}",
        })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(out_path))
    return out_path


def run(model_path: Path, out_dir: Path, rules_path: Path | None, project: str, revision: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    model = M.load(model_path)
    ruleset = R.load_ruleset(rules_path)
    revision = revision or git_revision()

    sched = S.write_all(model, out_dir)
    report = R.check(model, ruleset)
    R.write_report(report, out_dir)

    sheets = []
    sheet_dir = out_dir / "sheets"
    sheet_dir.mkdir(exist_ok=True)
    for i, st in enumerate(model.drawable_storeys(), start=1):
        no = f"A-{100 + i}"
        base = sheet_dir / f"{no}_{_slug(st.name)}"
        svg = D.plan_svg(model, st, base.with_suffix(".svg"), project=project, sheet_no=no, revision=revision)
        D.svg_to_pdf(svg, base.with_suffix(".pdf"))
        D.svg_to_png(svg, base.with_suffix(".png"))
        D.plan_dxf(model, st, base.with_suffix(".dxf"))
        sheets.append({"sheet": no, "storey": st.name, "svg": svg.name, "pdf": base.with_suffix(".pdf").name,
                       "png": base.with_suffix(".png").name, "dxf": base.with_suffix(".dxf").name})

    enriched = enrich_ifc(model, report, out_dir / "model.detailed.ifc")

    s = report.summary()
    summary = {
        "recognition_version": __version__, "revision": revision, "model": model_path.name, "schema": model.schema,
        "project": project or model_path.stem,
        "counts": {"storeys": len(model.storeys), "walls": len(model.walls), "spaces": len(model.spaces),
                   "doors": len(model.doors), "windows": len(model.windows)},
        "compliance": {"status": "FAIL" if s["errors"] else ("WARN" if s["warnings"] else "PASS"), **s},
        "schedules": {k: len(v) for k, v in sched.items() if k != "dir"},
        "sheets": sheets,
        "files": {"schedules": "schedules/", "report_md": "report.md", "report_json": "report.json",
                  "enriched_ifc": enriched.name, "sheets": "sheets/"},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="recognition", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="generate schedules, compliance report, drawings and enriched IFC")
    p_run.add_argument("model", type=Path)
    p_run.add_argument("out_dir", type=Path)
    p_run.add_argument("--rules", type=Path, default=None)
    p_run.add_argument("--project", default="")
    p_run.add_argument("--revision", default="")
    p_chk = sub.add_parser("check", help="run compliance rules; exit 1 if any error-level finding")
    p_chk.add_argument("model", type=Path)
    p_chk.add_argument("--rules", type=Path, default=None)
    a = ap.parse_args(argv)

    if a.cmd == "run":
        s = run(a.model, a.out_dir, a.rules, a.project, a.revision)
        c = s["compliance"]
        print(f"{s['model']} ({s['schema']}): {s['counts']}")
        print(f"compliance {c['status']}: {c['checks']} checks, {c['errors']} errors, {c['warnings']} warnings")
        print(f"sheets: {', '.join(sh['sheet'] + ' ' + sh['storey'] for sh in s['sheets'])}")
        print(f"written to {a.out_dir}/ (summary.json, report.md, schedules/, sheets/, model.detailed.ifc)")
        return 0

    report = R.check(M.load(a.model), R.load_ruleset(a.rules))
    print(R.to_markdown(report))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())

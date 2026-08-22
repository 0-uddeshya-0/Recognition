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

from . import __version__

# The heavy stacks (ifcopenshell, cairo-backed drawing) are imported inside
# the commands that use them: `recognition interview` runs in a CI job with
# no cairo installed, and importing the renderer there would crash a command
# that never draws anything.


def git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")


def enrich_ifc(model, report, out_path: Path) -> Path:
    """Write tags and compliance results back into the IFC as a property set,
    so the 3D model round-trips into the architect's tool with the findings attached."""
    import ifcopenshell.api

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
    from . import drawings as D
    from . import model as M
    from . import rules as R
    from . import schedules as S

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


def _autopilot(a) -> int:
    """Trigger to artifact. Exit code is the verdict, so CI can gate on it."""
    from .autopilot import DEFAULT_RULES, STRATEGIES, ranked, run_devin, run_local, strategy_by_name
    from .contracts import DesignBrief

    brief = DesignBrief.read(a.brief)
    strats = ([strategy_by_name(s.strip()) for s in a.strategies.split(",") if s.strip()]
              or STRATEGIES)
    rules = a.rules or DEFAULT_RULES
    out = a.out / _slug(brief.project)

    print(f"autopilot · {brief.project} · engine={a.engine} · {len(strats)} candidates")
    if a.engine == "devin":
        res = run_devin(brief, out, strategies=strats, rules_path=rules,
                        max_acu=a.max_acu, timeout_s=a.timeout, critic=not a.no_critic)
    else:
        res = run_local(brief, out, strategies=strats, rules_path=rules)

    print("\nranking (deterministic — no human, no model):")
    for i, v in enumerate(ranked(res), 1):
        m = v.metrics
        print(f"  {i}. {v.candidate:9} {v.stamp():4} blocking={v.blocking_failures} "
              f"advisory={v.advisory_failures} usable={m.get('usable_ratio', 0):.3f} "
              f"openings={m.get('openings', 0)}")
    for c in res.candidates:
        if c.error:
            print(f"  ! {c.name}: {c.error[:150]}")

    if not res.winner:
        print("\nNO WINNER — nothing passed the compliance gate. Nothing will be merged.")
        return 1
    print(f"\nwinner: {res.winner}  →  {out / res.winner}")
    print(f"run summary: {out / 'run.json'}")

    if a.publish:
        from .publish import publish_run
        dest = publish_run(out, project=brief.project, brief=a.brief)
        print(f"published to {dest} — the Studio will show it on next load")
    return 0


def _interview(a) -> int:
    """One conversational round of the intake interview, via a Devin session.

    The transcript file is what the Studio dispatched: {"messages": [...],
    "session_id": "...", "round": n, "known": {...}}. The reply JSON is what
    the Studio polls for. Exit 0 whenever a reply was produced -- "Devin has
    not answered yet" is a reply, not a failure.
    """
    from .interview import conduct

    doc = json.loads(Path(a.transcript).read_text(encoding="utf-8"))
    reply = conduct(
        doc.get("messages", []),
        session_id=str(doc.get("session_id", "") or a.session or ""),
        round_no=int(doc.get("round", 1)),
        known=doc.get("known") or None,
        timeout_s=a.timeout,
    )
    out = Path(a.out)
    reply.write(out)
    print(f"round {reply.round} · done={reply.done} · session={reply.session_id}")
    print(f"reply written to {out}")
    return 0


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

    p_auto = sub.add_parser(
        "autopilot",
        help="the autonomous layer: one brief in, verified artifacts out, nobody in between")
    p_auto.add_argument("brief", type=Path, help="path to a DesignBrief JSON")
    p_auto.add_argument("--out", type=Path, default=Path("out/autopilot"))
    p_auto.add_argument("--engine", choices=("local", "devin"), default="local",
                        help="local = deterministic candidate generation; devin = one session per strategy")
    p_auto.add_argument("--rules", type=Path, default=None)
    p_auto.add_argument("--strategies", default="",
                        help="comma-separated subset, e.g. compact,linear")
    p_auto.add_argument("--max-acu", type=int, default=None)
    p_auto.add_argument("--timeout", type=float, default=1800)
    p_auto.add_argument("--no-critic", action="store_true",
                        help="skip the adversarial review session (devin engine only)")
    p_auto.add_argument("--publish", action="store_true",
                        help="copy the artifacts into web/data/ for the static Studio")

    p_int = sub.add_parser(
        "interview",
        help="one round of the intake interview: transcript in, structured reply out (Devin)")
    p_int.add_argument("transcript", type=Path,
                       help="JSON file: {messages: [{role, text}], session_id?, round?, known?}")
    p_int.add_argument("--out", type=Path, default=Path("out/interview-reply.json"))
    p_int.add_argument("--session", default="", help="continue this Devin session")
    p_int.add_argument("--timeout", type=float, default=600)

    a = ap.parse_args(argv)

    if a.cmd == "interview":
        return _interview(a)

    if a.cmd == "autopilot":
        return _autopilot(a)

    if a.cmd == "run":
        s = run(a.model, a.out_dir, a.rules, a.project, a.revision)
        c = s["compliance"]
        print(f"{s['model']} ({s['schema']}): {s['counts']}")
        print(f"compliance {c['status']}: {c['checks']} checks, {c['errors']} errors, {c['warnings']} warnings")
        print(f"sheets: {', '.join(sh['sheet'] + ' ' + sh['storey'] for sh in s['sheets'])}")
        print(f"written to {a.out_dir}/ (summary.json, report.md, schedules/, sheets/, model.detailed.ifc)")
        return 0

    from . import model as M
    from . import rules as R

    report = R.check(M.load(a.model), R.load_ruleset(a.rules))
    print(R.to_markdown(report))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())

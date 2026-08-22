# Task: Recognition UI proof of concept

Build the one-page web UI that makes the detailing pipeline visible to an architect: upload an IFC → watch it being processed → see the sheets, schedules and compliance result → request a change → approve. Work on a new branch; do not change the pipeline.

## 1. Context — what already exists

- Repo: `0-uddeshya-0/Recognition`. **Base your branch on `poc/ifc-detailing`** (PR #2), not `main` — `main` does not have the pipeline yet.
- Read `README.md`, `AGENTS.md`, and `samples/README.md` first.
- Pipeline (pure Python, `uv` project, Python 3.12):
  ```bash
  uv sync
  uv run pytest -q                                                      # 10 tests, ~10 s
  uv run recognition run samples/AC20-FZK-Haus.ifc out/fzk --project FZK   # ~2 s, writes the package below
  uv run recognition run samples/AC20-FZK-Haus.ifc out/fzk --rules my-rules.yaml
  uv run recognition check samples/Duplex.ifc                           # exit 1 on error-level findings
  ```
- Output package written by `run` into `<out_dir>/`:
  ```
  summary.json                 ← the UI's primary data source (shape below)
  report.json / report.md      ← per-element compliance results
  schedules/rooms.csv, doors.csv, windows.csv, schedules.md
  sheets/A-101_<Storey>.png|.svg|.pdf|.dxf   (one set per storey)
  model.detailed.ifc           ← 3D model with tags + findings as a property set
  ```
- Demo models: `samples/AC20-FZK-Haus.ifc` (passes, 2 sheets), `samples/Duplex.ifc` (fails: six narrow doors, 4 sheets), `samples/extended/AC20-Smiley-West.ifc` (10 houses, 40 errors, ~17 s).
- Rules live in `rules/residential.yaml` (thresholds as data). Changing `bedroom: 9.0` to `25.0` makes FZK's Schlafzimmer (22.1 m²) fail — this is the planned demo moment.

### Data contracts (do not change; consume as-is)

`summary.json`:
```json
{
  "recognition_version": "0.1.0", "revision": "9750f5c",
  "model": "AC20-FZK-Haus.ifc", "schema": "IFC4", "project": "AC20-FZK-Haus",
  "counts": {"storeys": 2, "walls": 13, "spaces": 7, "doors": 5, "windows": 11},
  "compliance": {
    "status": "PASS",                       // PASS | WARN | FAIL
    "checks": 27, "passed": 27, "errors": 0, "warnings": 0,
    "by_rule": {"ROOM-MIN-AREA": {"checked": 5, "failed": 0, "severity": "error", "title": "..."}, "...": {}}
  },
  "schedules": {"rooms": 7, "doors": 5, "windows": 11},
  "sheets": [{"sheet": "A-101", "storey": "Erdgeschoss", "svg": "A-101_Erdgeschoss.svg",
              "pdf": "A-101_Erdgeschoss.pdf", "png": "A-101_Erdgeschoss.png", "dxf": "A-101_Erdgeschoss.dxf"}],
  "files": {"schedules": "schedules/", "report_md": "report.md", "report_json": "report.json",
            "enriched_ifc": "model.detailed.ifc", "sheets": "sheets/"}
}
```
`report.json.results[]` (one per element check, pass or fail):
```json
{"rule_id": "DOOR-MIN-WIDTH", "severity": "error", "title": "Minimum door leaf width",
 "element_tag": "D-03", "element_name": "M_Single-Flush...", "storey": "Level 1",
 "value": 0.762, "limit": 0.8, "passed": false, "message": "D-03 ...: leaf width 0.762 m < 0.8 m (interior)"}
```
Schedule CSV headers:
```
rooms.csv:   tag,storey,name,category,area_m2,height_m,doors,windows
doors.csv:   tag,storey,name,type,width_m,height_m,external,connects
windows.csv: tag,storey,name,type,width_m,height_m,glazing_m2,room
```

## 2. Goal

One page, three states, no login. The architect never sees Python, git or Devin.

**State 1 — Start**
- Drop zone / file picker for an `.ifc` (accept up to 100 MB). Show file name + size when chosen.
- Optional text box: *"Anything to change? e.g. 'Bedrooms must be ≥ 10 m² under the new code'"*.
- Buttons for the three demo models ("Try FZK-Haus", "Try Duplex", "Try Smiley West") that load the sample without an upload.
- `Run detailing` button.

**State 2 — Working**
- A step list with live status: Loaded model (counts) → Schedules → Compliance → Sheets → (Devin mode only) Opening pull request. Elapsed time. In Devin mode also show Devin's latest message and ACUs used.
- Poll every 2 s.

**State 3 — Result**
- Header: project name, revision, a big compliance pill: green PASS / amber WARN / red FAIL with `errors`/`warnings` counts.
- Left: the sheet PNG, large, with ◀ ▶ to move between storeys; click opens the PDF.
- Right: tabs **Findings** (failures first, grouped by rule; each row: tag, storey, message, value vs limit), **Rooms**, **Doors**, **Windows** (tables from the CSVs). Rows with a failing tag are highlighted red.
- Download bar: PDF set (all sheets), DXF set, schedules (zip or individual), `model.detailed.ifc`, `report.md`.
- Footer actions: `Request change` (text box → re-run in the same job), `Approve` (Devin mode: merges the PR; local mode: marks job approved), `View PR ↗` (Devin mode).
- A collapsible **Rules** panel showing the active YAML in an editable textarea; "Apply & re-run" re-runs the job with that YAML (local mode uses `--rules`; Devin mode sends the instruction + YAML to the session). This is the fallback that makes the "turns red" demo work without Devin.

## 3. Architecture

Keep one language and one process: **FastAPI backend + server-rendered HTML with htmx or a small amount of vanilla JS**. (React/Vite is acceptable if you are faster with it, but it must still be startable with a single command and must not require the pipeline to move.)

```
ui/
  app.py            FastAPI app, routes below, serves static + templates
  engine.py         Engine protocol + LocalEngine + DevinEngine
  jobs.py           in-memory job store (dict) — no database
  templates/, static/
tests/test_ui.py    backend tests with LocalEngine (no network)
```
Add `ui` deps to `pyproject.toml` (`fastapi`, `uvicorn`, `python-multipart`, `jinja2`, `httpx`) and a script entry `recognition-ui = "ui.app:main"` so `uv run recognition-ui` starts it on `:8000`.

### Engine protocol
```python
class Engine(Protocol):
    def start(self, job: Job, ifc_path: Path, instruction: str | None, rules_yaml: str | None) -> None: ...
    def poll(self, job: Job) -> None:        # updates job.status, job.steps, job.result_dir / job.pr_url
    def message(self, job: Job, text: str) -> None:   # "request change"
    def approve(self, job: Job) -> None: ...
```
Job fields: `id, created_at, model_name, status ("queued|running|done|failed"), steps[{name,status,detail}], result_dir, summary (dict), pr_url, devin_session_id, error`.

**LocalEngine** (default; must work with no credentials):
- Runs `uv run recognition run <ifc> <jobdir>/out --project <name> [--rules <jobdir>/rules.yaml]` in a background thread; parse stdout lines to tick the steps (or just mark all done when the process exits 0).
- `message()` re-runs with the edited rules YAML; free-text instructions without YAML changes are rejected with a clear note "needs Devin mode".

**DevinEngine** (enabled when `DEVIN_API_KEY`, `DEVIN_ORG_ID`, `DEVIN_PLAYBOOK_ID`, `GITHUB_REPO` are set):
- Upload the IFC: `POST https://api.devin.ai/v3/organizations/{org}/attachments` (multipart) → URL.
- Create session: `POST https://api.devin.ai/v3/organizations/{org}/sessions` with
  `{"prompt": "<instruction or 'Produce the detailing package for the attached model'>", "playbook_id": ..., "attachment_urls": [url], "title": "<model name>", "tags": ["recognition","ui"], "max_acu_limit": 5, "structured_output_schema": <schema mirroring summary.json + {"branch": str, "pr_url": str}>}`.
  Auth header `Authorization: Bearer $DEVIN_API_KEY`. Playbook is `playbooks/detailing.devin.md` (create it in the Devin org and put its id in env).
- Poll `GET .../sessions/{id}`: map `status`/`status_detail` to steps; when `structured_output` is present, read `branch`, then fetch `summary.json`, `report.json`, CSVs and PNGs from `https://raw.githubusercontent.com/{GITHUB_REPO}/{branch}/out/<name>/...` (or whatever path the playbook specifies — keep it in one constant).
- `message()` → `POST .../sessions/{id}/messages {"message": text}`; `approve()` → merge `pr_url` via `gh pr merge --squash` or the GitHub REST API with `GITHUB_TOKEN`.
- API docs: https://docs.devin.ai/api-reference/overview and https://docs.devin.ai/llms.txt (index). If an endpoint differs from the above, follow the docs and note it in the PR.

### HTTP routes
```
GET  /                         page (state 1)
POST /api/jobs                 multipart: ifc file | sample=<name>, instruction?, rules_yaml?  → {job_id}
GET  /api/jobs/{id}            job JSON (status, steps, summary, pr_url)
GET  /jobs/{id}                page rendering state 2/3 for that job (deep-linkable)
POST /api/jobs/{id}/message    {text, rules_yaml?}
POST /api/jobs/{id}/approve
GET  /jobs/{id}/files/{path}   serves files from the job's result dir (png/pdf/dxf/csv/ifc/md), path-traversal safe
GET  /api/rules                current default rules YAML
```

## 4. Non-goals

- No auth, no database, no multi-user, no deployment config beyond `uv run recognition-ui`.
- No changes to `recognition/`, `rules/`, `samples/`, `examples/`, `tests/test_pipeline.py`. If the pipeline needs a change, write it down in the PR instead.
- No 3D viewer (nice-to-have only if everything else is done: That Open Company's web-ifc viewer embedding `model.detailed.ifc`).

## 5. Acceptance criteria

- [ ] `uv sync && uv run recognition-ui` starts; `/` loads; "Try FZK-Haus" → result screen within ~5 s showing 2 sheets, PASS pill, 7 rooms / 5 doors / 11 windows in tabs.
- [ ] "Try Duplex" → FAIL pill, Findings tab lists the `DOOR-MIN-WIDTH` failures first, those door rows are red in the Doors tab.
- [ ] Rules panel: change `bedroom: 9.0` to `25.0`, Apply & re-run on FZK → `R-04 Schlafzimmer` appears as a failure; pill turns red.
- [ ] Upload of an arbitrary `.ifc` works (test with `samples/extended/AC20-Smiley-West.ifc`; the working screen must stay responsive for ~20 s).
- [ ] Downloads: each sheet PDF/DXF, `model.detailed.ifc`, CSVs open correctly.
- [ ] `tests/test_ui.py`: job lifecycle with LocalEngine (create → poll until done → summary present → files served → rules re-run changes status). `uv run pytest -q` green overall.
- [ ] DevinEngine is implemented and selected automatically when env vars are present; with no credentials it is never invoked. If you cannot test it against a real org, say so explicitly in the PR and leave the code behind the env check.
- [ ] The page is presentable: clear hierarchy, the sheet image dominates, the compliance pill is unmistakable, works on a laptop screen at 1440×900. No framework defaults left visible.

## 6. Process

- Branch: `ui/poc` from `poc/ifc-detailing`. Commit after each of: scaffold, LocalEngine + jobs, state 1, state 2, state 3, rules panel, DevinEngine, tests, polish. Conventional messages, present tense.
- Open a PR against `poc/ifc-detailing` with screenshots of all three states (FZK PASS, Duplex FAIL, FZK after rule change), and a short "how to run" block.
- Time box: ~6 h. Order of work: LocalEngine + state 3 on the FZK sample first (that is 70 % of the demo), then state 1 upload, state 2 polling, rules panel, tests, DevinEngine last.
- If something in this brief conflicts with what you find in the repo, the repo wins; note the discrepancy in the PR.

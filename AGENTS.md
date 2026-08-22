# AGENTS.md — how to work in this repository

Recognition gives architecture an engineer: a brief in plain words goes in; a
compliant building comes out — IFC model, dimensioned sheets, schedules, and a
compliance report citing the statute behind every finding. **The model plans,
the code draws:** no agent ever emits a coordinate or states a regulation.
A deterministic verifier is the only gate, and it — not you — decides done.

## The two pipelines (both live here)

| | In | Out | Entry |
|---|---|---|---|
| **Autopilot** (the product) | `briefs/<p>.json` | verified candidates in `out/autopilot/`, published to `web/data/` | `recognition autopilot` |
| **Detailing** (stage 1) | an IFC from an architect | schedules, compliance, sheets | `recognition run` / `check` |

Layers, briefly: L0 rules-as-data (`rules/by/*.yaml`, cited) → L1 interview
(`recognition/interview.py`) → L2 architect (Devin session, areas + adjacencies
only) → L3 deterministic translator (`translate.py`, zero tokens) → L4 geometry
(`design.py` → IFC4) → L5 verifier (`rules.py` + `score.py`) → L6 iteration →
L7 Studio (`web/`, static) → L8 orchestration (`.github/workflows/`).
Full detail: [docs/architecture/](docs/architecture/README.md).

## Commands

```bash
uv sync                                                   # Python 3.12, deps in pyproject.toml
uv run pytest -q                                          # the verifier — green before any PR
uv run recognition autopilot briefs/familienhaus.json     # full loop, local engine, ~20 s, no key
uv run recognition autopilot briefs/<p>.json --engine devin --publish
uv run recognition interview transcript.json --out reply.json   # one interview round (needs DEVIN_API_KEY)
uv run recognition run samples/AC20-FZK-Haus.ifc out/fzk  # detailing package for one model
python3 -m http.server 8123 -d web                        # the Studio, exactly as Pages serves it
```

On macOS, `cairosvg` needs `brew install cairo` and
`export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH`.

## Skills

Repo skills live in `.agents/skills/` (open Agent Skills layout — Devin,
Claude, Cursor and Codex all discover them). Invoke with `@skills:<name>`:

- **architect-plan** — author a valid `ArchitectPlan` (L2 sessions).
- **interview-brief** — conduct the intake interview (L1 sessions).
- **verify-repair** — run the gate, read a verdict, repair at the lowest layer.
- **studio-visual-test** — frame-by-frame browser test before any `web/` PR.

If your harness runs **Fusion**, the split that pays: judgement (the plan, the
diagnosis, the final review) stays in the main agent; mechanical loops
(`uv sync`, pytest, regenerate, re-verify) go to the sidekick.

## The five sources of truth

Everything else is derived — regenerate it, never edit it.

| Authority | Artifact | Rule |
|---|---|---|
| Intent | `briefs/<p>.json` | unconfirmed values are recorded `assumptions[]`, never silent |
| Regulation | `rules/by/*.yaml` | **no LLM may author or edit a rule or threshold**; every rule carries `tier` + cited `source` or fails to load |
| Geometry | `design/<p>.py` / generated `design.py` | change the plan or the translator, not the output |
| Exchange | `out/**/model.ifc` | pure output |
| Provenance | git history + Entire checkpoints | append-only |

## Conventions

- Units: metres internally; drawings annotate millimetres without unit (`3 625`).
- Tags `R-nn` / `D-nn` / `W-nn` are drawing identifiers — renumbering them
  invalidates every sheet; call it out in the PR title if unavoidable.
- DXF layers follow AIA naming (`A-WALL`, `A-DOOR`, `A-GLAZ`, `A-ANNO-DIMS` …).
- Rule thresholds live in YAML with a source comment — never hard-coded in Python.
- Room categories are inferred from names (`model.ROOM_CATEGORIES`, EN + DE);
  extend the keyword list rather than special-casing.
- The Studio is static: no build step, no framework, no secret in the browser.
  Brand tokens live in `web/studio.css`; verdict colours are never decoration.

## Definition of done

- `uv run pytest -q` green.
- `examples/` regenerated and committed when `recognition/` or `rules/` changed
  (`for m in AC20-FZK-Haus Duplex; do uv run recognition run samples/$m.ifc examples/$m --project $m; done`) —
  an unexpected diff in a sheet you did not mean to touch **is** the bug signal.
- Anything touching `web/` passed @skills:studio-visual-test, with current
  screenshots in `docs/ui/`.
- PR description: what changed and why, before/after sheet or Studio images,
  the coverage line for affected models, and any domain assumption you made.

## Forbidden

- Hand-editing generated files: `examples/`, `out/`, `web/data/`, any
  SVG/DXF/PDF/IFC, or a translator-produced `design.py`.
- Editing `samples/` — those are the architect's models.
- Authoring rule thresholds or citations (see sources of truth).
- Committing `out/` or secrets; `.env` stays local.
- Claiming compliance you did not compute. A rule that cannot be evaluated is
  reported **not evaluated** — never pass, never hidden.
- `git add -A` — stage files by name.

## When unsure

State the assumption in the PR and take the conservative reading (stricter
limit, more information on the drawing). Ask a human only when two readings
lead to materially different buildings.

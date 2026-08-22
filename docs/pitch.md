# Recognition — the pitch

*Built for Cognition's "Find an Industry, Give it an Engineer" — two days, judged
on what actually runs. Everything below links to a live run, a merged PR, or the
live product. Nothing is a mock.*

**Live product:** https://0-uddeshya-0.github.io/Recognition/

---

## Problem — the industry, who's stuck, and why it has the loop

**Architecture.** A layout that violates building code is discovered months after
the work went out — at permit review, or on site. Small practices and their
clients wait weeks for a first compliant feasibility study, and every change
request restarts the wait.

But architecture is the exception hiding in plain sight: **building code is
machine-checkable.** Clear heights, daylight ratios, door widths, corridor
clearances, which rooms a dwelling must contain — all decidable from a model.
BayBO articles and DIN norms are executable predicates. The verdict already
exists; nothing was sitting inside the loop.

## Approach — what we went in with, and how it changed while building

1. **Went in with:** the *paperwork* as code. The architect keeps designing in
   Revit; an IFC comes in, code derives schedules, sheets and the compliance
   check, and Devin maintains that code. (Still alive: `recognition run`.)
2. **First change — the design itself became code.** Verification and review
   demand diffable text, so the building became `design.py`: ~60 readable
   lines, every number a metre, generated from a typed plan.
3. **Second change — Devin stopped touching the repository.** The Devin GitHub
   App got 403 on push, and routing around it produced the better
   architecture: **the model plans, the code draws.** Devin returns an
   `ArchitectPlan` — rooms, areas, adjacencies, *no coordinates* — and
   deterministic code builds the IFC and judges it. A session cannot fake a
   pass, because the artifacts it is judged on are produced downstream by code
   it never ran.
4. **Third change — the human moved to the trigger.** The interview happens
   *before* the run and seals a brief; unanswered non-legal questions become
   registered assumptions, never silent defaults. There is no Approve button
   anywhere.

## Solution — what runs now

```
brief ──▶ 3 Devin sessions ──▶ build each ──▶ verify each ──▶ merge the winner
 (chat)     (plan only)         (0 tokens)     (cited gate)    (github-actions)
```

Nine layers, each reading only the one below — rules-as-data with citations,
the interview, the architect sessions, a deterministic translator, an IFC4
geometry kernel, the tiered verifier, word-driven iteration, the static Studio,
and GitHub Actions as the runtime. Full detail: [architecture](architecture/README.md).

---

## The judging criteria, point by point

### Autonomy — trigger to artifact, nobody in between

[Run 32600313272](https://github.com/0-uddeshya-0/Recognition/actions/runs/32600313272):
one `workflow_dispatch` started **three parallel Devin sessions**; each returned
a plan; deterministic code built and verified all three; the scorer picked the
winner; and [PR #13](https://github.com/0-uddeshya-0/Recognition/pull/13) was
**opened and merged by `github-actions` itself**, then deployed to the live
Studio. No approval step exists in the workflow — a green verifier *is* the
merge decision, and a red one merges nothing.

Triggers: the Studio chat, `workflow_dispatch`, `repository_dispatch`, or
committing a brief. The page holds no secret — it hands any viewer the exact
`gh workflow run` command and live-follows the run it starts.

### Verification — the system tells good from bad on its own

- Every rule carries a **provenance tier and a citation** (`law` · `standard` ·
  `guidance` · `house`) and *fails to load without them*. Law blocks; guidance
  can only warn — `ROOM-MIN-AREA` is a Richtwert and the system knows it.
- **The stamp always carries coverage**: `42 checked · 2 not evaluated ·
  2 failed`. Rules the model cannot decide (smoke detectors, thresholds) are
  declared blind spots — reported, never counted as passes. No bare PASS exists.
- **Live proof it rejects work**: in the autonomy run above, the gate failed
  two of Devin's three plans and merged only the legal one. On the demo site,
  [Dreifamilienhaus](https://0-uddeshya-0.github.io/Recognition/?p=dreifamilienhaus&c=linear)
  fails its 1.15 m corridor — a finding that is *advisory* for a single-family
  house and **blocking** here, because three dwellings auto-trigger BayBO
  Art. 48 and DIN 18040-2. Nobody configured that; the rule declares its own
  trigger.
- A **critic session** reviews each winner for what rules cannot see (it caught
  a hall "narrower than the seven door leaves opening off it") — advisory by
  construction: a model must never veto a deterministic gate, in either direction.

### Artifacts — output the industry actually uses

Per candidate: `model.ifc` (IFC4 with real `IfcSpace`/`IfcWall`/`IfcDoor` and
proper openings — opens in Revit or ArchiCAD), dimensioned floor-plan sheets as
**SVG / PDF / PNG / DXF** (DXF goes straight into AutoCAD, AIA layer names),
room/door/window schedules as CSV, `verdict.json` with a statute citation on
every finding, and `design.py` — the building as reviewable source.

### Clarity — follow the loop in one demo

1. **Describe it** — chat: *"a co-working space for a team of ten — a studio
   with a desk for everyone, a conference room, a washroom, a small kitchen"*.
   Watch the brief sheet fill in, each value tagged **you / Devin / assumed**.
   Switch the agent to *Devin · live session* for the real reader (relayed
   through CI; every reply badged with its engine and session link).
2. **See a verdict fail honestly** — open Dreifamilienhaus → `linear`: the
   stamp reads FAIL, and the findings panel explains in plain words: the
   corridor is 1.15 m, barrier-free needs 1.20 m — with the fix suggested.
3. **Say the change in words** — type *"make the hall at least 20 m²"* into
   Rebuild: the whole building is re-planned, re-drawn and re-verified (never
   patched), and a before/after strip shows which findings the change fixed.
4. **Check the provenance** — Options links each layout to the Devin session
   that planned it; the merged design PR sits in the repo history, authored by
   the workflow.

## Where Devin does the work

| Role | What it reads | What it returns |
|---|---|---|
| Interviewer | the client's own words (chat relay) | the brief, questions, registered assumptions |
| Architect ×3 | brief + `@skills:architect-plan` | an `ArchitectPlan` — no coordinates |
| Critic | the winner's plan + verdict | what a checker cannot see (advisory) |
| Repairer | a contract error, verbatim | a corrected plan (observed live: one reject → one repair → pass) |

The repo teaches its agents natively: [AGENTS.md](../AGENTS.md) plus four
[Agent Skills](../.agents/skills) Devin auto-discovers, prompts structured to
Cognition's own instructing-Devin guidance, structured output enforced at the
API, and **Fusion-shaped delegation** (judgment in the main agent, mechanical
verification to the sidekick) so enabling the Fusion preview pays immediately.

## Honest limits

v1 is single-storey, and the cited rulepack is **Bayern residential**; a
workplace brief is designed gladly but judged against that pack, and the report
says exactly what it could and could not check. This is a design aid, not a
*Prüfstatiker*, and no run ever claims otherwise.

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
committing a brief. The page holds no secret — a Cloudflare relay keeps the
token server-side and exposes only "start one allow-listed workflow" plus four
pattern-validated reads, so a first-time visitor gets the whole loop with
nothing to install and nothing to sign in to.

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

1. **Say it** — *"an office for my small startup — 8 of us, an open studio, a
   meeting room, a small kitchen"*. The agent asks only what it can't infer
   (here: nothing) and proposes drafting. Switch it to *Devin · live* for the
   session that genuinely reads; every reply is badged with its engine.
2. **Choose from four takes** — dimensioned blueprints as cards, each with a
   quiet code pill (`✓ 28 checks · 2 unchecked` — never a bare pass). When a
   take fails, the agent says so in plain words and the checks drawer carries
   the citation and the fix.
3. **Keep talking** — "make the studio bigger", "add a meeting room" — the
   whole set is redrafted and re-verified; nothing is ever patched by hand.
4. **Pick one** — the 3D model rises on the stage; **archive** re-verifies,
   merges itself, and the design joins the portfolio with builder-grade files.
5. **Check the provenance** — archived designs link the Devin sessions that
   planned them, and every merged design PR in the history is authored by the
   workflow, not a person.

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

# Submission answers

Copy-paste ready for the entry form.

---

## Project Name

```
Recognition
```

*(If a tagline is wanted alongside it: **Recognition — your AI architect**.)*

---

## Short Description — 279 / 300 characters

```
An AI architect you talk to. Describe a building in plain words; Devin plans four
layouts in parallel, deterministic code draws them as dimensioned blueprints and
IFC, and a cited rule engine verifies every one before you see it. Pick one, get
the 3D model and builder-ready files.
```

Alternates, if a different emphasis is wanted:

**Autonomy-forward (272 chars)**
```
Architecture's feedback loop existed all along: building code is machine-checkable.
Recognition puts Devin inside it — a sentence in, four verified blueprints and a 3D
model out, with the compliance gate, not a person, deciding what merges. No approve
button anywhere.
```

**Plain-spoken (246 chars)**
```
Tell it what you want to build — an office for your startup, a 3BHK, a warehouse.
It asks only what it needs, drafts four dimensioned blueprints checked against real
building code, and builds the 3D model of the one you pick. No architect fees, no
weeks of waiting.
```

---

## Pitch Deck

Upload **`Recognition-pitch.pptx`** (11 slides, ~3 minutes). A `.pdf` export sits
beside it if the form prefers PDF. Editable in PowerPoint, Google Slides or Canva
(Canva: *Create design → Import file*).

---

## GitHub Repository

```
0-uddeshya-0/Recognition
```

Public — no collaborator invite needed. Entire session history is present.

---

## Live Demo

```
https://0-uddeshya-0.github.io/Recognition/
```

Nothing to install and no sign-in: a Cloudflare relay holds the trigger token
server-side, so a first-time visitor gets the whole loop — describe → four
verified blueprints → 3D — straight away.

Worth clicking during judging:

| Link | What it shows |
|---|---|
| [the live Studio](https://0-uddeshya-0.github.io/Recognition/) | the product: type a sentence, watch a real CI run, choose from four takes |
| [?p=familienhaus](https://0-uddeshya-0.github.io/Recognition/?p=familienhaus) | a design planned by three parallel Devin sessions — each candidate links its session |
| [?p=dreifamilienhaus&c=linear](https://0-uddeshya-0.github.io/Recognition/?p=dreifamilienhaus&c=linear) | the gate rejecting work: 3 homes trigger BayBO Art. 48 and a 1.15 m corridor turns blocking |
| [PR #13](https://github.com/0-uddeshya-0/Recognition/pull/13) | a design pull request opened **and merged by `github-actions`**, no human |
| [run 32600313272](https://github.com/0-uddeshya-0/Recognition/actions/runs/32600313272) | that run: three Devin sessions, two candidates rejected, one merged |

---

## Tech Stack (comma-separated)

```
Devin API (v1, parallel sessions, structured output, Agent Skills, playbooks), Python 3.12, IfcOpenShell (IFC4), Shapely, svgwrite, cairosvg, ezdxf, PyYAML, pytest, uv, JavaScript (ES modules, no framework), Three.js, WebGL, HTML/CSS glassmorphism, GitHub Actions, GitHub Pages, Cloudflare Workers, httpx, GitHub REST API
```

Shorter variant if the field is tight:

```
Devin API, Python, IfcOpenShell, Shapely, ezdxf, cairosvg, pytest, JavaScript, Three.js, WebGL, GitHub Actions, GitHub Pages, Cloudflare Workers
```

---

## If asked: "What does Devin do here?"

Four roles, all programmatic:

1. **Interviewer** — reads the client's own words, returns a typed `DesignBrief`,
   asks only what a `tier: law` rule genuinely requires.
2. **Architect ×N** — parallel sessions, each given a structurally different
   strategy, each returning an `ArchitectPlan` of rooms, areas and adjacencies —
   **no coordinates**.
3. **Critic** — reviews the winner for what a rule engine cannot see; advisory by
   construction, it can annotate but never overturn.
4. **Repairer** — a contract-validation error is handed back verbatim as the
   repair prompt; observed live as one rejection, one repair, clean pass.

The repo teaches Devin natively: four Agent Skills in `.agents/skills/`, playbooks
per role, `structured_output_schema` enforced at the API, an environment
blueprint, and Fusion-shaped delegation guidance (judgement in the main agent,
mechanical verification to the sidekick).

## If asked: "What are the limits?"

v1 designs a **single storey**, and the cited rulepack is **Bayern residential**.
A workplace or warehouse is designed gladly, and the compliance report states
exactly what it could and could not check. Rules that cannot be judged from a
model — smoke detectors, thresholds — are reported as *not evaluated* and never
counted as passes. It is a design aid, not a *Prüfstatiker*, and nothing in the
product uses the word "certified".

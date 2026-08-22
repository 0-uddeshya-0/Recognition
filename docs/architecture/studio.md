# The Studio — L7, the interface

> *"A drawing-office light table. The sheet is the hero; the rest is the instrument
> panel."* — the note at the top of the original `style.css`, and still the brief.

The Studio is where a person meets the autonomous layer. It has exactly two jobs:
take a brief in, and make a building legible coming out. Everything between those
two moments happens without it.

## Brand

Carried forward from the existing UI rather than reinvented — the visual language was
already right for the domain and consistency is worth more than novelty.

| Token | Value | Role |
|---|---|---|
| `--board` | `#E4E8EC` | the desk the sheet lies on |
| `--paper` | `#FFFFFF` | the sheet — always the brightest thing on screen |
| `--ink` | `#15191D` | walls, type |
| `--accent` | `#2A62D8` | drafting blue: openings, links, the one action |
| `--pass` / `--warn` / `--fail` | `#167A4C` / `#B8740A` / `#C8352A` | verdicts, never decoration |
| `--font-ui` | Familjen Grotesk | interface |
| `--font-mono` | IBM Plex Mono | every number, tag and dimension |

Three rules that keep it feeling like a drawing office and not a dashboard:

1. **The drawing is the hero.** Panels are quiet; the sheet and the model get the
   contrast, the shadow and the space.
2. **Numbers are monospace, always.** A room area, a door width, a rule threshold and
   a tag are all data, and data lines up.
3. **Verdict colour is reserved.** `--pass` / `--fail` mean a compliance result and
   nothing else. Nothing decorative is ever green.

## The four states

### 1 · Brief — the interview

Deliberately short. Enough to know intent and the specifications the rules actually
need, and not one question more. The whole interview is **five questions**, each with
options and a free-text escape:

| Question | Why it is asked |
|---|---|
| What are you building? | selects the building class |
| How many homes in it? | **required by BayBO Art. 48** — above two, barrier-free becomes mandatory |
| Which rooms, and how many? | the programme |
| How big is the plot? | bounds the envelope |
| Anything else? | free text, always available |

Only questions a `tier: law` rule genuinely needs are blocking. Everything else has a
default that is recorded as an **assumption** and shown as an editable chip:

```
ceiling 2.50 m · assumed · BayBO Art. 45 (1) minimum 2.40 m + 100 mm build-up   ✎
```

The question list is not hand-written. It is derived from the `requires:` fields of
the rules in force, so adding a rule adds its question. See
[autonomy.md](autonomy.md) for why this runs *before* the trigger.

### 2 · Working

The layer stack ticks L2 → L5, each step showing the artifact as it appears. When
Devin is running, its own words are shown rather than a spinner — the wait is more
tolerable when you can see what it is doing.

### 3 · Result

Three panes: **3D**, **2D sheet**, **findings**.

- **3D** — orbit, zoom, hover a room for its tag and area. Walls, spaces, doors and
  windows are separately coloured; doors and windows use the accent so the openings
  read at a glance.
- **2D** — the generated sheet, the same file that goes to a contractor.
- **Findings** — grouped by tier. Every entry links to the statute article it came
  from, with the retrieval date. Nothing appears without a citation.

The stamp always carries coverage. `PASS 57/57` alone is a lie of omission; the
Studio renders `57 checked · 2 not evaluated · 0 failed` and lists what it could not
see.

### 4 · Options

When a run explored several strategies, each is a card with its plan, its verdict and
its metrics. The winner is already marked — chosen by the scorer, not by the person
looking at the screen. Selecting another is a *new trigger*, not an approval.

## How 3D works, and why it is static

`ifcopenshell.geom.create_shape` triangulates every wall, space, door and window
server-side into `mesh.json` — vertices, faces, tag, class, storey per element. The
browser loads that JSON and renders it with Three.js.

This approach comes from the Studio work on the `studio` branch and is better than the
alternative for our case:

| | mesh.json + Three.js | web-ifc (WASM) |
|---|---|---|
| Parses IFC in the browser | no — already triangulated | yes |
| Payload | small, only what is drawn | the whole IFC |
| Needs a server at view time | **no** | no |
| Element tags and areas | carried in the JSON | must be re-derived |

Because meshing happens once, when the artifact is produced, the viewer is a static
file reading a static file — which is what makes the whole Studio hostable on GitHub
Pages with no backend and no secret in the browser.

## Hosting

GitHub Pages serves `web/` as static files. A run publishes its artifacts into
`web/data/<project>/`, and the Studio reads them:

```
web/
  index.html          the Studio
  studio.css          brand tokens + layout
  studio.js           viewer, interview, state
  data/
    index.json        which projects exist
    <project>/
      mesh.json  sheet.svg  verdict.json  plan.json  design.py
```

The page never holds a secret. A live run is a `repository_dispatch` posted with the
viewer's own credentials, or — for the common case — the Studio simply reads the
artifacts a previous run already committed.

## What the Studio deliberately does not have

No **Approve**, no **Reject**, no **Request changes** on the autonomous path. Those
made the previous UI a copilot. A person can start a run and can start another one;
they cannot hand-approve a building into existence, because the verifier already
decided and it does not need a second opinion.

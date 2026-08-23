# Recognition — advertisement video generation prompt

A production-ready prompt for a text-to-video model (Sora 2, Veo 3, Runway Gen-4,
Kling 2.5). Two forms: **one master prompt** for models that accept a long brief,
and a **shot-by-shot list** for models that generate 5–10 s clips to be cut
together. Voice-over script and on-screen type are included so the edit can be
assembled without further writing.

Brand constants for every shot: cobalt `#3B5BDB`, ink `#1B2230`, near-white
`#F4F7FD`, glass surfaces, monospace numerals, and a soft architectural morning
light. Never show a green "PASS" without its coverage line — the honesty rule of
the product applies to its advertising too.

---

## 1 · Master prompt (single-shot models)

> A 60-second cinematic product film for **Recognition**, an AI architect.
> Photoreal, shot on an ARRI Alexa with a 35 mm prime, shallow depth of field,
> soft north-facing daylight, dust motes in the air. Colour grade: cool
> near-white and pale blue, with a single saturated cobalt accent that recurs in
> every scene. Calm, confident, premium — the register of Apple or Stripe, never
> a hard-sell tech ad. No text-to-speech voice, no stock-music swell, no
> spinning 3D logos, no lens flares, no neon "AI" clichés, no glitch effects.
>
> **Opening (0–8 s):** a young architecture-practice owner sits alone at a
> drafting table at dusk, surrounded by rolled drawings and red-inked markups.
> She rubs her eyes. Slow push-in. A wall calendar behind her shows weeks
> crossed off. The room is warm, cluttered, and tired.
>
> **Turn (8–16 s):** she opens a laptop; the screen's cool cobalt light washes
> over her face and the clutter falls into shadow. Cut to a clean screen-capture
> insert: she types one plain sentence — *"an office for my small startup, eight
> of us, an open studio and a meeting room"* — and presses send. No forms, no
> dropdowns.
>
> **The work (16–34 s):** a macro-scale, physically-real sequence: four
> architectural floor plans draw themselves in crisp black line-work on white
> paper, dimension strings extending like measuring tape, room labels settling
> into place. The four plans arrange themselves side by side on a glass surface.
> A cobalt check mark and a small monospace line — *"57 checked · 2 not evaluated
> · 0 failed"* — settle beneath each one. One plan's corridor glows amber and a
> line of type reads *"1.15 m — barrier-free needs 1.20 m"*; that plan slides
> gently back, rejected.
>
> **The build (34–48 s):** the chosen plan lifts off the page and extrudes into
> a translucent white 3D model of the building — walls rising, door and window
> openings cutting themselves cleanly, the model rotating slowly in soft light
> above a glass table. Sunlight moves across it. A thin cobalt outline traces
> the envelope once.
>
> **Close (48–60 s):** the architect looks up from the laptop, calm, and smiles
> slightly. Hard cut to a near-white screen: the Recognition mark — a rounded
> square outline with a solid cobalt square inside — animates on with a single
> confident scale-in. Type beneath, centred, generous letter-spacing:
> **"Recognition — your AI architect."** Then a second line in monospace:
> *"Describe it. It draws it. The code checks it."* Hold three seconds on the
> mark and the URL. End on silence.
>
> Audio: sparse piano and low strings, one gentle rise at the extrusion moment,
> resolving to near-silence at the logo. Diegetic sound: paper, a pencil set
> down, a laptop opening, a soft mechanical click as each check lands.

---

## 2 · Shot list (clip-based models)

Generate each as its own clip, then cut in order. Every shot carries the same
grade note: *cool near-white and pale blue, one cobalt accent, soft daylight,
35 mm, shallow depth of field, photoreal, no text artefacts.*

| # | Dur | Prompt | On-screen |
|---|---|---|---|
| 1 | 4 s | Dusk. An architect at a drafting table buried in rolled drawings and red-pen markups, rubbing her eyes. Slow push-in, warm tungsten light, dust in the air. | — |
| 2 | 3 s | Macro: a red pen strikes through a dimension on a printed floor plan. Paper texture, shallow focus. | *"Wrong by 5 cm. Found out in month three."* |
| 3 | 4 s | She opens a laptop; cool cobalt screen light washes over her face as the cluttered room falls into shadow. | — |
| 4 | 5 s | Clean screen capture, no cursor jitter: one plain sentence being typed into a glass-panelled chat interface, then sent. | *"an office for my startup — eight of us"* |
| 5 | 6 s | Four architectural floor plans drawing themselves simultaneously in crisp black line-work on white paper; dimension strings extend, room labels settle. Top-down, macro. | — |
| 6 | 5 s | The four plans arrange side by side on a glass surface; a small cobalt check mark and monospace figures settle under each. | *"57 checked · 2 not evaluated · 0 failed"* |
| 7 | 4 s | One plan's corridor glows amber; the plan slides back and dims while the others stay lit. | *"1.15 m — barrier-free needs 1.20 m"* |
| 8 | 6 s | A floor plan lifts off the paper and extrudes upward into a translucent white 3D building model; walls rise, window openings cut themselves cleanly. | — |
| 9 | 5 s | The translucent model rotates slowly above a glass table in soft daylight, a thin cobalt line tracing its envelope once. | — |
| 10 | 4 s | A wide, calm shot: the architect looks up from the laptop and smiles slightly. Morning light now, the room tidy. | — |
| 11 | 5 s | Near-white screen. A rounded-square outline mark with a solid cobalt square inside scales on once, confidently. Generous negative space. | **Recognition — your AI architect** |
| 12 | 4 s | Hold on the mark; a monospace line fades in beneath it. | *Describe it. It draws it. The code checks it.*  ·  `0-uddeshya-0.github.io/Recognition` |

---

## 3 · Voice-over script (60 s, calm female or neutral, unhurried)

> Every industry has an engineering problem.
> Software solved its own — write it, run it, test it, fix it. Seconds, not months.
>
> Architecture never got that loop. A drawing goes out, and someone finds out
> much later whether it was right.
>
> But building code is checkable. Heights. Daylight. Door widths. Clearances.
> The verdict was always there. Nobody had put an engineer inside it.
>
> Now you can just say it.
>
> Recognition plans four ways at once, draws every line in code, and checks each
> one against the regulation itself — citing the article behind every finding.
> The ones that fail don't reach you.
>
> Pick the one you like. Watch it stand up.
>
> Recognition. Your AI architect.

---

## 4 · Negative prompt (paste into any model that supports one)

```
text artefacts, garbled letters, warped typography, fake UI gibberish,
watermark, stock-footage look, corporate handshake, glossy blue hologram,
neon circuit-board overlays, floating binary, robot hands, humanoid AI,
spinning globe, lens flare, heavy bloom, glitch transitions, aggressive
zoom, drone-swoop cliché, oversaturated teal-and-orange grade, cluttered
composition, motion blur on type, cheap 3D logo animation
```

## 5 · Craft notes for the edit

- **Show the rejection.** The shot where a plan fails its corridor check is the
  most persuasive four seconds in the film: it is the proof that the system
  judges rather than flatters. Do not cut it for length.
- **Let the numbers be monospace and small.** Big percentage claims read as
  advertising; a quiet `57 checked · 2 not evaluated · 0 failed` reads as
  engineering.
- **Never invent a metric.** No "10× faster", no "trusted by N firms". The
  product's whole promise is that it does not overstate what it knows.
- **One accent colour only.** If a shot needs emphasis, use cobalt or use light —
  never a second hue.
- **Silence at the end.** Let the mark hold on a near-white frame with no music
  under it; the restraint is the brand.
- **Legal register:** the film may say *checked against building code* and *cites
  the article behind every finding*. It may not say *certified*, *approved*, or
  *guaranteed compliant* — the product is a design aid, not a stamp.

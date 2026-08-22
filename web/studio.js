/* Recognition Studio.
 *
 * A static page. It reads artifacts a run already committed under data/ and
 * renders them; it never runs the pipeline itself and it never holds a secret.
 *
 * Two things happen live, and both go through GitHub with the *viewer's own*
 * token, never a stored one:
 *   - the interview can escalate from the instant rules engine to a real
 *     Devin session, relayed through the `interview` workflow (the browser
 *     cannot call the Devin API: CORS, and the key must stay server-side);
 *   - "Design it" can dispatch a real autopilot run and watch it to the
 *     merged, published result.
 *
 * Honesty rules carried from the product: every agent reply is labelled with
 * the engine that produced it, every inferred value is a visible assumption,
 * and no step ever ticks without a real event behind it.
 */
import * as THREE from "three";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const State = { run: null, project: null, candidate: null };

/* ══════════════════════════════════════════════════════════════════════
   GitHub — the viewer's own credentials, api.github.com only
   ══════════════════════════════════════════════════════════════════════ */

function detectRepo() {
  // studio served at <owner>.github.io/<repo>/ — derive; fall back for localhost.
  const host = location.hostname;
  if (host.endsWith(".github.io")) {
    const owner = host.split(".")[0];
    const seg = location.pathname.split("/").filter(Boolean)[0];
    if (owner && seg) return `${owner}/${seg}`;
  }
  return "0-uddeshya-0/Recognition";
}

const GH = {
  repo: detectRepo(),
  get token() { return localStorage.getItem("recognition.gh_token") || ""; },
  set token(v) { v ? localStorage.setItem("recognition.gh_token", v) : localStorage.removeItem("recognition.gh_token"); },
  get on() { return !!this.token; },

  async api(path, opts = {}) {
    const r = await fetch(`https://api.github.com${path}`, {
      ...opts,
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${this.token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        ...(opts.headers || {}),
      },
    });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 140)}`);
    return r.status === 204 ? true : r.json();
  },

  dispatch(event_type, client_payload) {
    return this.api(`/repos/${this.repo}/dispatches`, {
      method: "POST",
      body: JSON.stringify({ event_type, client_payload }),
    });
  },

  async raw(path, ref) {
    const r = await fetch(
      `https://api.github.com/repos/${this.repo}/contents/${path}?ref=${ref}&t=${Date.now()}`,
      { headers: { Accept: "application/vnd.github.raw+json", Authorization: `Bearer ${this.token}` } },
    );
    return r.ok ? r.json() : null;
  },

  async findRun(workflow, sinceMs) {
    const d = await this.api(`/repos/${this.repo}/actions/runs?event=repository_dispatch&per_page=10`);
    return (d?.workflow_runs || []).find(
      (r) => r.path?.endsWith(`/${workflow}.yml`) && Date.parse(r.created_at) >= sinceMs - 15000,
    ) || null;
  },
};

/* ══════════════════════════════════════════════════════════════════════
   The brief — one state object behind both the chat and the form.
   Every slot knows who set it: "you", "devin", or "assumed".
   ══════════════════════════════════════════════════════════════════════ */

const ROOM_LABELS = {
  bedroom: "Bedroom", living: "Living room", kitchen: "Kitchen",
  bathroom: "Bathroom", office: "Study", utility: "Utility", hall: "Hall", other: "Room",
};
const CLASS_LABELS = {
  detached_house: "A detached house", semi_detached: "A semi-detached house",
  apartment_block: "An apartment building",
};

const Brief = {
  f: {},          // fields
  src: {},        // slot -> you | devin | assumed
  reset() {
    this.f = {
      project: "Neubau", bundesland: "BY", building_class: "detached_house",
      plot_width_m: 18, plot_depth_m: 24, dwelling_count: null, storey_count: 1,
      storey_height_m: 2.5, occupants: null, rooms: {}, accessibility_tier: "none",
      notes: "",
    };
    this.src = {};
    renderSheet();
  },
  set(slot, value, by) {
    this.f[slot] = value;
    this.src[slot] = by;
    renderSheet();
  },
  addRooms(patch, by) {   // {bedroom: 3, ...} — counts replace, they don't stack
    for (const [cat, n] of Object.entries(patch)) {
      if (n > 0) this.f.rooms[cat] = n; else delete this.f.rooms[cat];
      this.src[`room:${cat}`] = by;
    }
    if (Object.keys(patch).length) this.src.rooms = by;
    renderSheet();
  },
  get blockingOpen() {
    // dwelling_count is required by a tier:law rule; a programme must exist.
    return this.f.dwelling_count == null || !Object.keys(this.f.rooms).length;
  },
  /* The sealed DesignBrief. Facilities the law requires (kitchen, bathroom)
     are added here as *visible* assumptions, never silently. */
  seal() {
    const assumptions = [];
    const rooms = { ...this.f.rooms };
    for (const [cat, basis] of [
      ["kitchen", "BayBO Art. 46: every dwelling needs a kitchen"],
      ["bathroom", "BayBO Art. 46: every dwelling needs a bathroom"],
    ]) {
      if (!rooms[cat]) {
        rooms[cat] = 1;
        assumptions.push({ slot: `rooms.${cat}`, value: 1, basis, confidence: "high", confirmed: false });
      }
    }
    if (this.f.dwelling_count == null) return null;
    for (const [slot, value, basis] of [
      ["storey_height_m", 2.5, "BayBO Art. 45 (1) minimum 2.40 m + 100 mm build-up"],
      ["storey_count", 1, "v1 designs a single storey"],
    ]) {
      if (!this.src[slot]) assumptions.push({ slot, value, basis, confidence: "high", confirmed: false });
    }
    if (!this.src.plot_width_m) {
      assumptions.push({ slot: "plot", value: `${this.f.plot_width_m} × ${this.f.plot_depth_m} m`, basis: "default plot; correct it if yours differs", confidence: "low", confirmed: false });
    }
    return {
      project: this.f.project, bundesland: "BY", building_class: this.f.building_class,
      plot_width_m: this.f.plot_width_m, plot_depth_m: this.f.plot_depth_m,
      dwelling_count: this.f.dwelling_count, storey_count: 1,
      storey_height_m: this.f.storey_height_m, occupants: this.f.occupants || 4,
      rooms: Object.entries(rooms).map(([category, count]) => ({ category, count, min_area_m2: null, label: null })),
      accessibility_tier: this.f.accessibility_tier, assumptions,
      notes: this.f.notes.trim(), schema: "designbrief/v1",
    };
  },
};

function srcTag(by) {
  if (!by) return null;
  const s = el("span", "src" + (by === "devin" ? " devin" : ""),
    by === "you" ? "· you" : by === "devin" ? "· Devin" : "· assumed");
  return s;
}

function renderSheet() {
  const dl = $("sheet-fields");
  dl.innerHTML = "";
  const f = Brief.f;
  const roomsTxt = Object.entries(f.rooms).map(([c, n]) => `${n}× ${ROOM_LABELS[c] || c}`).join(" · ");
  const rows = [
    ["project", f.project, Brief.src.project],
    ["building", CLASS_LABELS[f.building_class], Brief.src.building_class],
    ["homes", f.dwelling_count == null ? "" : String(f.dwelling_count), Brief.src.dwelling_count],
    ["rooms", roomsTxt, Brief.src.rooms],
    ["plot", `${f.plot_width_m} × ${f.plot_depth_m} m`, Brief.src.plot_width_m],
    ["ceiling", `${f.storey_height_m.toFixed(2)} m`, Brief.src.storey_height_m],
    ["barrier-free", f.accessibility_tier === "none" ? "not requested" : "DIN 18040-2" + (f.accessibility_tier.endsWith("_R") ? " (R)" : ""), Brief.src.accessibility_tier],
    ["notes", f.notes.trim(), Brief.src.notes],
  ];
  for (const [k, v, by] of rows) {
    const row = el("div");
    row.append(el("dt", null, k));
    const dd = el("dd", v ? "" : "empty", v || "—");
    const tag = srcTag(v ? by : null);
    if (tag) dd.append(tag);
    row.append(dd);
    dl.append(row);
  }
  renderAssumptions();
  const go = $("go");
  go.disabled = Brief.blockingOpen;
  $("go-hint").textContent = Brief.blockingOpen
    ? "Still needed: " + [Brief.f.dwelling_count == null && "how many homes", !Object.keys(Brief.f.rooms).length && "which rooms"].filter(Boolean).join(" · ")
    : "Nobody touches the run once it starts.";
}

function renderAssumptions() {
  const box = $("assumed-chips");
  box.innerHTML = "";
  const f = Brief.f;
  const chips = [];
  if (!Brief.src.storey_height_m) chips.push(["ceiling", "2.50 m", "BayBO Art. 45 (1) min 2.40 m + build-up"]);
  chips.push(["storeys", "1", "v1 designs a single storey"]);
  chips.push(["glazing", "1/8 of floor area", "BayBO Art. 45 (2)"]);
  if ((f.dwelling_count || 0) > 2 && f.accessibility_tier === "none") {
    chips.push(["barrier-free", "DIN 18040-2", "BayBO Art. 48 (1): more than 2 homes"]);
  }
  if (!f.rooms.kitchen) chips.push(["kitchen", "+1", "BayBO Art. 46: a dwelling needs one"]);
  if (!f.rooms.bathroom) chips.push(["bathroom", "+1", "BayBO Art. 46: a dwelling needs one"]);
  chips.forEach(([k, v, basis]) => {
    const c = el("span", "chip");
    c.append(el("span", null, k + " "), el("b", null, v), el("span", "basis", "· " + basis));
    box.append(c);
  });
}

/* ══════════════════════════════════════════════════════════════════════
   The parser — deterministic intent extraction. It only ever *shows* what
   it understood; anything it is unsure of stays a question.
   ══════════════════════════════════════════════════════════════════════ */

const NUM_WORDS = {
  a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
  ein: 1, eine: 1, einem: 1, zwei: 2, drei: 3, vier: 4, "fünf": 5, fuenf: 5, sechs: 6,
};
const CAT_WORDS = [
  [/bed\s?rooms?|schlafzimmer|kinderzimmer|kids?['’]?\s?rooms?|children'?s rooms?|guest\s?rooms?|g[äa]stezimmer/, "bedroom"],
  [/bath\s?rooms?|bäder|b[äa]dezimmer|\bbad\b|\bwc\b|toilets?|shower rooms?|duschbad/, "bathroom"],
  [/kitchens?|küchen?|kueche/, "kitchen"],
  [/living\s?rooms?|lounge|wohnzimmer|wohnbereich/, "living"],
  [/stud(?:y|ies)|offices?|home\s?office|büros?|buero|arbeitszimmer/, "office"],
  [/utilit(?:y|ies)|laundry|hwr|hauswirtschaftsraum|storage room|abstellraum/, "utility"],
];

function wordNum(s) {
  const n = parseInt(s, 10);
  if (!Number.isNaN(n)) return n;
  return NUM_WORDS[s.toLowerCase()] ?? null;
}

function parseUtterance(text) {
  const t = " " + text.toLowerCase() + " ";
  const got = [];            // [label, value] chips shown back to the client
  const rooms = {};

  // rooms with counts: "three bedrooms", "2 Bäder", "a study"
  const numPat = "(\\d+|one|two|three|four|five|six|a|an|ein|eine|zwei|drei|vier|fünf|fuenf|sechs)";
  for (const [pat, cat] of CAT_WORDS) {
    const re = new RegExp(`${numPat}\\s+(?:${pat.source})|(?:${pat.source})`, "gi");
    let m, count = 0, seen = false;
    while ((m = re.exec(t)) !== null) {
      seen = true;
      count += m[1] ? (wordNum(m[1]) ?? 1) : 1;
      if (!m[1]) count = Math.max(count, 1);
    }
    if (seen) rooms[cat] = Math.min(Math.max(rooms[cat] || 0, count), 6);
  }
  for (const [cat, n] of Object.entries(rooms)) got.push([ROOM_LABELS[cat].toLowerCase(), `× ${n}`]);

  const patch = {};

  // dwellings: "three families", "2 apartments", "dreifamilienhaus", "duplex"
  const dw = t.match(new RegExp(`${numPat}\\s+(?:famil(?:y|ies|ien)|homes?|households?|apartments?|flats?|units?|wohnungen|wohneinheiten|parteien)`));
  if (dw) patch.dwelling_count = wordNum(dw[1]);
  else if (/dreifamilien|three.?family/.test(t)) patch.dwelling_count = 3;
  else if (/zweifamilien|two.?family|duplex|doppelhaus/.test(t)) patch.dwelling_count = 2;
  else if (/einfamilien|single.?family|just (us|our family)|nur wir/.test(t)) patch.dwelling_count = 1;
  if (patch.dwelling_count) got.push(["homes", String(patch.dwelling_count)]);

  // building class
  if (/apartment (building|block)|mehrfamilienhaus|wohnblock/.test(t)) patch.building_class = "apartment_block";
  else if (/semi.?detached|doppelhaush[äa]lfte/.test(t)) patch.building_class = "semi_detached";
  else if (/detached|einfamilienhaus|freistehend/.test(t)) patch.building_class = "detached_house";
  if (patch.building_class) got.push(["building", CLASS_LABELS[patch.building_class].toLowerCase()]);

  // plot: "18 x 24", "18 by 24 m", "18×24m"
  const plot = t.match(/(\d{1,3})\s*(?:x|×|by|mal)\s*(\d{1,3})\s*(?:m\b|met)/);
  if (plot) {
    patch.plot_width_m = +plot[1]; patch.plot_depth_m = +plot[2];
    got.push(["plot", `${plot[1]} × ${plot[2]} m`]);
  }

  // occupants: "family of four", "zu fünft", "5 people"
  const occ = t.match(new RegExp(`family of ${numPat}|${numPat}\\s+(?:people|persons?|personen)|zu\\s+(dritt|viert|fünft|sechst)`));
  if (occ) {
    const zu = { dritt: 3, viert: 4, "fünft": 5, sechst: 6 };
    patch.occupants = occ[3] ? zu[occ[3]] : wordNum(occ[1] || occ[2]);
    if (patch.occupants) got.push(["household", `${patch.occupants} people`]);
  }

  // accessibility
  if (/wheelchair|rollstuhl/.test(t)) patch.accessibility_tier = "din18040_2_R";
  else if (/barrier.?free|barrierefrei|accessible|step.?free|altersgerecht/.test(t)) patch.accessibility_tier = "din18040_2";
  if (patch.accessibility_tier) got.push(["barrier-free", "DIN 18040-2" + (patch.accessibility_tier.endsWith("_R") ? " (R)" : "")]);

  // storeys — v1 is single-storey; be honest rather than quietly flattening
  const st = t.match(new RegExp(`${numPat}\\s+(?:store(?:y|ys|ies)|floors?|geschoss(?:e|ig)?|stockwerke?|etagen)`));
  const storeysAsked = st ? wordNum(st[1]) : (/zweigeschossig|two.?stor(?:e?y|ies)/.test(t) ? 2 : null);

  // project name: "for the Weber family", "für Familie Huber"
  const name = text.match(/(?:for the|für(?: die)?(?: Familie)?|for)\s+([A-ZÄÖÜ][a-zA-Zäöüß]+)(?:\s+family|\s+familie)?/);
  if (name && /family|familie|Familie/.test(text)) {
    patch.project = `Haus ${name[1]}`;
    got.push(["project", patch.project]);
  }

  return { patch, rooms, got, storeysAsked };
}

/* ══════════════════════════════════════════════════════════════════════
   The chat — two agents, each labelled. The instant agent is this file
   (deterministic slot-filling; the questions come from the rules). The
   live agent is a Devin session relayed through the interview workflow.
   ══════════════════════════════════════════════════════════════════════ */

const Chat = {
  transcript: [],                 // {role: client|interviewer, text}
  id: null, round: 0, session: "", waiting: false,
  askedDwelling: false, askedRooms: false, askedPlot: false, askedFinal: false,
};

function addMsg(who, text, { meta, got, wait } = {}) {
  const li = el("li", `msg ${who}${wait ? " wait" : ""}`);
  li.append(el("div", "bubble", text));
  if (got?.length) {
    const row = el("div", "got");
    got.forEach(([k, v]) => {
      const c = el("span", "chip");
      c.append(el("span", null, k + " "), el("b", null, v));
      row.append(c);
    });
    li.append(row);
  }
  if (meta) { const m = el("div", "meta"); m.append(meta); li.append(m); }
  $("chat-log").append(li);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return li;
}

function agentSay(text, { chips = [], devin = false, sessionUrl = "" } = {}) {
  const meta = el("span");
  if (devin) {
    meta.append("Devin · live session");
    if (sessionUrl) {
      meta.append(" · ");
      const a = el("a", null, "watch ↗");
      a.href = sessionUrl; a.target = "_blank"; a.rel = "noopener";
      meta.append(a);
    }
  } else {
    meta.append("rules engine · instant");
  }
  addMsg(devin ? "devin" : "agent", text, { meta });
  Chat.transcript.push({ role: "interviewer", text });
  setChips(chips);
}

function setChips(chips) {
  const row = $("chat-chips");
  row.innerHTML = "";
  chips.forEach(({ label, send }) => {
    const b = el("button", "qchip", label);
    b.type = "button";
    b.onclick = () => { if (!Chat.waiting) submitUtterance(send ?? label); };
    row.append(b);
  });
}

/* What the instant agent says next — ordered by what the rules still need. */
function instantNext(parsed) {
  const f = Brief.f;
  if (parsed?.storeysAsked > 1) {
    agentSay(
      `Noted — you'd like ${parsed.storeysAsked} storeys. v1 of this pipeline designs a single storey, so I'll plan the ground floor and keep the wish in the notes.`,
    );
    Brief.set("notes", (f.notes + ` Client asked for ${parsed.storeysAsked} storeys (v1 designs one).`).trim(), "you");
  }
  if (f.dwelling_count == null) {
    if (!Chat.askedDwelling) {
      Chat.askedDwelling = true;
      agentSay(
        "How many homes will the building hold? Above two, barrier-free rules kick in automatically — that's why I ask.",
        { chips: [{ label: "Just one" , send: "One home"}, { label: "Two", send: "Two homes" }, { label: "Three", send: "Three homes" }] },
      );
      return;
    }
  }
  if (!Object.keys(f.rooms).length) {
    if (!Chat.askedRooms) {
      Chat.askedRooms = true;
      agentSay(
        "Which rooms, and how many? Say it in your own words — \"three bedrooms, a study, an open kitchen\" works.",
        { chips: [{ label: "3 bed family home", send: "Three bedrooms, a living room, an open kitchen, one bathroom and a study" }] },
      );
      return;
    }
  }
  if (Brief.blockingOpen) return;   // asked already; wait for the answer
  if (!Chat.askedPlot && !Brief.src.plot_width_m) {
    Chat.askedPlot = true;
    agentSay(
      `How big is the plot? I'll assume ${f.plot_width_m} × ${f.plot_depth_m} m if you're not sure.`,
      { chips: [{ label: `Use ${f.plot_width_m} × ${f.plot_depth_m} m`, send: "Use the default plot" }] },
    );
    return;
  }
  if (!Chat.askedFinal) {
    Chat.askedFinal = true;
    agentSay(
      "Anything else I should know — orientation, a view to keep, how you live? Otherwise the brief on the right is ready: press Design it.",
      { chips: [{ label: "That's everything — design it", send: "That's everything" }] },
    );
    return;
  }
  agentSay("The brief is ready — press Design it, or keep refining. Every assumption on the right stays editable.");
}

function applyParsed(parsed, by) {
  const { patch, rooms } = parsed;
  Brief.addRooms(rooms, by);
  for (const [k, v] of Object.entries(patch)) Brief.set(k, v, by);
}

async function submitUtterance(text) {
  text = text.trim();
  if (!text || Chat.waiting) return;
  addMsg("you", text);
  Chat.transcript.push({ role: "client", text });
  $("chat-input").value = "";
  autoGrow();

  const parsed = parseUtterance(text);
  if (/use the default plot/i.test(text)) Chat.askedPlot = true;
  if (/that'?s everything/i.test(text)) Chat.askedFinal = true;
  applyParsed(parsed, "you");
  Brief.set("notes", (Brief.f.notes + " " + text).trim().slice(0, 2000), Brief.src.notes || "you");

  if ($("chat-engine").value === "devin") return devinRound();

  if (parsed.got.length) {
    const li = $("chat-log").lastElementChild;
    // echo what was understood under the client's own message
    const row = el("div", "got");
    parsed.got.forEach(([k, v]) => {
      const c = el("span", "chip");
      c.append(el("span", null, k + " "), el("b", null, v));
      row.append(c);
    });
    li.append(row);
  }
  instantNext(parsed);
}

/* --- the live agent: one round = one workflow run = one Devin turn ------ */

async function devinRound() {
  if (!GH.on) {
    openPop();
    agentSay("Live Devin needs a GitHub connection — the session runs in this repository's Actions so no key ever reaches this page. Connect, or switch back to instant.");
    return;
  }
  Chat.id = Chat.id || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())).replace(/[^a-zA-Z0-9-]/g, "").slice(0, 40);
  Chat.round += 1;
  Chat.waiting = true;
  $("chat-send").dataset.state = "busy";
  $("chat-engine").disabled = true;

  const wait = addMsg("agent", "Devin is reading the conversation… the session runs in CI, so the first reply usually takes 2–4 minutes.", { wait: true });
  const meta = el("div", "meta");
  wait.append(meta);
  const t0 = Date.now();
  const tick = setInterval(() => {
    meta.textContent = `waiting ${Math.round((Date.now() - t0) / 1000)}s · relayed through Actions`;
  }, 1000);
  setChips([{ label: "Stop waiting", send: "__cancel__" }]);
  const cancel = { hit: false };
  $("chat-chips").firstChild.onclick = () => { cancel.hit = true; };

  try {
    await GH.dispatch("interview", {
      id: Chat.id, round: Chat.round, session_id: Chat.session,
      messages: Chat.transcript.slice(-30).map((m) => ({ role: m.role, text: m.text.slice(0, 2000) })),
      known: Brief.f,
    });
  } catch (e) {
    clearInterval(tick); wait.remove(); endWait();
    agentSay(`Could not start the round: ${e.message}. Check the token's permissions (Contents read & write on ${GH.repo}).`);
    return;
  }

  // surface the run link as soon as Actions picks it up
  GH.findRun("interview", t0).then((r) => {
    if (r) {
      meta.append(" · ");
      const a = el("a", null, "run ↗"); a.href = r.html_url; a.target = "_blank"; a.rel = "noopener";
      meta.append(a);
    }
  }).catch(() => {});

  const path = `interviews/${Chat.id}/reply-${Chat.round}.json`;
  let reply = null;
  const deadline = t0 + 12 * 60 * 1000;
  while (Date.now() < deadline && !cancel.hit) {
    await sleep(6000);
    reply = await GH.raw(path, "studio-interviews").catch(() => null);
    if (reply) break;
  }
  clearInterval(tick);
  wait.remove();
  endWait();

  if (!reply) {
    agentSay(cancel.hit
      ? "Stopped waiting. The round may still finish — ask again to pick it up, or continue with the instant agent."
      : "No reply arrived within 12 minutes. The workflow log will say why — ask again to retry.",
      { chips: [{ label: "Ask Devin again", send: "__retry__" }] });
    $("chat-chips").firstChild.onclick = () => { Chat.round -= 1; devinRound(); };
    return;
  }

  Chat.session = reply.session_id || Chat.session;
  if (reply.brief && Object.keys(reply.brief).length) {
    const b = reply.brief;
    if (b.rooms?.length) Brief.addRooms(Object.fromEntries(b.rooms.map((r) => [r.category, r.count || 1])), "devin");
    for (const k of ["project", "building_class", "dwelling_count", "plot_width_m", "plot_depth_m", "occupants", "accessibility_tier", "notes"]) {
      if (b[k] != null && b[k] !== "" && JSON.stringify(b[k]) !== JSON.stringify(Brief.f[k])) Brief.set(k, b[k], "devin");
    }
  }
  const chips = (reply.questions || []).flatMap((q) =>
    (q.options || []).slice(0, 4).map((o) => ({ label: o, send: o })));
  agentSay(reply.message || "…", { devin: true, sessionUrl: reply.session_url, chips });
  if (reply.done && reply.sealed_brief) {
    agentSay("Devin sealed the brief — every field on the right is filled, and every inferred value is registered as an assumption. Press Design it when you're ready.", { devin: true, sessionUrl: reply.session_url });
  } else if (reply.contract_error && !reply.questions?.length) {
    agentSay(`(validator: ${reply.contract_error})`);
  }
}

function endWait() {
  Chat.waiting = false;
  delete $("chat-send").dataset.state;
  $("chat-engine").disabled = false;
  setChips([]);
}

/* ══════════════════════════════════════════════════════════════════════
   The form — the same brief, for people who'd rather not chat
   ══════════════════════════════════════════════════════════════════════ */

const FORM_ROOMS = ["living", "kitchen", "bedroom", "bathroom", "office", "utility"];

function renderForm() {
  const list = $("qlist");
  list.innerHTML = "";
  const add = (title, why, field) => {
    const li = el("li", "q");
    const head = el("div", "qh");
    head.append(el("span", "num"), el("label", "qt", title));
    li.append(head);
    const w = el("p", "why"); w.innerHTML = why; li.append(w);
    li.append(field);
    list.append(li);
  };

  const cls = el("div", "opts");
  Object.entries(CLASS_LABELS).forEach(([val, label]) => {
    const b = el("button", "opt", label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(Brief.f.building_class === val));
    b.onclick = () => {
      Brief.set("building_class", val, "you");
      [...cls.children].forEach((c) => c.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
    };
    cls.append(b);
  });
  add("What are you building?", "Selects which rules apply.", cls);

  const dw = el("div", "pair");
  const dwi = el("input");
  Object.assign(dwi, { type: "number", min: 1, max: 24, value: Brief.f.dwelling_count ?? "" });
  dwi.placeholder = "1";
  dwi.oninput = () => Brief.set("dwelling_count", dwi.value ? Math.max(1, +dwi.value) : null, "you");
  dw.append(dwi, el("span", null, "homes"));
  add("How many homes are in it?", "Required by <b>BayBO Art. 48 (1)</b> — above two, one storey must be barrier-free.", dw);

  const grid = el("div", "rooms-grid");
  FORM_ROOMS.forEach((cat) => {
    const count = Brief.f.rooms[cat] || 0;
    const row = el("div", "room-row" + (count ? " on" : ""));
    const n = el("span", "n", String(count));
    const dec = el("button", null, "−"); dec.type = "button"; dec.setAttribute("aria-label", `fewer ${ROOM_LABELS[cat]}`);
    const inc = el("button", null, "+"); inc.type = "button"; inc.setAttribute("aria-label", `more ${ROOM_LABELS[cat]}`);
    const set = (v) => {
      const nv = Math.max(0, Math.min(6, v));
      Brief.addRooms({ [cat]: nv }, "you");
      n.textContent = String(nv);
      row.classList.toggle("on", nv > 0);
    };
    dec.onclick = () => set((Brief.f.rooms[cat] || 0) - 1);
    inc.onclick = () => set((Brief.f.rooms[cat] || 0) + 1);
    const step = el("div", "stepper");
    step.append(dec, n, inc);
    row.append(el("span", "nm", ROOM_LABELS[cat]), step);
    grid.append(row);
  });
  add("Which rooms, and how many?", "The programme. A dwelling needs a kitchen and a bathroom — <b>BayBO Art. 46</b>.", grid);

  const plot = el("div", "pair");
  const w = el("input"), d = el("input");
  Object.assign(w, { type: "number", min: 5, max: 100, value: Brief.f.plot_width_m });
  Object.assign(d, { type: "number", min: 5, max: 100, value: Brief.f.plot_depth_m });
  const upd = () => { Brief.set("plot_width_m", +w.value || 18, "you"); Brief.set("plot_depth_m", +d.value || 24, "you"); };
  w.oninput = upd; d.oninput = upd;
  plot.append(w, el("span", null, "×"), d, el("span", null, "m"));
  add("How big is the plot?", "Bounds the envelope. Leave it if you're not sure.", plot);

  const notes = el("input");
  Object.assign(notes, { type: "text", placeholder: "e.g. living room facing the garden, south", value: "" });
  notes.oninput = () => Brief.set("notes", notes.value, "you");
  add("Anything else we should know?", "Free text — orientation, a view to keep, how you live in it.", notes);
}

/* ══════════════════════════════════════════════════════════════════════
   Design it — dispatch a real run and watch it, or hand off honestly
   ══════════════════════════════════════════════════════════════════════ */

const slugify = (s) => {
  let out = "";
  for (const ch of s.toLowerCase()) out += /[a-z0-9]/.test(ch) ? ch : "-";
  while (out.includes("--")) out = out.replaceAll("--", "-");
  return out.replace(/^-+|-+$/g, "") || "project";
};

function renderStepList(items) {
  // items: [{label, rt, state: done|run|pend|fail}]
  const list = $("steps");
  list.innerHTML = "";
  for (const it of items) {
    const li = el("li", `step ${it.state}`);
    li.append(el("span", "dot"), el("span", "lb", it.label));
    const rt = el("span", "rt");
    if (it.href) { const a = el("a", null, it.rt || "log ↗"); a.href = it.href; a.target = "_blank"; a.rel = "noopener"; rt.append(a); }
    else rt.textContent = it.rt || "";
    li.append(rt);
    list.append(li);
  }
}

async function designIt() {
  const sealed = Brief.seal();
  if (!sealed) return;
  const engine = $("run-engine").value;
  show("working");
  $("working-extra").innerHTML = "";
  $("run-links").innerHTML = "";
  $("working-note").textContent = "";

  if (!GH.on) return handoff(sealed, engine);

  $("working-title").textContent = engine === "devin" ? "Devin is designing" : "Designing";
  $("working-sub").textContent = engine === "devin"
    ? "Three Devin sessions plan three structurally different layouts in parallel; deterministic code builds and verifies each."
    : "One brief, three layouts, each checked on its own. Nobody touches the run.";
  renderStepList([{ label: "Dispatching the brief", rt: "repository_dispatch", state: "run" }]);

  const t0 = Date.now();
  try {
    await GH.dispatch("design-request", { brief_json: sealed, engine });
  } catch (e) {
    renderStepList([{ label: "Dispatching the brief", rt: e.message.slice(0, 60), state: "fail" }]);
    $("working-note").textContent = "The dispatch failed — check the token's permissions, or run it locally: uv run recognition autopilot <brief>";
    backRow();
    return;
  }

  // find the run
  renderStepList([
    { label: "Dispatching the brief", rt: "sent", state: "done" },
    { label: "Waiting for Actions to pick it up", state: "run" },
  ]);
  let run = null;
  for (let i = 0; i < 20 && !run; i++) { await sleep(4000); run = await GH.findRun("autopilot", t0).catch(() => null); }
  if (!run) {
    renderStepList([{ label: "Dispatching the brief", rt: "sent", state: "done" },
                    { label: "Waiting for Actions to pick it up", rt: "no run appeared in 80 s", state: "fail" }]);
    $("working-note").textContent = "Check the repository's Actions tab.";
    backRow();
    return;
  }
  const runLink = el("a", null, "run ↗"); runLink.href = run.html_url; runLink.target = "_blank"; runLink.rel = "noopener";
  $("run-links").append(runLink);

  // live steps from the jobs API — real names, real states, nothing invented
  const slug = slugify(sealed.project);
  const before = await fetch(`data/${slug}/run.json`, { cache: "no-store" }).then((r) => r.ok ? r.text() : null).catch(() => null);
  let conclusion = null;
  while (!conclusion) {
    await sleep(6000);
    const jobs = await GH.api(`/repos/${GH.repo}/actions/runs/${run.id}/jobs`).catch(() => null);
    const steps = jobs?.jobs?.[0]?.steps || [];
    const items = steps.filter((s) => !/^Set up|^Complete|Post /.test(s.name)).map((s) => ({
      label: s.name,
      rt: s.conclusion || s.status,
      state: s.conclusion === "success" ? "done" : s.conclusion ? "fail" : s.status === "in_progress" ? "run" : "pend",
    }));
    if (items.length) renderStepList(items);
    const r = await GH.api(`/repos/${GH.repo}/actions/runs/${run.id}`).catch(() => null);
    if (r?.status === "completed") conclusion = r.conclusion || "failure";
  }

  if (conclusion !== "success") {
    $("working-note").textContent = "No candidate cleared the compliance gate, or the run failed — nothing was merged, by design. The log has the findings.";
    backRow();
    return;
  }

  // green run merged itself; now the Studio publish rides the Pages deploy
  const cur = [...$("steps").children].map((li) => ({ label: li.querySelector(".lb").textContent, rt: li.querySelector(".rt").textContent, state: "done" }));
  cur.push({ label: "Publishing to the Studio (Pages deploy)", state: "run" });
  renderStepList(cur);
  const deadline = Date.now() + 5 * 60 * 1000;
  let published = false;
  while (Date.now() < deadline) {
    await sleep(8000);
    const now = await fetch(`data/${slug}/run.json`, { cache: "no-store" }).then((r) => r.ok ? r.text() : null).catch(() => null);
    if (now && now !== before) { published = true; break; }
  }
  if (!published) {
    $("working-note").textContent = "The run merged, but the Pages deploy hasn't landed yet — reload in a minute and it will be under Already built.";
    backRow();
    return;
  }
  await loadIndex();
  openProject(slug);
}

/* The honest hand-off when no token is connected: the page cannot run the
   pipeline, so it says so and hands over everything needed to run it. */
function handoff(sealed, engine) {
  $("working-title").textContent = "Ready to run";
  renderStepList([{ label: "Brief sealed", rt: "the last moment a person is involved", state: "done" }]);
  $("working-sub").textContent =
    "This page is static, so it cannot start the pipeline by itself. Your brief is ready — run it with one command, or connect GitHub (top right) to trigger runs from here.";
  $("working-note").textContent = `uv run recognition autopilot brief.json${engine === "devin" ? " --engine devin" : ""} --publish`;
  const blob = new Blob([JSON.stringify(sealed, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = el("a", "primary", "Download the brief");
  a.href = url; a.download = "brief.json";
  a.style.display = "inline-block"; a.style.textDecoration = "none";
  const back = el("button", "ghost", "Look at a finished design");
  back.type = "button";
  back.onclick = () => { URL.revokeObjectURL(url); show("brief"); $("existing").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth" }); };
  const row = el("div", "brief-actions");
  row.append(a, back);
  $("working-extra").append(row);
}

function backRow() {
  const back = el("button", "ghost", "Back to the brief");
  back.type = "button";
  back.onclick = () => show("brief");
  const row = el("div", "brief-actions");
  row.append(back);
  $("working-extra").append(row);
}

/* ══════════════════════════════════════════════════════════════════════
   The 3D viewer
   ══════════════════════════════════════════════════════════════════════ */

const COLOR = {
  bg: 0xffffff, wall: 0x9aa5ae, space: 0xdfe6ec,
  door: 0xd07a2a, window: 0x2a62d8, edge: 0x2a3138, ground: 0xe4e8ec,
};
/* Room tints stay low-chroma and steer clear of verdict green/red — colour
   that means pass/fail must never appear as decoration. */
const SPACE_TINT = {
  living: 0xe9dfc8, kitchen: 0xdde5e9, bedroom: 0xd9e2ef, bathroom: 0xcfe0ea,
  office: 0xe4deef, hall: 0xe7e9eb, utility: 0xe3e6e0, other: 0xe6e4df,
};
const kindOf = (cls) =>
  cls === "IfcSpace" ? "space" : cls === "IfcDoor" ? "door" : cls === "IfcWindow" ? "window" : "wall";

let V = null;

function viewer() {
  if (V) return V;
  const host = $("v3-host");
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.className = "v3-canvas";
  host.append(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COLOR.bg);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 2000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.maxPolarAngle = Math.PI * 0.495;
  // a quiet idle orbit until the first touch — interruptible, and off
  // entirely for people who asked for reduced motion
  controls.autoRotate = !REDUCED;
  controls.autoRotateSpeed = 0.5;
  host.addEventListener("pointerdown", () => { controls.autoRotate = false; }, { once: true });

  scene.add(new THREE.HemisphereLight(0xffffff, 0xc7ced5, 1.15), new THREE.AmbientLight(0xffffff, 0.4));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(14, 22, 10);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  scene.add(sun);

  V = { renderer, scene, camera, controls, host, root: null, ground: null, sun,
        raycaster: new THREE.Raycaster(), pointer: new THREE.Vector2(), spaces: [] };

  const resize = () => {
    const w = host.clientWidth || 1, h = host.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(host);
  resize();

  host.addEventListener("pointermove", onHover);
  host.addEventListener("pointerleave", () => $("hoverchip").classList.add("hide"));

  (function loop() {
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  })();
  return V;
}

function loadMesh(json) {
  const v = viewer();
  if (v.root) { v.scene.remove(v.root); disposeTree(v.root); }
  if (v.ground) { v.scene.remove(v.ground); disposeTree(v.ground); }
  const root = new THREE.Group();
  v.spaces = [];

  const [x0, y0, z0, x1, y1, z1] = json.bounds;
  const mid = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
  const span = Math.max(x1 - x0, y1 - y0, z1 - z0) || 10;

  for (const e of json.elements || []) {
    const kind = kindOf(e.cls);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(e.verts, 3));
    g.setIndex(e.faces);
    const flat = g.toNonIndexed();     // flat shading keeps corners crisp
    flat.computeVertexNormals();
    g.dispose();
    flat.translate(-mid.x, -mid.y, -mid.z);

    const base = kind === "space" ? (SPACE_TINT[e.category] ?? COLOR.space) : COLOR[kind];
    const mat = new THREE.MeshLambertMaterial({
      color: base,
      transparent: kind === "space",
      opacity: kind === "space" ? 0.34 : 1,
      depthWrite: kind !== "space",
      side: kind === "space" ? THREE.DoubleSide : THREE.FrontSide,
    });
    const mesh = new THREE.Mesh(flat, mat);
    mesh.userData = { tag: e.tag, name: e.name, kind, area: e.area, base };
    if (kind === "space") v.spaces.push(mesh);
    else {
      mesh.castShadow = true;
      // ink-line edges — the drawing-office look, and corners stay legible
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(flat, 28),
        new THREE.LineBasicMaterial({ color: COLOR.edge, transparent: true, opacity: 0.28 }),
      );
      mesh.add(edges);
    }
    root.add(mesh);
  }

  // IFC is Z-up; three.js is Y-up.
  root.rotation.x = -Math.PI / 2;
  v.scene.add(root);
  v.root = root;

  // the desk the model sits on: a soft shadow catcher plus a faint grid
  const ground = new THREE.Group();
  const catcher = new THREE.Mesh(
    new THREE.CircleGeometry(span * 2.2, 64),
    new THREE.ShadowMaterial({ opacity: 0.16 }),
  );
  catcher.rotation.x = -Math.PI / 2;
  catcher.position.y = -(z1 - z0) / 2 - 0.01;
  catcher.receiveShadow = true;
  const grid = new THREE.GridHelper(span * 4, 40, 0xc7ced5, 0xdde2e7);
  grid.material.transparent = true;
  grid.material.opacity = 0.35;
  grid.position.y = catcher.position.y - 0.005;
  ground.add(catcher, grid);
  v.scene.add(ground);
  v.ground = ground;

  v.scene.fog = new THREE.Fog(COLOR.bg, span * 3, span * 7);
  v.sun.shadow.camera.left = v.sun.shadow.camera.bottom = -span * 1.4;
  v.sun.shadow.camera.right = v.sun.shadow.camera.top = span * 1.4;
  v.sun.shadow.camera.updateProjectionMatrix();

  v.camera.position.set(span * 0.95, span * 0.72, span * 1.05);
  v.controls.target.set(0, 0, 0);
  v.controls.update();
  applySpaceVisibility();
  $("v3-wait").classList.add("hide");
}

function disposeTree(obj) {
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  });
}

function applySpaceVisibility() {
  if (!V) return;
  const on = $("show-spaces").checked;
  V.spaces.forEach((m) => { m.visible = on; });
}

function onHover(ev) {
  const v = viewer();
  if (!v.root) return;
  const r = v.host.getBoundingClientRect();
  v.pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  v.raycaster.setFromCamera(v.pointer, v.camera);
  const hit = v.raycaster.intersectObjects(v.root.children, false)
    .find((h) => h.object.visible && h.object.userData.kind === "space");
  const chip = $("hoverchip");
  v.spaces.forEach((m) => { m.material.opacity = 0.34; });
  if (!hit) { chip.classList.add("hide"); return; }
  hit.object.material.opacity = 0.55;
  const d = hit.object.userData;
  chip.textContent = `${d.tag ? d.tag + "  " : ""}${d.name}${d.area ? "  ·  " + d.area + " m²" : ""}`;
  chip.style.left = `${ev.clientX - r.left}px`;
  chip.style.top = `${ev.clientY - r.top}px`;
  chip.classList.remove("hide");
}

/* ══════════════════════════════════════════════════════════════════════
   The 2D sheet — zoom and pan, because contractors squint at dimensions
   ══════════════════════════════════════════════════════════════════════ */

const Sheet = { scale: 1, tx: 0, ty: 0 };

function applySheet() {
  $("sheet-zoom").style.transform = `translate(${Sheet.tx}px, ${Sheet.ty}px) scale(${Sheet.scale})`;
  $("z-val").textContent = `${Math.round(Sheet.scale * 100)}%`;
}
function sheetReset() { Sheet.scale = 1; Sheet.tx = 0; Sheet.ty = 0; applySheet(); }
function sheetZoom(factor, cx, cy) {
  const next = Math.min(6, Math.max(0.4, Sheet.scale * factor));
  const k = next / Sheet.scale;
  if (cx != null) { Sheet.tx = cx - k * (cx - Sheet.tx); Sheet.ty = cy - k * (cy - Sheet.ty); }
  Sheet.scale = next;
  applySheet();
}

const STACKED = matchMedia("(max-width: 1080px)");

function initSheetControls() {
  const host = $("sheet-host");
  host.addEventListener("wheel", (e) => {
    // In the stacked layout the page itself scrolls; a plain wheel must keep
    // scrolling it. ctrl/⌘-wheel (and trackpad pinch, which arrives as
    // ctrl+wheel) zooms everywhere; a bare wheel zooms only on the desktop
    // grid, where the page has nothing to scroll.
    if (STACKED.matches && !e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const r = host.getBoundingClientRect();
    sheetZoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  let pan = null;
  host.addEventListener("pointerdown", (e) => {
    pan = { x: e.clientX, y: e.clientY, tx: Sheet.tx, ty: Sheet.ty };
    host.classList.add("panning");
    host.setPointerCapture(e.pointerId);
  });
  host.addEventListener("pointermove", (e) => {
    if (!pan) return;
    Sheet.tx = pan.tx + (e.clientX - pan.x);
    Sheet.ty = pan.ty + (e.clientY - pan.y);
    applySheet();
  });
  const up = () => { pan = null; host.classList.remove("panning"); };
  host.addEventListener("pointerup", up);
  host.addEventListener("pointercancel", up);
  host.addEventListener("dblclick", sheetReset);
  $("z-in").onclick = () => sheetZoom(1.25);
  $("z-out").onclick = () => sheetZoom(1 / 1.25);
  $("z-fit").onclick = sheetReset;
}

/* ══════════════════════════════════════════════════════════════════════
   Results
   ══════════════════════════════════════════════════════════════════════ */

const base = (p, c) => `data/${p}/${c}`;

async function openProject(key, candidate) {
  const run = await fetch(`data/${key}/run.json`, { cache: "no-store" }).then((r) => r.json());
  State.run = run; State.project = key;
  State.candidate = candidate || run.winner || (run.candidates[0] || {}).name;
  show("result");
  $("doc-title").textContent = run.project;
  $("restart").classList.remove("hide");
  await showCandidate(State.candidate);
}

async function showCandidate(name) {
  State.candidate = name;
  const p = State.project, dir = base(p, name);

  const verdict = await fetch(`${dir}/verdict.json`).then((r) => r.json()).catch(() => null);
  renderStamp(verdict);
  renderFindings(verdict);
  renderRooms(verdict);
  renderOptions();

  // Two very different failures used to report the same thing. "No model" when
  // the truth was "this browser has no WebGL" sends you looking in the wrong
  // place, so the fetch and the render are caught separately.
  const wait = $("v3-wait");
  wait.textContent = "loading model…";
  wait.classList.remove("hide");
  fetch(`${dir}/mesh.json`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`mesh.json ${r.status}`))))
    .then((json) => {
      try {
        loadMesh(json);
      } catch (e) {
        wait.textContent = "3D needs WebGL, which this browser did not provide";
        wait.classList.remove("hide");
        console.error("3D render failed:", e);
      }
    })
    .catch(() => { wait.textContent = "no 3D model was published for this candidate"; });

  fetch(`${dir}/sheet.svg`).then((r) => (r.ok ? r.text() : Promise.reject()))
    .then((svg) => { $("sheet-zoom").innerHTML = svg; sheetReset(); })
    .catch(() => { $("sheet-zoom").innerHTML = '<p class="hint">no sheet for this candidate</p>'; });
  $("pdf-link").href = `${dir}/sheet.pdf`;

  fetch(`${dir}/design.py`).then((r) => r.text())
    .then((src) => { $("tab-code").innerHTML = ""; $("tab-code").append(el("pre", "code", src)); })
    .catch(() => {});
}

function renderStamp(v) {
  const host = $("top-stamp");
  host.classList.remove("hide");
  host.innerHTML = "";
  if (!v) return;
  const s = el("span", `stamp ${v.ok ? "pass" : "fail"}`);
  s.append(el("span", null, v.ok ? "PASS" : "FAIL"));
  // Never a bare PASS: what we could not check is part of the answer.
  s.append(el("span", "cov",
    `${v.checked} checked · ${v.not_evaluated} not evaluated · ${v.failed} failed`));
  host.append(s);
}

const TIERS = [
  ["law", "Statute", "may block"],
  ["standard", "Standard", "blocks once triggered"],
  ["guidance", "Guidance", "advisory only"],
  ["house", "Practice", "advisory only"],
];

function renderFindings(v) {
  const box = $("tab-findings");
  box.innerHTML = "";
  if (!v) { box.append(el("p", "hint", "No compliance result.")); return; }

  const notable = (v.findings || []).filter((f) => f.status !== "passed");
  if (!notable.length) {
    box.append(el("p", "hint", "Every rule that could be evaluated passed."));
  }
  for (const [tier, label, note] of TIERS) {
    const items = notable.filter((f) => f.tier === tier);
    if (!items.length) continue;
    const g = el("div", "tier-group");
    const h = el("div", "tier-h");
    h.append(el("span", `tl ${tier}`, label), el("span", "tn", note));
    g.append(h);
    items.forEach((f) => {
      const d = el("div", `finding ${f.status}`);
      const r = el("div", "fr");
      r.append(el("span", "rid", f.rule_id));
      if (f.status === "not_evaluated") r.append(el("span", "hint", "not evaluated"));
      else if (f.blocking) r.append(el("span", "hint", "blocking"));
      d.append(r, el("div", "fm", f.message));
      const cite = el("div", "cite");
      if (f.url) {
        const a = el("a", null, f.citation);
        a.href = f.url; a.target = "_blank"; a.rel = "noopener";
        cite.append(a);
      } else cite.append(el("span", null, f.citation));
      d.append(cite);
      g.append(d);
    });
    box.append(g);
  }
}

function renderRooms(v) {
  const box = $("tab-rooms");
  box.innerHTML = "";
  const m = (v && v.metrics) || {};
  const t = el("table", "rooms");
  t.innerHTML = "<thead><tr><th>Metric</th><th>Value</th></tr></thead>";
  const body = el("tbody");
  const rows = [
    ["Rooms", m.rooms], ["Envelope", m.envelope_m2 && m.envelope_m2 + " m²"],
    ["Room area", m.room_area_m2 && m.room_area_m2 + " m²"],
    ["Circulation", m.circulation_m2 && m.circulation_m2 + " m²"],
    ["Usable ratio", m.usable_ratio && (m.usable_ratio * 100).toFixed(1) + " %"],
    ["Doors + windows", m.openings],
  ];
  rows.forEach(([k, val]) => {
    if (val == null) return;
    const tr = el("tr");
    tr.append(el("td", null, k), el("td", "n", String(val)));
    body.append(tr);
  });
  t.append(body);
  box.append(t);
}

function renderOptions() {
  const box = $("tab-options");
  box.innerHTML = "";
  const run = State.run;
  (run.candidates || []).forEach((c) => {
    const card = el("div", "opt-card" + (c.name === State.candidate ? " on" : ""));
    const h = el("div", "oh");
    h.append(el("span", "on-name", c.label || c.name));
    if (c.name === run.winner) h.append(el("span", "badge", "winner"));
    card.append(h);
    if (c.error) card.append(el("div", "od", c.error));
    const m = el("div", "om");
    m.append(el("span", null, `${c.checked} checked`),
             el("span", null, `${c.failed} failed`),
             el("span", null, `${c.not_evaluated} not evaluated`));
    if (c.devin_session) {
      const a = el("a", null, "Devin session ↗");
      a.href = `https://app.devin.ai/sessions/${String(c.devin_session).replace(/^devin-/, "")}`;
      a.target = "_blank"; a.rel = "noopener";
      a.onclick = (e) => e.stopPropagation();
      m.append(a);
    }
    card.append(m);
    card.onclick = () => showCandidate(c.name);
    box.append(card);
  });
  const note = run.engine === "devin"
    ? "Each layout was planned by its own Devin session, running in parallel; the winner was chosen by the deterministic scorer from the compliance result — not by a person, and not by a model."
    : "The winner was chosen by the scorer from the compliance result — not by a person and not by a model. Picking another here is a new view, not an approval.";
  box.append(el("p", "chosen-note", note));
}

/* ══════════════════════════════════════════════════════════════════════
   Shell
   ══════════════════════════════════════════════════════════════════════ */

function show(which) {
  ["brief", "working", "result"].forEach((v) =>
    $(`view-${v}`).classList.toggle("hide", v !== which));
}

function toast(msg, ms = 4200) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hide");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hide"), ms);
}

/* --- connect popover ----------------------------------------------------- */

function openPop() {
  $("connect-pop").classList.remove("hide");
  $("connect").setAttribute("aria-expanded", "true");
  $("gh-token").focus();
}
function closePop() {
  $("connect-pop").classList.add("hide");
  $("connect").setAttribute("aria-expanded", "false");
}

async function refreshConnect() {
  const b = $("connect");
  if (!GH.on) { b.textContent = "Connect"; b.dataset.on = ""; return; }
  b.dataset.on = "1";
  b.textContent = "Connected";
  try {
    const me = await GH.api("/user");
    if (me?.login) b.textContent = `● ${me.login}`;
  } catch { /* token may be fine-grained without user scope — still usable */ }
}

function initConnect() {
  $("connect").onclick = () => {
    $("connect-pop").classList.contains("hide") ? openPop() : closePop();
  };
  document.addEventListener("pointerdown", (e) => {
    if (!$("connect-pop").classList.contains("hide") && !e.target.closest(".connect-wrap")) closePop();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });
  $("gh-save").onclick = async () => {
    const v = $("gh-token").value.trim();
    if (!v) { $("gh-state").textContent = "paste a token first"; return; }
    GH.token = v;
    $("gh-state").textContent = "checking…";
    try {
      const repo = await GH.api(`/repos/${GH.repo}`);
      $("gh-state").textContent = repo ? "connected ✓" : "token works, repo not visible";
      $("gh-token").value = "";
      refreshConnect();
      setTimeout(closePop, 700);
    } catch (e) {
      $("gh-state").textContent = "rejected: " + e.message.slice(0, 60);
      GH.token = "";
      refreshConnect();
    }
  };
  $("gh-clear").onclick = () => {
    GH.token = "";
    $("gh-token").value = "";
    $("gh-state").textContent = "forgotten";
    refreshConnect();
  };
}

/* --- boot ---------------------------------------------------------------- */

function autoGrow() {
  const ta = $("chat-input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 130) + "px";
}

async function loadIndex() {
  let index = { projects: [] };
  try {
    index = await fetch("data/index.json", { cache: "no-store" }).then((r) => r.json());
  } catch { /* fresh repo: no runs yet */ }
  const grid = $("proj-grid");
  grid.innerHTML = "";
  $("existing").classList.toggle("hide", !index.projects.length);
  index.projects.forEach((p) => {
    const b = el("button", "proj");
    b.type = "button";
    b.append(el("div", "pn", p.project));
    b.append(el("div", "pm",
      `${p.candidates} layouts · ${p.checked} checked · ${p.not_evaluated} not evaluated · ${p.failed} failed`));
    b.onclick = () => openProject(p.key);
    grid.append(b);
  });
  return index;
}

function initModes() {
  const chat = $("mode-chat"), form = $("mode-form");
  const setMode = (m) => {
    chat.classList.toggle("on", m === "chat");
    form.classList.toggle("on", m === "form");
    chat.setAttribute("aria-selected", String(m === "chat"));
    form.setAttribute("aria-selected", String(m === "form"));
    document.querySelector(".brief-grid").classList.toggle("hide", m !== "chat");
    $("interview").classList.toggle("hide", m !== "form");
    if (m === "form") renderForm();
  };
  chat.onclick = () => setMode("chat");
  form.onclick = () => setMode("form");
}

async function boot() {
  Brief.reset();
  initModes();
  initConnect();
  initSheetControls();
  refreshConnect();

  $("composer").addEventListener("submit", (e) => { e.preventDefault(); submitUtterance($("chat-input").value); });
  $("chat-input").addEventListener("input", autoGrow);
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitUtterance($("chat-input").value); }
  });
  $("go").addEventListener("click", designIt);
  $("show-spaces").addEventListener("change", applySpaceVisibility);
  $("restart").addEventListener("click", () => {
    show("brief");
    $("top-stamp").classList.add("hide");
    $("restart").classList.add("hide");
    $("doc-title").textContent = "A house, described";
  });
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      ["findings", "rooms", "options", "code"].forEach((t) =>
        $(`tab-${t}`).classList.toggle("hide", t !== b.dataset.tab));
    };
  });

  agentSay(
    "Tell me about the house — who it's for, which rooms, anything that matters to you. I'll only ask what the building code actually needs.",
    { chips: [
      { label: "Try an example", send: "A house for our family of four — three bedrooms, a study, an open kitchen, and the living room facing the garden. Plot is 18 by 24 m." },
    ] },
  );

  await loadIndex();

  // Deep link: ?p=familienhaus&c=open
  const q = new URLSearchParams(location.search);
  if (q.get("p")) openProject(q.get("p"), q.get("c"));
}

boot().catch((e) => toast("Could not start the Studio: " + e.message));

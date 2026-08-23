/* Recognition — an AI architect you talk to.
 *
 * The flow: describe the building in your own words → the agent asks only
 * what it genuinely needs (fitted to the building type) → four structurally
 * different blueprints arrive as options → refine in words, redraft → pick
 * one → the 3D model. Regulations run underneath as the quality gate; the
 * conversation never lectures about them, and the checks are always one tap
 * away — counted honestly, cited fully.
 *
 * The page is static and holds no secret. Live work runs through GitHub
 * Actions: with the viewer's token it dispatches directly; without one it
 * hands over the exact trigger command and live-follows the run. Every agent
 * reply is labelled with the engine that produced it, and every inferred
 * value is a visible assumption. No step ticks without a real event.
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

/* ══════════════════════════════════════════════════════════════════════
   GitHub — the viewer's own credentials, api.github.com only.
   Public reads need no credential at all; only triggering does.
   ══════════════════════════════════════════════════════════════════════ */

function detectRepo() {
  const host = location.hostname;
  if (host.endsWith(".github.io")) {
    const owner = host.split(".")[0];
    const seg = location.pathname.split("/").filter(Boolean)[0];
    if (owner && seg) return `${owner}/${seg}`;
  }
  return "0-uddeshya-0/Recognition";
}

/* The demo key: a deliberately weak, Actions-only credential (it can start
   workflow runs on this one repository and nothing else). It must NOT live
   in the repository — GitHub auto-revokes its own tokens the moment they
   appear in public code, which is exactly what killed the first one. It
   arrives through the URL fragment instead (…/#k=github_pat_…): the fragment
   never reaches any server and never enters git; the page stores it locally
   and cleans the address bar. A personal token from Connect takes precedence,
   and a configured relay (config.triggerUrl) needs no key here at all. */
(() => {
  const m = location.hash.match(/[#&]k=([A-Za-z0-9_]{20,})/);
  if (m) {
    localStorage.setItem("recognition.demo_key", m[1]);
    history.replaceState(null, "", location.pathname + location.search);
  }
})();
let demoKey = localStorage.getItem("recognition.demo_key")
  || (typeof window !== "undefined" && window.RECOGNITION_CONFIG?.demoKey) || "";
const TRIGGER_URL = (typeof window !== "undefined" && window.RECOGNITION_CONFIG?.triggerUrl) || "";

/* A 401 means a credential is revoked or wrong; keeping it would poison every
   request (this page must degrade, never break). Drop it, say so, move on. */
function dropDeadKey() {
  if (GH.token) {
    GH.token = "";
    toast("Your saved GitHub token was rejected and has been forgotten.");
  } else if (demoKey) {
    demoKey = "";
    localStorage.removeItem("recognition.demo_key");
    toast("The demo key was rejected — continuing without it.");
  }
  try { refreshConnect(); } catch { /* pre-boot */ }
}

const GH = {
  repo: detectRepo(),
  get token() { return localStorage.getItem("recognition.gh_token") || ""; },
  set token(v) { v ? localStorage.setItem("recognition.gh_token", v) : localStorage.removeItem("recognition.gh_token"); },
  get on() { return !!this.token; },
  get authToken() { return this.token || demoKey; },
  get canDispatch() { return !!this.authToken || !!TRIGGER_URL; },
  get pollMs() { return this.authToken ? 5000 : 12000; },

  async api(path, opts = {}) {
    const headers = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(opts.headers || {}),
    };
    if (this.authToken) headers.Authorization = `Bearer ${this.authToken}`;
    let r = await fetch(`https://api.github.com${path}`, { ...opts, headers });
    if (r.status === 401 && this.authToken) {
      dropDeadKey();
      delete headers.Authorization;
      if (this.authToken) headers.Authorization = `Bearer ${this.authToken}`;
      r = await fetch(`https://api.github.com${path}`, { ...opts, headers });
    }
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 140)}`);
    return r.status === 204 ? true : r.json();
  },

  /* One trigger path for every credential: workflow_dispatch needs only
     Actions:write — exactly all the demo key has. A configured relay
     (config.triggerUrl) holds the token server-side instead. */
  async workflowDispatch(file, inputs) {
    if (TRIGGER_URL && !this.token) {
      const r = await fetch(TRIGGER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: file, inputs }),
      });
      if (!r.ok) throw new Error(`relay ${r.status}: ${(await r.text()).slice(0, 140)}`);
      return true;
    }
    const call = () => fetch(`https://api.github.com/repos/${this.repo}/actions/workflows/${file}/dispatches`, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${this.authToken}`,
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    });
    let r = await call();
    if (r.status === 401) {
      dropDeadKey();
      if (!this.authToken) throw new Error("the key was revoked — reopen the page from a link with a fresh #k=… key");
      r = await call();
    }
    if (!r.ok) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 140)}`);
    return true;
  },

  /* Relay reads. The CDN mirror is free but can lag ~a minute; the API is
     fresh but unauthenticated calls are scarce (60/h). So poll cheaply while
     a run is in flight and fetch fresh the moment it completes. */
  async raw(path, ref) {
    if (!this.token) {
      const r = await fetch(
        `https://raw.githubusercontent.com/${this.repo}/${ref}/${path}?t=${Date.now()}`,
        { cache: "no-store" },
      );
      return r.ok ? r.json().catch(() => null) : null;
    }
    const r = await fetch(
      `https://api.github.com/repos/${this.repo}/contents/${path}?ref=${ref}&t=${Date.now()}`,
      { headers: { Accept: "application/vnd.github.raw+json", Authorization: `Bearer ${this.token}` } },
    );
    return r.ok ? r.json() : null;
  },

  /* With no credential of our own, GitHub allows 60 anonymous calls an hour
     — one run's progress polling would eat that and the page would look
     stalled. When a relay is configured it proxies these few reads with its
     own token, so progress stays live and artifacts arrive without CDN lag. */
  get viaRelay() { return !!TRIGGER_URL && !this.authToken; },

  async relayGet(query) {
    try {
      const r = await fetch(`${TRIGGER_URL}?${query}&t=${Date.now()}`);
      return r.ok ? await r.json() : null;
    } catch { return null; }
  },

  async relayFresh(path) {
    if (this.viaRelay) return this.relayGet(`file=${encodeURIComponent(path)}`);
    const headers = { Accept: "application/vnd.github.raw+json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    try {
      const r = await fetch(
        `https://api.github.com/repos/${this.repo}/contents/${path}?ref=studio-interviews&t=${Date.now()}`,
        { headers },
      );
      if (r.ok) return await r.json();
    } catch { /* fall through to the mirror */ }
    return this.raw(path, "studio-interviews");
  },

  async runStatus(id) {
    if (this.viaRelay) {
      const d = await this.relayGet(`run=${id}`);
      return d?.status === "completed" ? (d.conclusion || "failure") : null;
    }
    const r = await this.api(`/repos/${this.repo}/actions/runs/${id}`).catch(() => null);
    return r?.status === "completed" ? (r.conclusion || "failure") : null;
  },

  async runSteps(id) {
    if (this.viaRelay) return (await this.relayGet(`jobs=${id}`))?.steps || [];
    const jobs = await this.api(`/repos/${this.repo}/actions/runs/${id}/jobs`).catch(() => null);
    return jobs?.jobs?.[0]?.steps || [];
  },

  async findRun(workflow, sinceMs) {
    const fresh = (r) => Date.parse(r.created_at) >= sinceMs - 20000;
    if (this.viaRelay) {
      const list = await this.relayGet(`runs=${workflow}.yml`);
      return (list || []).find(fresh) || null;
    }
    const d = await this.api(`/repos/${this.repo}/actions/runs?per_page=12`);
    return (d?.workflow_runs || []).find(
      (r) => r.path?.endsWith(`/${workflow}.yml`) && fresh(r),
    ) || null;
  },
};

function b64(s) { return btoa(String.fromCharCode(...new TextEncoder().encode(s))); }
function triggerCommand(workflow, field, payload, extra = "") {
  return `gh workflow run ${workflow} --repo ${GH.repo} --ref main${extra} -f ${field}="$(echo ${b64(JSON.stringify(payload))} | base64 -d)"`;
}

/* ══════════════════════════════════════════════════════════════════════
   The brief — one state object. Every slot knows who set it.
   ══════════════════════════════════════════════════════════════════════ */

const ROOM_LABELS = {
  bedroom: "Bedroom", living: "Living room", kitchen: "Kitchen",
  bathroom: "Bathroom", office: "Workspace", meeting: "Meeting room",
  lab: "Hall floor", utility: "Utility", hall: "Hallway", other: "Room",
};
const CLASS_LABELS = {
  detached_house: "A detached house", semi_detached: "A semi-detached house",
  apartment_block: "An apartment building", apartment: "An apartment",
  workplace: "A workplace", coworking_space: "A co-working space",
  office_building: "An office", practice: "A practice",
  studio_building: "A studio", warehouse: "A warehouse",
};
const RESIDENTIAL = ["detached_house", "semi_detached", "apartment_block", "apartment"];
const isWorkspace = () => !RESIDENTIAL.includes(Brief.f.building_class);
const classLabel = (c) => CLASS_LABELS[c] || ("A " + String(c).replaceAll("_", " "));

const Brief = {
  f: {}, src: {},
  reset() {
    this.f = {
      project: "Neubau", bundesland: "BY", building_class: "detached_house",
      plot_width_m: 18, plot_depth_m: 24, dwelling_count: null, storey_count: 1,
      storey_height_m: 2.5, occupants: null, rooms: {}, roomAreas: {},
      accessibility_tier: "none", notes: "",
    };
    this.src = {};
    renderSpecs();
  },
  set(slot, value, by) { this.f[slot] = value; this.src[slot] = by; renderSpecs(); },
  addRooms(patch, by) {
    for (const [cat, n] of Object.entries(patch)) {
      if (n > 0) this.f.rooms[cat] = n; else { delete this.f.rooms[cat]; delete this.f.roomAreas[cat]; }
    }
    if (Object.keys(patch).length) this.src.rooms = by;
    renderSpecs();
  },
  get ready() { return Object.keys(this.f.rooms).length > 0; },
  seal() {
    const assumptions = [];
    const f = this.f;
    const rooms = { ...f.rooms };
    const work = isWorkspace();
    for (const [cat, basis] of [
      ["kitchen", "every dwelling needs a kitchen — added quietly"],
      ["bathroom", "every dwelling needs a bathroom — added quietly"],
    ]) {
      if (!rooms[cat]) { rooms[cat] = 1; assumptions.push({ slot: `rooms.${cat}`, value: 1, basis, confidence: "high", confirmed: false }); }
    }
    if (f.dwelling_count == null) {
      assumptions.push({
        slot: "dwelling_count", value: 1,
        basis: work ? "a workplace is one unit" : "described as a single home",
        confidence: "high", confirmed: false,
      });
    }
    const occupants = f.occupants || (work ? 8 : 4);
    if (f.occupants == null) {
      assumptions.push({ slot: "occupants", value: occupants, basis: work ? "typical small team" : "typical household", confidence: "low", confirmed: false });
    }
    if (!this.src.plot_width_m) {
      assumptions.push({ slot: "plot", value: `${f.plot_width_m} × ${f.plot_depth_m} m`, basis: "default plot — say yours anytime", confidence: "low", confirmed: false });
    }
    for (const [slot, value, basis] of [
      ["storey_height_m", 2.5, "standard ceiling: legal minimum 2.40 m plus build-up"],
      ["storey_count", 1, "v1 designs a single storey"],
    ]) {
      if (!this.src[slot]) assumptions.push({ slot, value, basis, confidence: "high", confirmed: false });
    }
    return {
      project: f.project, bundesland: "BY", building_class: f.building_class,
      plot_width_m: f.plot_width_m, plot_depth_m: f.plot_depth_m,
      dwelling_count: f.dwelling_count ?? 1, storey_count: 1,
      storey_height_m: f.storey_height_m, occupants,
      rooms: Object.entries(rooms).map(([category, count]) => ({
        category, count, min_area_m2: f.roomAreas[category] ?? null, label: null,
      })),
      accessibility_tier: f.accessibility_tier, assumptions,
      notes: f.notes.trim().slice(0, 2000), schema: "designbrief/v1",
    };
  },
};

/* ══════════════════════════════════════════════════════════════════════
   Understanding words — deterministic; shows what it got, admits what not.
   ══════════════════════════════════════════════════════════════════════ */

const NUM_WORDS = {
  a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
  seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12,
  ein: 1, eine: 1, einem: 1, zwei: 2, drei: 3, vier: 4, "fünf": 5, fuenf: 5, sechs: 6,
  sieben: 7, acht: 8, neun: 9, zehn: 10, "zwölf": 12, zwoelf: 12,
};
const CAT_WORDS = [
  [/bed\s?rooms?|schlafzimmer|kinderzimmer|kids?['’]?\s?rooms?|children'?s rooms?|guest\s?rooms?|g[äa]stezimmer/, "bedroom"],
  [/bath\s?rooms?|wash\s?rooms?|rest\s?rooms?|bäder|b[äa]dezimmer|\bbad\b|\bwc\b|toilets?|shower rooms?|duschbad/, "bathroom"],
  [/kitchens?|kitchenettes?|küchen?|kueche|teek[üu]che|break rooms?|canteen|cafeteria|pantry/, "kitchen"],
  [/living\s?rooms?|lounge|wohnzimmer|wohnbereich/, "living"],
  [/conference rooms?|meeting rooms?|boardrooms?|besprechungsr[äa]ume?|konferenzr[äa]ume?/, "meeting"],
  [/warehouse floor|storage hall|lagerhalle|workshops?|werkst[äa]tt(?:en)?|maker\s?space|labs?\b|labor/, "lab"],
  [/stud(?:y|ies)|studios?|offices?|open.?space|workspaces?|home\s?office|büros?|buero|arbeitszimmer/, "office"],
  [/receptions?|lobb(?:y|ies)|foyer|empfang/, "hall"],
  [/utilit(?:y|ies)|laundry|hwr|hauswirtschaftsraum|storage rooms?|abstellraum|server rooms?/, "utility"],
];
const WORK_CLASSES = [
  // order matters: the phrase that gets stripped should be the building
  // mention, so "an office for my startup" is caught by the office pattern
  // (stripping "an office") before the bare "startup" pattern can win.
  [/warehouse|lagerhalle|\blager\b/, "warehouse"],
  [/co.?working/, "coworking_space"],
  [/office building|offices? for|an office\b|my office\b|büro(?:geb[äa]ude|fl[äa]che)/, "office_building"],
  [/startup|small (company|business|firm)|our (team|company)\b/, "office_building"],
  [/practice|praxis|kanzlei|clinic|klinik/, "practice"],
  [/agency|agentur|design studio|studio for|atelier/, "studio_building"],
];

function wordNum(s) {
  const n = parseInt(s, 10);
  return Number.isNaN(n) ? (NUM_WORDS[s?.toLowerCase()] ?? null) : n;
}

function parseUtterance(text) {
  let t = " " + text.toLowerCase() + " ";
  const got = [];
  const rooms = {};
  const roomAreas = {};

  // The building itself is not a room: detect the class first and blank the
  // phrase, so "an office for my startup" doesn't also count an office room.
  let workClass = null;
  for (const [pat, cls] of WORK_CLASSES) {
    const m = t.match(pat);
    if (m) { workClass = cls; t = t.replace(m[0], " "); break; }
  }

  // "3 BHK" — bedrooms + hall(living) + kitchen, said the way people say it
  const bhk = t.match(/(\d)\s*bhk/);
  if (bhk) {
    rooms.bedroom = Math.min(+bhk[1], 6);
    rooms.living = 1; rooms.kitchen = 1; rooms.bathroom = Math.max(rooms.bathroom || 0, 1);
    got.push([`${bhk[1]} BHK`, "bedrooms + hall + kitchen"]);
  }

  const numPat = "(\\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an|ein|eine|zwei|drei|vier|fünf|fuenf|sechs)";
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
  for (const [cat, n] of Object.entries(rooms)) {
    if (!bhk || !["bedroom", "living", "kitchen"].includes(cat) || rooms[cat] > (cat === "bedroom" ? +bhk[1] : 1)) {
      if (!bhk) got.push([ROOM_LABELS[cat].toLowerCase(), `× ${n}`]);
    }
  }
  if (bhk) for (const cat of Object.keys(rooms)) {
    if (!["bedroom", "living", "kitchen", "bathroom"].includes(cat)) got.push([ROOM_LABELS[cat].toLowerCase(), `× ${rooms[cat]}`]);
  }

  const patch = {};

  const dw = t.match(new RegExp(`${numPat}\\s+(?:famil(?:y|ies|ien)|homes?|households?|apartments?|flats?|units?|wohnungen|wohneinheiten|parteien)`));
  if (dw && wordNum(dw[1]) > 1) patch.dwelling_count = wordNum(dw[1]);
  else if (/dreifamilien|three.?family/.test(t)) patch.dwelling_count = 3;
  else if (/zweifamilien|two.?family|duplex|doppelhaus/.test(t)) patch.dwelling_count = 2;
  else if (/einfamilien|single.?family|just (us|our family)|nur wir/.test(t)) patch.dwelling_count = 1;
  if (patch.dwelling_count) got.push(["homes", String(patch.dwelling_count)]);

  if (workClass) patch.building_class = workClass;
  else if (/apartment (building|block|complex)|mehrfamilienhaus|wohnblock/.test(t)) patch.building_class = "apartment_block";
  else if (/\b(an?|my|our|the)\s+(apartment|flat|wohnung)\b|\d\s*bhk/.test(t)) patch.building_class = "apartment";
  else if (/semi.?detached|doppelhaush[äa]lfte/.test(t)) patch.building_class = "semi_detached";
  else if (/detached|house|home\b|haus\b|cottage|weekend house|ferienhaus|bungalow|villa/.test(t)) patch.building_class = "detached_house";
  if (patch.building_class) got.push(["building", classLabel(patch.building_class).toLowerCase()]);

  // a warehouse IS its floor — make sure the floor itself is in the programme
  if (patch.building_class === "warehouse" && !rooms.lab) { rooms.lab = 1; }

  const plot = t.match(/(\d{1,3})\s*(?:x|×|by|mal)\s*(\d{1,3})\s*(?:m\b|met)/);
  if (plot) {
    patch.plot_width_m = +plot[1]; patch.plot_depth_m = +plot[2];
    got.push(["plot", `${plot[1]} × ${plot[2]} m`]);
  }

  // a bare floor area — for warehouses and big rooms: "about 300 m² of floor"
  const floor = t.match(/(\d{2,5})\s*(?:m2|m²|sqm|square met|quadratmet)/);
  if (floor && (workClass === "warehouse" || Chat.awaitingFloor)) {
    roomAreas.lab = Math.min(+floor[1], 2000);
    rooms.lab = rooms.lab || 1;
    got.push(["floor", `${floor[1]} m²`]);
  }

  const occNum = "(\\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|zwölf|zwoelf)";
  const occ = t.match(new RegExp(`(?:family|team|group) of ${occNum}|${occNum}\\s+(?:of us|people|persons?|personen|employees?|mitarbeiter|desks?|seats?|arbeitspl[äa]tze)|zu\\s+(dritt|viert|fünft|sechst)`));
  if (occ) {
    const zu = { dritt: 3, viert: 4, "fünft": 5, sechst: 6 };
    patch.occupants = occ[3] ? zu[occ[3]] : wordNum(occ[1] || occ[2]);
    if (patch.occupants) got.push(["people", `${patch.occupants}`]);
  }

  if (/wheelchair|rollstuhl/.test(t)) patch.accessibility_tier = "din18040_2_R";
  else if (/barrier.?free|barrierefrei|accessible|step.?free|altersgerecht/.test(t)) patch.accessibility_tier = "din18040_2";
  if (patch.accessibility_tier) got.push(["barrier-free", "yes"]);

  const st = t.match(new RegExp(`${numPat}\\s+(?:store(?:y|ys|ies)|floors?|geschoss(?:e|ig)?|stockwerke?|etagen)`));
  const storeysAsked = st ? wordNum(st[1]) : (/zweigeschossig|two.?stor(?:e?y|ies)/.test(t) ? 2 : null);

  const name = text.match(/(?:for the|für(?: die)?(?: Familie)?|for)\s+([A-ZÄÖÜ][a-zA-Zäöüß]+)(?:\s+family|\s+familie)?/);
  if (name && /family|familie|Familie/.test(text)) {
    patch.project = `Haus ${name[1]}`;
    got.push(["project", patch.project]);
  }

  const multiHint = /apartment (building|block|complex)|mehrfamilien|several (families|units)|wohnblock/.test(t);
  return { patch, rooms, roomAreas, got, storeysAsked, multiHint };
}

/* ══════════════════════════════════════════════════════════════════════
   The conversation
   ══════════════════════════════════════════════════════════════════════ */

const Chat = {
  transcript: [], id: null, round: 0, session: "", waiting: false,
  askedRooms: false, askedPeople: false, askedDwelling: false, askedFloor: false,
  awaitingFloor: false, proposed: false, multiHint: false,
};
const Draft = { round: 0, id: null, bundle: null, sealed: null, selected: null, busy: false };

function addMsg(who, text, { meta, wait } = {}) {
  const li = el("li", `msg ${who}${wait ? " wait" : ""}`);
  li.append(el("div", "bubble", text));
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
    meta.append("instant");
  }
  addMsg(devin ? "devin" : "agent", text, { meta });
  Chat.transcript.push({ role: "interviewer", text });
  setChips(chips);
}

function setChips(chips) {
  const row = $("chat-chips");
  row.innerHTML = "";
  chips.forEach(({ label, send, action }) => {
    const b = el("button", "qchip", label);
    b.type = "button";
    b.onclick = () => {
      if (Chat.waiting || Draft.busy) return;
      if (action) action(); else submitUtterance(send ?? label);
    };
    row.append(b);
  });
}

function commandBubble(intro, cmd) {
  const li = addMsg("agent", intro);
  const box = el("div", "cmd");
  const pre = el("pre", "mono", cmd);
  const copy = el("button", "pill sm", "Copy");
  copy.type = "button";
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(cmd); copy.textContent = "Copied ✓"; }
    catch { copy.textContent = "Select + copy"; }
    setTimeout(() => { copy.textContent = "Copy"; }, 2500);
  };
  box.append(pre, copy);
  li.append(box);
  li.append(el("div", "meta", "tokenless trigger · this page holds no secret"));
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return li;
}

function applyParsed(parsed, by) {
  Brief.addRooms(parsed.rooms, by);
  for (const [cat, a] of Object.entries(parsed.roomAreas)) Brief.f.roomAreas[cat] = a;
  for (const [k, v] of Object.entries(parsed.patch)) Brief.set(k, v, by);
  if (parsed.multiHint) Chat.multiHint = true;
}

/* The instant agent — asks only what it can't infer, fitted to the type. */
function instantNext(parsed) {
  const f = Brief.f;
  const work = isWorkspace();
  const wh = f.building_class === "warehouse";

  if (parsed?.storeysAsked > 1) {
    agentSay(`Noted — ${parsed.storeysAsked} storeys. I design a single storey for now, so I'll plan the ground floor beautifully and keep the wish on file.`);
    Brief.set("notes", (f.notes + ` Client wants ${parsed.storeysAsked} storeys (v1 designs one).`).trim(), "you");
  }

  if (Chat.multiHint && f.dwelling_count == null && !Chat.askedDwelling) {
    Chat.askedDwelling = true;
    agentSay("How many homes should the building hold?",
      { chips: [{ label: "Two", send: "Two homes" }, { label: "Three", send: "Three homes" }, { label: "Four", send: "Four homes" }] });
    return;
  }

  if (wh && !f.roomAreas.lab && !Chat.askedFloor) {
    Chat.askedFloor = true;
    Chat.awaitingFloor = true;
    agentSay("Roughly how much hall floor do you need? I'll add a small office corner and a washroom alongside.",
      { chips: [{ label: "100 m²", send: "About 100 m² of floor" }, { label: "200 m²", send: "About 200 m² of floor" }, { label: "400 m²", send: "About 400 m² of floor" }] });
    return;
  }

  if (work && !wh && f.occupants == null && !Chat.askedPeople) {
    Chat.askedPeople = true;
    agentSay("How many people will work there day to day? That's what sizes the space.",
      { chips: [{ label: "5 of us", send: "5 people" }, { label: "10", send: "10 people" }, { label: "About 20", send: "20 people" }] });
    return;
  }

  if (!Brief.ready && !Chat.askedRooms) {
    Chat.askedRooms = true;
    agentSay(
      work
        ? "Tell me the spaces you need — in your own words. \"An open studio, a meeting room, a small kitchen\" is plenty."
        : "Which rooms should it have? Say it however you'd say it — \"three bedrooms, a study, an open kitchen\" works.",
      { chips: [] },
    );
    return;
  }
  if (!Brief.ready) return;

  if (!Chat.proposed) {
    Chat.proposed = true;
    Chat.awaitingFloor = false;
    const what = classLabel(f.building_class).toLowerCase();
    agentSay(
      `Lovely — I have what I need for ${what}. I'll draft four structurally different blueprints, dimensioned and checked; it takes about two minutes. Anything else first?`,
      { chips: [
        { label: "Draft the blueprints", action: () => draftRound() },
        { label: "One more thing…", action: () => { setChips([]); $("chat-input").focus(); } },
      ] },
    );
    return;
  }

  // options already exist (or were proposed): any new understanding redrafts
  if (Draft.bundle || Draft.busy) return;
  agentSay("Got it. Ready when you are —",
    { chips: [{ label: "Draft the blueprints", action: () => draftRound() }] });
}

async function submitUtterance(text) {
  text = text.trim();
  if (!text || Chat.waiting || Draft.busy) return;
  addMsg("you", text);
  Chat.transcript.push({ role: "client", text });
  $("chat-input").value = "";
  autoGrow();

  const parsed = parseUtterance(text);
  applyParsed(parsed, "you");
  Brief.set("notes", (Brief.f.notes + " " + text).trim().slice(0, 2000), Brief.src.notes || "you");

  if ($("chat-engine").value === "devin") return devinRound();

  if (parsed.got.length) {
    const li = $("chat-log").lastElementChild;
    const row = el("div", "got");
    parsed.got.forEach(([k, v]) => {
      const c = el("span", "chip");
      c.append(el("span", null, k + " "), el("b", null, v));
      row.append(c);
    });
    li.append(row);
    li.scrollIntoView({ block: "end" });
  } else if (text.split(/\s+/).length > 6) {
    agentSay(
      "I read that, but I couldn't pull anything concrete from it — I'm the instant engine and my vocabulary is rooms and sizes. Rephrase, or hand the conversation to Devin, which genuinely reads.",
      { chips: [
        { label: "Hand it to Devin", action: () => { $("chat-engine").value = "devin"; devinRound(); } },
        { label: "I'll rephrase", action: () => { setChips([]); $("chat-input").focus(); } },
      ] },
    );
    return;
  }

  // refining after options exist → redraft with the change
  if (Draft.bundle && parsed.got.length) {
    agentSay(`Changing that — I'll redraft the four takes. Two minutes.`);
    return draftRound();
  }
  instantNext(parsed);
}

/* --- Devin: one relay round = one live turn ----------------------------- */

async function devinRound() {
  Chat.id = Chat.id || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())).replace(/[^a-zA-Z0-9-]/g, "").slice(0, 40);
  Chat.round += 1;
  Chat.waiting = true;
  $("chat-send").dataset.state = "busy";
  $("chat-engine").disabled = true;

  const payload = {
    id: Chat.id, round: Chat.round, session_id: Chat.session,
    messages: Chat.transcript.slice(-30).map((m) => ({ role: m.role, text: m.text.slice(0, 2000) })),
    known: Brief.f,
  };

  const t0 = Date.now();
  if (GH.canDispatch) {
    try {
      await GH.workflowDispatch("interview.yml", { payload: JSON.stringify(payload) });
    } catch (e) {
      endWait();
      agentSay(`Couldn't start the round: ${e.message}.`);
      return;
    }
  } else {
    commandBubble(
      "This page has no trigger key, so it can't start the session itself. Run this in any terminal with gh — I'm already watching for Devin's reply:",
      triggerCommand("interview.yml", "payload", payload),
    );
  }

  const wait = addMsg("agent",
    GH.canDispatch ? "Devin is reading the conversation… first reply usually takes 2–4 minutes."
                   : "Waiting for the trigger… once it runs, Devin's reply lands here.",
    { wait: true });
  const meta = el("div", "meta");
  wait.append(meta);
  const tick = setInterval(() => {
    meta.textContent = `waiting ${Math.round((Date.now() - t0) / 1000)}s · relayed through Actions`;
  }, 1000);
  setChips([{ label: "Stop waiting", action: () => { cancel.hit = true; } }]);
  const cancel = { hit: false };

  let runRef = null;
  GH.findRun("interview", t0).then((r) => {
    if (r) {
      runRef = r;
      meta.append(" · ");
      const a = el("a", null, "run ↗"); a.href = r.html_url; a.target = "_blank"; a.rel = "noopener";
      meta.append(a);
    }
  }).catch(() => {});

  // Poll cheaply while the run works; the moment it completes, read fresh.
  const path = `interviews/${Chat.id}/reply-${Chat.round}.json`;
  let reply = null;
  let concluded = false;
  const deadline = t0 + 15 * 60 * 1000;
  while (Date.now() < deadline && !cancel.hit) {
    await sleep(concluded ? 4000 : GH.pollMs);
    // same discipline as drafting: if the run's status is readable, don't
    // reach for the reply until the run is actually done
    if (runRef && (GH.authToken || GH.viaRelay) && !concluded) {
      concluded = !!(await GH.runStatus(runRef.id).catch(() => null));
      if (!concluded) continue;
    }
    reply = concluded
      ? await GH.relayFresh(path).catch(() => null)
      : await GH.raw(path, "studio-interviews").catch(() => null);
    if (reply && reply.round === Chat.round) break;
    reply = null;
  }
  clearInterval(tick);
  wait.remove();
  endWait();

  if (!reply) {
    agentSay(cancel.hit
      ? "Stopped waiting. Ask again to pick the round up, or continue with the instant engine."
      : "No reply within 15 minutes — if the trigger never ran, run it and ask again.",
      { chips: [{ label: "Ask Devin again", action: () => { Chat.round -= 1; devinRound(); } }] });
    return;
  }

  Chat.session = reply.session_id || Chat.session;
  if (reply.brief && Object.keys(reply.brief).length) {
    const b = reply.brief;
    if (b.rooms?.length) Brief.addRooms(Object.fromEntries(b.rooms.map((r) => [r.category, r.count || 1])), "devin");
    for (const k of ["project", "building_class", "dwelling_count", "plot_width_m", "plot_depth_m", "occupants", "storey_height_m", "accessibility_tier", "notes"]) {
      if (b[k] != null && b[k] !== "" && JSON.stringify(b[k]) !== JSON.stringify(Brief.f[k])) Brief.set(k, b[k], "devin");
    }
  }
  const chips = (reply.questions || []).flatMap((q) => (q.options || []).slice(0, 4).map((o) => ({ label: o, send: o })));
  agentSay(reply.message || "…", { devin: true, sessionUrl: reply.session_url, chips });
  if (reply.done) {
    agentSay("I have everything — shall I draft the blueprints? Four takes, about two minutes.",
      { devin: false, chips: [{ label: "Draft the blueprints", action: () => draftRound() }] });
    Chat.proposed = true;
  }
}

function endWait() {
  Chat.waiting = false;
  delete $("chat-send").dataset.state;
  $("chat-engine").disabled = false;
  setChips([]);
}

/* ══════════════════════════════════════════════════════════════════════
   Drafting — four takes per round, streamed back as one bundle
   ══════════════════════════════════════════════════════════════════════ */

function draftSteps(items) {
  const list = $("draft-steps");
  list.innerHTML = "";
  for (const it of items) {
    const li = el("li", `dstep ${it.state}`);
    li.append(el("span", "dot"), el("span", "lb", it.label));
    if (it.href) { const a = el("a", "rt", it.rt || "log ↗"); a.href = it.href; a.target = "_blank"; a.rel = "noopener"; li.append(a); }
    else li.append(el("span", "rt", it.rt || ""));
    list.append(li);
  }
}

async function draftRound() {
  if (Draft.busy) return;
  Draft.busy = true;
  Draft.id = Draft.id || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())).replace(/[^a-zA-Z0-9-]/g, "").slice(0, 40);
  Draft.round += 1;
  Draft.sealed = Brief.seal();
  setChips([]);
  stage("drafting");
  $("draft-title").textContent = Draft.round === 1 ? "Drafting four takes" : "Redrafting with your changes";
  $("draft-note").textContent = "";
  $("draft-cmd").innerHTML = "";
  draftSteps([{ label: "Sending the brief", rt: GH.canDispatch ? "dispatch" : "your trigger", state: "run" }]);

  const payload = { id: Draft.id, round: Draft.round, engine: "local", strategies: "", brief: Draft.sealed };
  const t0 = Date.now();

  if (GH.canDispatch) {
    try {
      await GH.workflowDispatch("draft.yml", { payload: JSON.stringify(payload) });
    } catch (e) {
      draftSteps([{ label: "Sending the brief", rt: e.message.slice(0, 50), state: "fail" }]);
      Draft.busy = false;
      agentSay(`The dispatch failed: ${e.message}`);
      return;
    }
  } else {
    // last-resort fallback (no demo key shipped, no personal token): the
    // exact trigger, folded away so it never dominates the card
    const cmd = triggerCommand("draft.yml", "payload", payload);
    const det = el("details", "cmd-fold");
    det.append(el("summary", null, "No trigger key on this page — show the one command that starts the round"));
    const box = el("div", "cmd");
    const pre = el("pre", "mono", cmd);
    const copy = el("button", "pill sm", "Copy");
    copy.type = "button";
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(cmd); copy.textContent = "Copied ✓"; }
      catch { copy.textContent = "Select + copy"; }
      setTimeout(() => { copy.textContent = "Copy"; }, 2500);
    };
    box.append(pre, copy);
    det.append(box);
    $("draft-cmd").append(det);
    $("draft-note").textContent = "I'm watching — the round starts the moment the trigger runs.";
  }

  // follow the run's real steps
  // How fast we may look depends on whose budget we are spending: our own
  // token or the relay's is fine; anonymous GitHub is 60 calls an hour.
  const watched = !!GH.authToken || GH.viaRelay;
  let run = null;
  const tries = watched ? 25 : 20;
  for (let i = 0; i < tries && !run; i++) { await sleep(watched ? 4000 : 15000); run = await GH.findRun("draft", t0).catch(() => null); }
  if (run) {
    const poll = async () => {
      const steps = await GH.runSteps(run.id);
      const items = steps.filter((s) => !/^Set up|^Complete|Post /.test(s.name)).map((s) => ({
        label: s.name, rt: s.conclusion || s.status,
        state: s.conclusion === "success" ? "done" : s.conclusion ? "fail" : s.status === "in_progress" ? "run" : "pend",
      }));
      if (items.length) {
        items.unshift({ label: "Run", rt: "open ↗", href: run.html_url, state: "done" });
        draftSteps(items);
      }
    };
    poll();
    var jobTick = setInterval(poll, watched ? 5000 : 20000);
  } else {
    $("draft-note").textContent = GH.canDispatch
      ? "No run appeared — check the Actions tab."
      : ($("draft-note").textContent || "") + " (still waiting for the run to start)";
  }

  // and wait for the bundle itself — the artifact is the truth. Cheap polls
  // while the run works; a fresh read the moment it completes.
  const path = `drafts/${Draft.id}/round-${Draft.round}.json`;
  let bundle = null;
  let concluded = false;
  // When the run's status is readable, wait for it to finish before reaching
  // for the bundle: fewer requests, a faster first hit, and no console full
  // of 404s from polling a file that does not exist yet.
  const canWatch = !!run && watched;
  const deadline = t0 + 20 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(concluded ? 3500 : GH.pollMs);
    if (canWatch && !concluded) {
      concluded = !!(await GH.runStatus(run.id).catch(() => null));
      if (!concluded) continue;
    }
    bundle = concluded
      ? await GH.relayFresh(path).catch(() => null)
      : await GH.raw(path, "studio-interviews").catch(() => null);
    if (bundle && bundle.schema === "draftbundle/v1") break;
    bundle = null;
  }
  if (typeof jobTick !== "undefined") clearInterval(jobTick);
  Draft.busy = false;

  if (!bundle) {
    draftSteps([{ label: "Waiting for the round", rt: "nothing arrived in 20 min", state: "fail" }]);
    agentSay("The drafting round never came back — the workflow log will say why. Say the word and I'll try again.",
      { chips: [{ label: "Try again", action: () => { Draft.round -= 1; draftRound(); } }] });
    return;
  }
  if (bundle.error) {
    agentSay(`The drafting run failed: ${bundle.error}`);
    stage("hero");
    return;
  }

  Draft.bundle = bundle;
  renderOptions(bundle);
  stage("options");

  const ok = bundle.candidates.filter((c) => c.ok).length;
  const bad = bundle.candidates.filter((c) => !c.ok && !c.error);
  let line = ok === bundle.candidates.length
    ? `All ${ok} pass the code checks — pick whichever feels right, or keep talking and I'll redraft.`
    : `${ok} of ${bundle.candidates.length} pass the code checks cleanly.`;
  if (bad.length) {
    const b = bad[0];
    const f = (b.findings || []).find((x) => x.status === "failed");
    if (f) line += ` The ${b.label.toLowerCase()} take has an issue — ${f.message} — details on its card.`;
  }
  agentSay(line);
}

/* ══════════════════════════════════════════════════════════════════════
   Options — four glass cards, sheets front and centre
   ══════════════════════════════════════════════════════════════════════ */

function codePill(c, { expanded = false } = {}) {
  const pill = el("button", `code-pill ${c.ok ? "ok" : "bad"}`);
  pill.type = "button";
  const n = c.not_evaluated ? ` · ${c.not_evaluated} unchecked` : "";
  pill.textContent = c.ok ? `✓ ${c.checked} checks${n}` : `✕ ${c.failed} issue${c.failed === 1 ? "" : "s"} · ${c.checked} checks${n}`;
  pill.title = "The building-code checks — tap for details";
  pill.onclick = (e) => { e.stopPropagation(); openCodeDrawer(c); };
  return pill;
}

function renderOptions(bundle) {
  $("options-h").textContent = `${bundle.candidates.length} takes on ${bundle.project === "Neubau" ? "your brief" : bundle.project}`;
  const grid = $("options-grid");
  grid.innerHTML = "";
  bundle.candidates.forEach((c, i) => {
    const card = el("article", "opt glass");
    card.style.setProperty("--i", i);
    if (c.error) {
      card.append(el("h3", "opt-name", c.label));
      card.append(el("p", "opt-desc", "This take couldn't be built: " + c.error.slice(0, 120)));
      grid.append(card);
      return;
    }
    const sheet = el("div", "opt-sheet");
    if (c.sheet_svg) sheet.innerHTML = c.sheet_svg; else sheet.append(el("p", "mini", "no sheet"));
    card.append(sheet);
    const meta = el("div", "opt-meta");
    const head = el("div", "opt-head");
    head.append(el("h3", "opt-name", c.label));
    head.append(codePill(c));
    meta.append(head);
    const m = c.metrics || {};
    meta.append(el("p", "opt-desc", c.rationale || ""));
    const facts = el("div", "opt-facts mono");
    if (m.envelope_m2) facts.append(el("span", null, `${m.envelope_m2} m²`));
    if (m.rooms) facts.append(el("span", null, `${m.rooms} rooms`));
    if (m.usable_ratio) facts.append(el("span", null, `${Math.round(m.usable_ratio * 100)}% usable`));
    meta.append(facts);
    const go = el("button", "pill primary", "Build this one in 3D");
    go.type = "button";
    go.onclick = () => selectCandidate(c);
    meta.append(go);
    card.append(meta);
    card.onclick = (e) => { if (e.target === card || e.target === sheet || sheet.contains(e.target)) openSheetModal(c); };
    grid.append(card);
  });
}

/* ══════════════════════════════════════════════════════════════════════
   Selection — the 3D moment, and the quiet archive
   ══════════════════════════════════════════════════════════════════════ */

/* The takes strip — the alternatives stay one click away above the model.
   Fundamental UX: a choice you can still see is a choice you can revisit. */
function renderTakesStrip(cands, selectedName, onPick) {
  const strip = $("takes-strip");
  strip.innerHTML = "";
  cands.forEach((c) => {
    if (c.error) return;
    const b = el("button", "take" + (c.name === selectedName ? " on" : ""));
    b.type = "button";
    b.append(el("span", `tdot ${c.ok ? "ok" : "bad"}`, c.ok ? "✓" : "✕"));
    b.append(el("span", "tname", c.label || c.name));
    const m2 = c.metrics?.envelope_m2;
    if (m2) b.append(el("span", "tm mono", `${m2} m²`));
    b.onclick = () => onPick(c);
    strip.append(b);
  });
  if (Draft.bundle && cands === Draft.bundle.candidates) {
    const all = el("button", "take all", "⌗ compare all");
    all.type = "button";
    all.onclick = () => stage("options");
    strip.append(all);
  }
}

function selectCandidate(c, { fromPortfolio = false, stripCands = null, onPick = null } = {}) {
  Draft.selected = c;
  stage("detail");

  const cands = stripCands || Draft.bundle?.candidates || [c];
  renderTakesStrip(cands, c.name, onPick || ((x) => selectCandidate(x)));

  $("detail-name").textContent = c.label || c.name;
  const m = c.metrics || {};
  $("detail-metrics").textContent =
    [m.envelope_m2 && `${m.envelope_m2} m²`, m.rooms && `${m.rooms} rooms`,
     m.openings && `${m.openings} openings`].filter(Boolean).join(" · ");
  const pillHost = $("detail-pill");
  pillHost.innerHTML = "";
  pillHost.append(codePill(c));

  // the chosen 2D stays in view right below the model
  const sheet = $("sheet-inline");
  sheet.innerHTML = "";
  const putSvg = (svg) => { sheet.innerHTML = svg || '<p class="mini">no sheet for this take</p>'; };
  if (c.sheet_svg) putSvg(c.sheet_svg);
  else if (c.sheet_url) fetch(c.sheet_url).then((r) => (r.ok ? r.text() : "")).then(putSvg).catch(() => putSvg(""));
  else putSvg("");
  sheet.onclick = () => openSheetModal(c);

  const pdf = $("pdf-link");
  if (c.pdf_url) { pdf.href = c.pdf_url; pdf.classList.remove("hide"); } else pdf.classList.add("hide");

  const wait = $("v3-wait");
  wait.textContent = "building the model…";
  wait.classList.remove("hide");
  const meshReady = (json) => {
    try { loadMesh(json); } catch (e) {
      wait.textContent = "3D needs WebGL, which this browser did not provide";
      console.error(e);
    }
  };
  if (c.mesh) meshReady(c.mesh);
  else if (c.mesh_url) {
    fetch(c.mesh_url).then((r) => (r.ok ? r.json() : Promise.reject())).then(meshReady)
      .catch(() => { wait.textContent = "no 3D model was published for this design"; });
  } else wait.textContent = "no 3D model in this draft";

  if (!fromPortfolio) {
    agentSay(`${c.label} it is — the model's up, the plan sits below it. Orbit, hover a room for its size, switch takes above. Want changes, just say them; want it kept, I'll archive it.`,
      { chips: [{ label: "Archive to portfolio", action: () => archiveSelected() }] });
  }
}

function archiveSelected() {
  const c = Draft.selected;
  if (!c || !Draft.sealed) return;
  if (GH.canDispatch) {
    GH.workflowDispatch("autopilot.yml", { engine: "local", brief_json: JSON.stringify(Draft.sealed) })
      .then(() => agentSay("Archiving. The run re-verifies everything, merges itself on green, and the design lands in the portfolio in about three minutes."))
      .catch((e) => agentSay("The archive dispatch failed: " + e.message.slice(0, 90)));
  } else {
    commandBubble(
      "No trigger key on this page — this one command archives it (re-verifies, merges, publishes):",
      `gh workflow run autopilot.yml --repo ${GH.repo} --ref main -f engine=local -f brief_json="$(echo ${b64(JSON.stringify(Draft.sealed))} | base64 -d)"`,
    );
  }
}

/* ══════════════════════════════════════════════════════════════════════
   The portfolio — archived designs from web/data/
   ══════════════════════════════════════════════════════════════════════ */

async function loadIndex() {
  try {
    return await fetch("data/index.json", { cache: "no-store" }).then((r) => r.json());
  } catch { return { projects: [] }; }
}

async function openPortfolioProject(key, candName) {
  const run = await fetch(`data/${key}/run.json`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
  if (!run) { toast("Couldn't load that project."); return; }
  closeDrawers();
  const name = candName || run.winner || run.candidates[0]?.name;
  const meta = run.candidates.find((x) => x.name === name) || {};
  const verdict = await fetch(`data/${key}/${name}/verdict.json`).then((r) => r.json()).catch(() => null);
  const c = {
    name, label: (meta.label || name) + " — " + run.project,
    ok: !!verdict?.ok, checked: verdict?.checked ?? 0, failed: verdict?.failed ?? 0,
    not_evaluated: verdict?.not_evaluated ?? 0,
    findings: (verdict?.findings || []).filter((f) => f.status !== "passed"),
    metrics: verdict?.metrics || {},
    mesh_url: `data/${key}/${name}/mesh.json`,
    sheet_url: `data/${key}/${name}/sheet.svg`,
    pdf_url: `data/${key}/${name}/sheet.pdf`,
    devin_session: meta.devin_session || "",
  };
  // the strip lists the archived run's other takes, switchable in place
  const stripCands = run.candidates.map((x) => ({
    name: x.name, label: x.label || x.name, ok: !!x.ok, error: x.error || "",
    metrics: x.metrics || {},
  }));
  selectCandidate(c, {
    fromPortfolio: true,
    stripCands,
    onPick: (x) => openPortfolioProject(key, x.name),
  });
  $("detail-name").textContent = c.label;
}

async function renderPortfolio() {
  const list = $("portfolio-list");
  list.innerHTML = "";
  const index = await loadIndex();
  if (!index.projects.length) {
    list.append(el("p", "mini", "Nothing archived yet — design something and archive it."));
    return;
  }
  index.projects.forEach((p) => {
    const b = el("button", "port-item");
    b.type = "button";
    const head = el("div", "port-head");
    head.append(el("b", null, p.project));
    head.append(el("span", `dot-pill ${p.ok ? "ok" : "bad"}`, p.ok ? "✓" : "✕"));
    b.append(head);
    b.append(el("span", "mini mono", `${p.candidates} takes · ${p.checked} checks · ${p.failed} failed${p.engine === "devin" ? " · planned by Devin" : ""}`));
    b.onclick = () => openPortfolioProject(p.key);
    list.append(b);
  });
}

/* ══════════════════════════════════════════════════════════════════════
   The code drawer — the checks, honest and cited, one tap away
   ══════════════════════════════════════════════════════════════════════ */

const ADVICE = {
  "CORRIDOR-WIDTH": "Accessible circulation needs 1.20 m clear — give the hallway more room (“make the hallway at least 20 m²”) or a wider plot.",
  "ROOM-DAYLIGHT": "This room can't get enough window for its size — more exterior wall for it, or a slightly smaller room.",
  "DOOR-MIN-WIDTH": "Accessible doors need 0.80 m clear inside, 0.90 m at the entrance.",
  "DOOR-MIN-HEIGHT": "Accessible doors need 2.05 m clear height.",
  "ROOM-MIN-AREA": "A comfort guideline, not law — it warns, it never blocks.",
  "ROOM-MIN-WIDTH": "A comfort guideline for proportions — a touch more area fixes it.",
  "DWELLING-FACILITIES": "Every home needs a kitchen and a bathroom — add the missing one.",
  "MOVEMENT-AREA": "Judged by the room's narrowest side — more area or a squarer room clears it.",
  "ROOM-HAS-DOOR": "A room came out unreachable — usually more area or another take fixes it.",
  "ROOM-CLEAR-HEIGHT": "Habitable rooms need 2.40 m clear — raise the ceiling.",
};

function openCodeDrawer(c) {
  const box = $("code-body");
  box.innerHTML = "";
  box.append(el("p", "drawer-sub",
    `${c.checked} checks ran against the Bavarian residential rules. ` +
    (c.not_evaluated ? `${c.not_evaluated} can't be judged from a model alone and are listed below — they are never counted as passes. ` : "") +
    (c.ok ? "Nothing failed." : `${c.failed} failed.`)));
  const failures = (c.findings || []).filter((f) => f.status === "failed");
  const blind = (c.findings || []).filter((f) => f.status === "not_evaluated");
  if (failures.length) {
    box.append(el("h3", "drawer-h", "What needs attention"));
    failures.forEach((f) => {
      const d = el("div", "check bad");
      d.append(el("b", null, f.message));
      if (ADVICE[f.rule_id]) d.append(el("p", null, ADVICE[f.rule_id]));
      const cite = el("p", "cite mono");
      if (f.url) { const a = el("a", null, f.citation); a.href = f.url; a.target = "_blank"; a.rel = "noopener"; cite.append(a); }
      else cite.append(f.citation || f.rule_id);
      if (f.blocking) cite.append("  · blocking");
      d.append(cite);
      box.append(d);
    });
  }
  if (blind.length) {
    box.append(el("h3", "drawer-h", "What a model can't see"));
    blind.forEach((f) => {
      const d = el("div", "check blind");
      d.append(el("b", null, f.rule_id));
      d.append(el("p", null, f.message));
      box.append(d);
    });
  }
  if (!failures.length && !blind.length) box.append(el("p", "mini", "Every check that could run, passed."));
  openDrawer("code-drawer");
}

/* ══════════════════════════════════════════════════════════════════════
   Specs drawer — what I understood, and what I assumed
   ══════════════════════════════════════════════════════════════════════ */

function renderSpecs() {
  const box = $("specs-body");
  if (!box) return;
  box.innerHTML = "";
  const f = Brief.f;
  const src = (k) => Brief.src[k] === "devin" ? " · Devin" : Brief.src[k] === "you" ? " · you" : "";
  const row = (k, v, by) => {
    if (!v) return;
    const d = el("div", "spec-row");
    d.append(el("span", "spec-k", k));
    const val = el("span", "spec-v mono", v);
    if (by) val.append(el("em", "spec-src", by));
    d.append(val);
    box.append(d);
  };
  row("building", classLabel(f.building_class), src("building_class"));
  row("homes", f.dwelling_count != null ? String(f.dwelling_count) : "", src("dwelling_count"));
  row("people", f.occupants != null ? String(f.occupants) : "", src("occupants"));
  const roomsTxt = Object.entries(f.rooms).map(([c, n]) => `${n}× ${ROOM_LABELS[c] || c}${f.roomAreas[c] ? ` (≥${f.roomAreas[c]} m²)` : ""}`).join("  ·  ");
  row("rooms", roomsTxt, src("rooms"));
  row("plot", `${f.plot_width_m} × ${f.plot_depth_m} m`, src("plot_width_m"));
  row("ceiling", `${f.storey_height_m.toFixed(2)} m`, src("storey_height_m"));
  row("access", f.accessibility_tier === "none" ? "" : "barrier-free", src("accessibility_tier"));

  const at = el("div", "assume");
  at.append(el("h3", "drawer-h", "Quiet assumptions"));
  at.append(el("p", "mini", "Everything I inferred rather than was told. Correct any of it in the chat."));
  const chips = el("div", "spec-chips");
  const sealed = Brief.ready ? Brief.seal() : { assumptions: [] };
  sealed.assumptions.forEach((a) => {
    const c = el("span", "chip");
    c.append(el("b", null, `${a.slot.replace("rooms.", "+")} ${typeof a.value === "string" ? a.value : a.value}`), el("span", "basis", " · " + a.basis));
    chips.append(c);
  });
  if (!sealed.assumptions.length) chips.append(el("span", "mini", "none yet"));
  at.append(chips);
  box.append(at);
  $("specs-pill").classList.toggle("hide", !Object.keys(f.rooms).length && !Brief.src.building_class);
}

/* ══════════════════════════════════════════════════════════════════════
   3D — the model floats on the glass
   ══════════════════════════════════════════════════════════════════════ */

const COLOR = { wall: 0x9aa5ae, space: 0xdfe6ec, door: 0xd07a2a, window: 0x3b5bdb, edge: 0x2a3138 };
const SPACE_TINT = {
  living: 0xe9dfc8, kitchen: 0xdde5e9, bedroom: 0xd9e2ef, bathroom: 0xcfe0ea,
  office: 0xe4deef, meeting: 0xe7e0d3, lab: 0xe2e6df, hall: 0xe7e9eb,
  utility: 0xe3e6e0, other: 0xe6e4df,
};
const kindOf = (cls) => cls === "IfcSpace" ? "space" : cls === "IfcDoor" ? "door" : cls === "IfcWindow" ? "window" : "wall";

let V = null;

function viewer() {
  if (V) return V;
  const host = $("v3-host");
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.className = "v3-canvas";
  host.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 2000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.maxPolarAngle = Math.PI * 0.495;
  controls.autoRotate = !REDUCED;
  controls.autoRotateSpeed = 0.5;
  host.addEventListener("pointerdown", () => { controls.autoRotate = false; }, { once: true });

  scene.add(new THREE.HemisphereLight(0xffffff, 0xc7ced5, 1.2), new THREE.AmbientLight(0xffffff, 0.45));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(14, 22, 10);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  scene.add(sun);

  V = { renderer, scene, camera, controls, host, sun, root: null, ground: null,
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

function disposeTree(obj) {
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  });
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
    const flat = g.toNonIndexed();
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
    mesh.userData = { tag: e.tag, name: e.name, kind, area: e.area };
    if (kind === "space") v.spaces.push(mesh);
    else {
      mesh.castShadow = true;
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(flat, 28),
        new THREE.LineBasicMaterial({ color: COLOR.edge, transparent: true, opacity: 0.3 }),
      );
      mesh.add(edges);
    }
    root.add(mesh);
  }

  root.rotation.x = -Math.PI / 2;   // IFC is Z-up; three.js is Y-up
  v.scene.add(root);
  v.root = root;

  const catcher = new THREE.Mesh(
    new THREE.CircleGeometry(span * 1.9, 64),
    new THREE.ShadowMaterial({ opacity: 0.14 }),
  );
  catcher.rotation.x = -Math.PI / 2;
  catcher.position.y = -(z1 - z0) / 2 - 0.02;
  catcher.receiveShadow = true;
  v.scene.add(catcher);
  v.ground = catcher;

  v.sun.shadow.camera.left = v.sun.shadow.camera.bottom = -span * 1.4;
  v.sun.shadow.camera.right = v.sun.shadow.camera.top = span * 1.4;
  v.sun.shadow.camera.updateProjectionMatrix();

  v.camera.position.set(span * 0.95, span * 0.7, span * 1.05);
  v.controls.target.set(0, 0, 0);
  v.controls.update();
  $("v3-wait").classList.add("hide");
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
   Sheet lightbox — zoom and pan on the drawing
   ══════════════════════════════════════════════════════════════════════ */

const Sheet = { scale: 1, tx: 0, ty: 0 };
function applySheet() {
  $("sheet-zoom").style.transform = `translate(${Sheet.tx}px, ${Sheet.ty}px) scale(${Sheet.scale})`;
}
function sheetReset() { Sheet.scale = 1; Sheet.tx = 0; Sheet.ty = 0; applySheet(); }
function sheetZoom(f2, cx, cy) {
  const next = Math.min(6, Math.max(0.4, Sheet.scale * f2));
  const k = next / Sheet.scale;
  if (cx != null) { Sheet.tx = cx - k * (cx - Sheet.tx); Sheet.ty = cy - k * (cy - Sheet.ty); }
  Sheet.scale = next;
  applySheet();
}

function openSheetModal(c) {
  const host = $("sheet-big");
  host.innerHTML = "";
  const put = (svg) => { host.innerHTML = `<div class="sheet-zoom" id="sheet-zoom">${svg}</div>`; sheetReset(); };
  if (c.sheet_svg) put(c.sheet_svg);
  else if (c.sheet_url) fetch(c.sheet_url).then((r) => r.text()).then(put);
  $("sheet-title").textContent = c.label || c.name;
  $("sheet-modal").classList.remove("hide");
}

function initSheetControls() {
  const host = $("sheet-big");
  host.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = host.getBoundingClientRect();
    sheetZoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  let pan = null;
  host.addEventListener("pointerdown", (e) => { pan = { x: e.clientX, y: e.clientY, tx: Sheet.tx, ty: Sheet.ty }; host.setPointerCapture(e.pointerId); });
  host.addEventListener("pointermove", (e) => {
    if (!pan) return;
    Sheet.tx = pan.tx + (e.clientX - pan.x); Sheet.ty = pan.ty + (e.clientY - pan.y);
    applySheet();
  });
  const up = () => { pan = null; };
  host.addEventListener("pointerup", up);
  host.addEventListener("pointercancel", up);
  host.addEventListener("dblclick", sheetReset);
  $("sheet-close").onclick = () => $("sheet-modal").classList.add("hide");
  $("sheet-modal").addEventListener("pointerdown", (e) => { if (e.target === $("sheet-modal")) $("sheet-modal").classList.add("hide"); });
}

/* ══════════════════════════════════════════════════════════════════════
   Shell — stage, drawers, dock
   ══════════════════════════════════════════════════════════════════════ */

function stage(which) {
  ["hero", "drafting", "options", "detail"].forEach((s) =>
    $(`st-${s}`).classList.toggle("hide", s !== which));
  // once real work is on the stage, the conversation docks to the side
  document.body.classList.toggle("split", which === "options" || which === "detail");
}

function openDrawer(id) { closeDrawers(); $(id).classList.remove("hide"); }
function closeDrawers() { ["code-drawer", "specs-drawer", "portfolio-drawer"].forEach((d) => $(d).classList.add("hide")); }

function toast(msg, ms = 4200) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hide");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hide"), ms);
}

function autoGrow() {
  const ta = $("chat-input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
}

function openPop() { $("connect-pop").classList.remove("hide"); $("connect").setAttribute("aria-expanded", "true"); $("gh-token").focus(); }
function closePop() { $("connect-pop").classList.add("hide"); $("connect").setAttribute("aria-expanded", "false"); }

async function refreshConnect() {
  const b = $("connect");
  if (!GH.on) {
    // a demo key (or a relay) means the page is live even with no personal
    // token — say so, or the pill reads as "nothing works here"
    const live = !!demoKey || !!TRIGGER_URL;
    b.textContent = live ? "Live" : "Connect";
    b.dataset.on = live ? "1" : "";
    b.title = live
      ? "A restricted key is active — it can only start this repository's workflows"
      : "Add a token to start runs from this page";
    return;
  }
  b.dataset.on = "1";
  b.textContent = "Connected";
  b.title = "Your own GitHub token is in use";
  try {
    const me = await GH.api("/user");
    if (me?.login) b.textContent = me.login;
  } catch { /* fine-grained tokens may lack /user */ }
}

function initConnect() {
  $("connect").onclick = () => $("connect-pop").classList.contains("hide") ? openPop() : closePop();
  document.addEventListener("pointerdown", (e) => {
    if (!$("connect-pop").classList.contains("hide") && !e.target.closest(".connect-wrap")) closePop();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closePop(); closeDrawers(); $("sheet-modal").classList.add("hide"); } });
  $("gh-save").onclick = async () => {
    const v = $("gh-token").value.trim();
    if (!v) { $("gh-state").textContent = "paste a token first"; return; }
    GH.token = v;
    $("gh-state").textContent = "checking…";
    try {
      await GH.api(`/repos/${GH.repo}`);
      $("gh-state").textContent = "connected ✓";
      $("gh-token").value = "";
      refreshConnect();
      setTimeout(closePop, 700);
    } catch (e) {
      $("gh-state").textContent = "rejected: " + e.message.slice(0, 60);
      GH.token = "";
      refreshConnect();
    }
  };
  $("gh-clear").onclick = () => { GH.token = ""; $("gh-token").value = ""; $("gh-state").textContent = "forgotten"; refreshConnect(); };
}

async function boot() {
  Brief.reset();
  initConnect();
  initSheetControls();
  refreshConnect();

  $("composer").addEventListener("submit", (e) => { e.preventDefault(); submitUtterance($("chat-input").value); });
  $("chat-input").addEventListener("input", autoGrow);
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitUtterance($("chat-input").value); }
  });
  $("specs-pill").onclick = () => { renderSpecs(); openDrawer("specs-drawer"); };
  $("portfolio-pill").onclick = async () => { await renderPortfolio(); openDrawer("portfolio-drawer"); };
  document.querySelectorAll(".drawer-x").forEach((b) => { b.onclick = closeDrawers; });

  agentSay(
    "Tell me what you want to build — an office for your startup, a 3BHK, a weekend house, a small warehouse. Plain words are perfect; I'll only ask what I really need.",
    { chips: [
      { label: "An office for my startup", send: "I want to make an office for my small startup — we are 8 people, we need an open studio, a meeting room, a small kitchen and a washroom." },
      { label: "A 3BHK for my family", send: "A 3BHK apartment for my family of four, with a small study." },
      { label: "A weekend house", send: "A small weekend house — two bedrooms, an open kitchen with the living room, one bathroom." },
    ] },
  );

  const q = new URLSearchParams(location.search);
  if (q.get("p")) openPortfolioProject(q.get("p"), q.get("c"));
}

boot().catch((e) => toast("Could not start: " + e.message));

// dev hook, localhost only — the visual-test skill asserts on internals
if (["localhost", "127.0.0.1"].includes(location.hostname)) {
  window.__studio = { parseUtterance, Brief, GH, Chat, Draft, renderOptions, stage, selectCandidate, openCodeDrawer, agentSay };
}

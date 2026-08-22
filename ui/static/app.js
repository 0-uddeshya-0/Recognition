/* Recognition UI — one page, three states. Vanilla JS, no build step. */
(() => {
  const CFG = window.RECOGNITION;
  const app = document.getElementById("app");
  const S = { jobId: CFG.jobId, job: null, pkg: null, pkgRun: null, sheet: 0, tab: "findings", file: null, engine: "local",
              rules: CFG.defaultRules, timer: null, tick: null, clockBase: 0, clockAt: 0, stamped: null };

  // --- helpers ------------------------------------------------------------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const $ = (sel, root = document) => root.querySelector(sel);
  const fmtMB = (b) => b >= 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.round(b / 1e3) + " KB";
  const fmtClock = (s) => { const m = Math.floor(s / 60), r = s - m * 60; return (m ? m + ":" : "") + (m ? String(Math.floor(r)).padStart(2, "0") : Math.floor(r)) + "." + Math.floor((r % 1) * 10) + " s"; };
  const num = (v, d = 2) => (v === null || v === undefined || v === "") ? "" : (Number.isFinite(+v) ? (+v).toFixed(d).replace(/\.?0+$/, "") : v);
  const files = (rel) => `/jobs/${S.jobId}/files/${rel}`;
  let toastT;
  function toast(msg, bad) {
    let t = $(".toast"); if (!t) { t = document.createElement("div"); document.body.appendChild(t); }
    t.className = "toast" + (bad ? " bad" : ""); t.textContent = msg; clearTimeout(toastT); toastT = setTimeout(() => t.remove(), 4200);
  }
  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; } throw new Error(d || r.statusText); }
    return r.json();
  }

  // --- header ---------------------------------------------------------------
  function renderTop() {
    const j = S.job;
    $("#top-new").hidden = !j;
    if (!j) { $("#top-title").innerHTML = ""; $("#top-stamp").innerHTML = ""; $("#top-delta").innerHTML = ""; return; }
    const s = j.summary;
    const run = j.runs.length > 1 ? ` · run ${j.runs[j.runs.length - 1].index}` : "";
    $("#top-title").innerHTML = `<h1>${esc(j.project)}</h1><span class="meta">${esc(j.model_name)}${s ? ` · ${esc(s.schema)} · rev ${esc(s.revision || "—")}` : ""}${run}${j.engine === "devin" ? " · Devin" : ""}</span>`;
    const d = j.delta;
    $("#top-delta").innerHTML = d ? `run ${d.from_run} <b>${d.status_before}</b> → run ${d.to_run} <b>${d.status_after}</b>` +
      (d.errors ? ` · <span class="${d.errors > 0 ? "up" : "down"}">${d.errors > 0 ? "+" : ""}${d.errors} error${Math.abs(d.errors) === 1 ? "" : "s"}</span>` : "") +
      (d.warnings ? ` · <span class="${d.warnings > 0 ? "up" : "down"}">${d.warnings > 0 ? "+" : ""}${d.warnings} warning${Math.abs(d.warnings) === 1 ? "" : "s"}</span>` : "") +
      (d.new_failures.length ? ` · new: ${esc(d.new_failures.slice(0, 3).join(", "))}${d.new_failures.length > 3 ? " …" : ""}` : "") +
      (d.fixed.length ? ` · fixed: ${esc(d.fixed.slice(0, 3).join(", "))}` : "") : "";
    $("#top-stamp").innerHTML = (j.status === "done" && s) ? stamp(s.compliance, false) : "";
  }
  function stamp(c, big) {
    const detail = c.status === "PASS" ? `${c.passed}/${c.checks} checks` :
      [c.errors ? `${c.errors} error${c.errors === 1 ? "" : "s"}` : "", c.warnings ? `${c.warnings} warning${c.warnings === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ");
    const key = `${S.jobId}:${S.job.runs.length}`;
    const press = big && S.stamped !== key; if (big) S.stamped = key;
    return `<span class="stamp ${c.status}${big ? " big" : ""}${press ? " press" : ""}">${c.status}<small>${esc(detail)}</small></span>`;
  }

  // --- state 1: start ---------------------------------------------------------
  function renderStart() {
    const f = S.file;
    app.innerHTML = `
      <section class="start">
        <div class="lede">
          <h2>Drop a model, get the drawings.</h2>
          <p>Schedules, code compliance and dimensioned plan sheets, derived from the IFC by code — so a design change means regenerate and review, not redraw.</p>
        </div>
        <label class="dropzone${f ? " has-file" : ""}" id="drop">
          <input type="file" accept=".ifc" id="file">
          <span class="north">N ▲</span>
          <div class="prompt">
            ${f ? `<strong>${esc(f.name)}</strong><div class="file">${fmtMB(f.size)} <em>· click to change</em></div>`
                : `<strong>Drop an .ifc file here</strong><span>or click to choose · up to 100 MB</span>`}
          </div>
          <div class="tb"><span>Sheet —</span><span>${f ? "Ready" : "Awaiting model"}</span></div>
        </label>
        <div class="samples">
          ${CFG.samples.map((v) => `<button class="sample" data-sample="${v.key}"><span class="try">Try a sample</span><b>${esc(v.label)}</b><span>${esc(v.hint)}</span></button>`).join("")}
        </div>
        <div class="field">
          <label for="instr">Anything to change? <span class="muted" style="font-weight:400">optional</span></label>
          <textarea id="instr" rows="2" placeholder="e.g. “Bedrooms must be ≥ 10 m² under the new code”"></textarea>
        </div>
        <div class="actions">
          ${CFG.devin ? `<div class="seg" id="engine"><button data-e="local" class="${S.engine === "local" ? "on" : ""}">Run here · seconds</button><button data-e="devin" class="${S.engine === "devin" ? "on" : ""}">Send to Devin · opens a PR</button></div>` : ""}
          <button class="btn" id="run" ${f ? "" : "disabled"}>Run detailing</button>
          <span class="muted" id="run-hint">${f ? "" : "Choose a file or a sample"}</span>
        </div>
        <div id="start-err"></div>
        <div class="recent" id="recent" hidden></div>
      </section>`;
    const drop = $("#drop");
    $("#file").addEventListener("change", (e) => { S.file = e.target.files[0] || null; renderStart(); });
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) { S.file = f; renderStart(); } });
    app.querySelectorAll(".sample").forEach((b) => b.addEventListener("click", () => startJob({ sample: b.dataset.sample })));
    $("#run").addEventListener("click", () => startJob({ file: S.file }));
    if (CFG.devin) $("#engine").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { S.engine = b.dataset.e; renderStart(); } });
    loadRecent();
  }
  async function loadRecent() {
    try {
      const jobs = await api("/api/jobs"); const el = $("#recent"); if (!el || !jobs.length) return;
      el.hidden = false;
      el.innerHTML = `<h3>Recent</h3>` + jobs.map((j) => `<a href="/jobs/${j.id}"><span class="dot ${j.compliance || ""}"></span>${esc(j.project)} <span class="muted mono">${j.status}${j.engine === "devin" ? " · Devin" : ""}</span></a>`).join("");
    } catch (_) { /* no recent list, no problem */ }
  }
  async function startJob({ sample, file }) {
    const fd = new FormData();
    if (sample) fd.append("sample", sample); else if (file) fd.append("file", file, file.name); else return;
    const instr = $("#instr"); if (instr && instr.value.trim()) fd.append("instruction", instr.value.trim());
    fd.append("engine", S.engine);
    if (S.rules !== CFG.defaultRules) fd.append("rules_yaml", S.rules);
    const run = $("#run"); if (run) { run.disabled = true; run.textContent = file ? "Uploading…" : "Starting…"; }
    try {
      const { job_id } = await api("/api/jobs", { method: "POST", body: fd });
      S.jobId = job_id; S.job = null; S.pkg = null; S.pkgRun = null; S.sheet = 0; S.stamped = null;
      history.pushState({}, "", `/jobs/${job_id}`);
      poll(true);
    } catch (e) {
      $("#start-err").innerHTML = `<div class="err">${esc(e.message)}</div>`;
      if (run) { run.disabled = false; run.textContent = "Run detailing"; }
    }
  }

  // --- state 2: working -------------------------------------------------------
  function renderWorking() {
    const j = S.job;
    const failed = j.status === "failed";
    const title = failed ? "The run failed" : j.engine === "devin" ? "Devin is working on it" : "Detailing " + j.project;
    app.innerHTML = `
      <section class="card working">
        <header><h2>${esc(title)}</h2><span class="clock" id="clock">${fmtClock(j.elapsed)}</span></header>
        <ul class="steps">
          ${j.steps.map((s) => `<li class="${s.status}"><span class="glyph"></span><span class="name">${esc(s.name)}</span><span class="detail" title="${esc(s.detail)}">${esc(s.detail)}</span></li>`).join("")}
        </ul>
        ${j.engine === "devin" ? `<div class="devin-line"><div class="msg">${esc(j.devin_message || "starting session…")}</div><div class="acu">${j.devin_acus != null ? `${j.devin_acus} ACU` : ""}</div></div>` : ""}
        ${failed ? `<div class="err">${esc(j.error || "unknown error")}</div>` : ""}
        <div class="foot">
          ${j.instruction ? `<span>Request: “${esc(j.instruction)}”</span>` : ""}
          ${j.devin_session_url ? `<a href="${esc(j.devin_session_url)}" target="_blank" rel="noopener">Open session ↗</a>` : ""}
          ${j.pr_url ? `<a href="${esc(j.pr_url)}" target="_blank" rel="noopener">View PR ↗</a>` : ""}
          ${failed ? `<a href="/">Start over</a>` : ""}
          ${failed && j.has_result ? `<a href="#" id="show-last">Show the last good package</a>` : ""}
        </div>
      </section>`;
    const sl = $("#show-last"); if (sl) sl.addEventListener("click", (e) => { e.preventDefault(); S.forceResult = true; render(); });
  }

  // --- state 3: result --------------------------------------------------------
  function renderResult() {
    const j = S.job, p = S.pkg, s = p.summary, sheets = s.sheets;
    S.sheet = Math.min(S.sheet, sheets.length - 1);
    const sh = sheets[S.sheet];
    const bad = new Set(p.failing_tags);
    const counts = { findings: s.compliance.errors + s.compliance.warnings, rooms: p.schedules.rooms.length, doors: p.schedules.doors.length, windows: p.schedules.windows.length };
    const failedIn = (rows) => rows.filter((r) => bad.has(r.tag)).length;
    const tabs = [["findings", "Findings", counts.findings, counts.findings > 0], ["rooms", "Rooms", counts.rooms, failedIn(p.schedules.rooms) > 0],
                  ["doors", "Doors", counts.doors, failedIn(p.schedules.doors) > 0], ["windows", "Windows", counts.windows, failedIn(p.schedules.windows) > 0]];
    const devinJob = j.engine === "devin";
    app.innerHTML = `
      <div class="two">
        <section class="viewer">
          <div class="bar">
            <span class="nav"><button id="prev" ${S.sheet === 0 ? "disabled" : ""} aria-label="previous sheet">◀</button><button id="next" ${S.sheet === sheets.length - 1 ? "disabled" : ""} aria-label="next sheet">▶</button></span>
            <span class="sheetno">${esc(sh.sheet)}</span><span class="storey">${esc(sh.storey)}</span><span class="count">${S.sheet + 1} / ${sheets.length}</span>
            <span class="spacer"></span>
            <a href="${files("sheets/" + sh.pdf)}" target="_blank" rel="noopener">Open PDF ↗</a>
            <a href="${files("sheets/" + sh.dxf)}?download=1">DXF</a>
            <a href="${files("sheets/" + sh.svg)}" target="_blank" rel="noopener">SVG</a>
          </div>
          <a class="sheet" href="${files("sheets/" + sh.pdf)}" target="_blank" rel="noopener" title="Open ${esc(sh.sheet)} as PDF">
            <img src="${files("sheets/" + sh.png)}?r=${j.runs.length}" alt="${esc(sh.sheet)} ${esc(sh.storey)} floor plan">
            ${stamp(s.compliance, true)}
            ${j.approved ? `<span class="stamp big approved">Approved</span>` : ""}
          </a>
          <div class="downloads">
            <span class="lbl">Download</span>
            <a href="/jobs/${S.jobId}/bundle/pdf">PDF set (${sheets.length})</a>
            <a href="/jobs/${S.jobId}/bundle/dxf">DXF set</a>
            <a href="/jobs/${S.jobId}/bundle/schedules">Schedules</a>
            <a href="${files("model.detailed.ifc")}?download=1">model.detailed.ifc</a>
            <a href="${files("report.md")}" target="_blank" rel="noopener">report.md</a>
            <a href="/jobs/${S.jobId}/bundle/all">Everything (zip)</a>
          </div>
        </section>
        <section class="card panel">
          <div class="tabs">${tabs.map(([k, l, n, b]) => `<button data-tab="${k}" class="${S.tab === k ? "on" : ""}">${l}<span class="n${b ? " bad" : ""}">${n}</span></button>`).join("")}</div>
          <div class="tabbody" id="tabbody"></div>
        </section>
      </div>
      <div class="footer">
        <section class="card request">
          <label for="req">Request a change</label>
          <div class="row">
            <textarea id="req" placeholder="${CFG.devin ? "e.g. “Bedrooms must be ≥ 25 m² under the new code” — Devin edits the rules or the generator, regenerates, opens a PR" : "Free-text requests need Devin mode on this server — edit the rules below to re-run here"}"></textarea>
            <button class="btn ${CFG.devin ? "accent" : "secondary"}" id="send">${CFG.devin ? "Send to Devin" : "Send"}</button>
          </div>
          <div class="hint">${devinJob && j.devin_message ? `Devin · ${esc(j.devin_message)}` : j.note ? esc(j.note) : ""}</div>
          <div id="req-err"></div>
        </section>
        <section class="card decide">
          ${j.approved ? `<div class="status"><b>Approved</b>${devinJob && j.pr_url ? " · pull request merged" : " · package accepted"}</div>` :
            `<div class="status">${devinJob ? (j.pr_url ? "Devin opened a pull request with this package." : "No pull request yet.") : "Approve to accept this package as the current revision."}</div>`}
          <button class="btn approve" id="approve" ${j.approved || (devinJob && !j.pr_url) ? "disabled" : ""}>${j.approved ? "Approved ✓" : devinJob ? "Approve & merge" : "Approve"}</button>
          ${j.pr_url ? `<a class="btn secondary" href="${esc(j.pr_url)}" target="_blank" rel="noopener">View PR ↗</a>` : ""}
          ${j.devin_session_url ? `<a class="ghost" href="${esc(j.devin_session_url)}" target="_blank" rel="noopener">Devin session ↗</a>` : ""}
        </section>
      </div>
      <details class="card rules" id="rules">
        <summary>Rules <span class="path">rules/residential.yaml</span> ${j.rules_yaml ? `<span class="edited">edited</span>` : ""}<span class="spacer"></span></summary>
        <div class="body">
          <textarea class="mono" id="rules-text" spellcheck="false">${esc(j.rules_yaml || CFG.defaultRules)}</textarea>
          <div class="row">
            <button class="btn" id="apply">Apply &amp; re-run</button>
            <button class="ghost" id="reset">Reset to default</button>
            <span class="hint">Thresholds are data. Change a number, re-run, watch the verdict.</span>
          </div>
          <div id="rules-err"></div>
        </div>
      </details>`;
    renderTab();
    $("#prev").addEventListener("click", () => { S.sheet--; renderResult(); });
    $("#next").addEventListener("click", () => { S.sheet++; renderResult(); });
    $(".tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { S.tab = b.dataset.tab; renderResult(); } });
    $("#send").addEventListener("click", () => sendMessage($("#req").value.trim(), null, "#req-err"));
    $("#apply").addEventListener("click", () => sendMessage("", $("#rules-text").value, "#rules-err"));
    $("#reset").addEventListener("click", () => { $("#rules-text").value = CFG.defaultRules; });
    $("#approve").addEventListener("click", approve);
    $("#rules").open = S.rulesOpen || false;
    $("#rules").addEventListener("toggle", (e) => { S.rulesOpen = e.target.open; });
    document.onkeydown = (e) => { if (e.target.tagName === "TEXTAREA") return; if (e.key === "ArrowLeft" && S.sheet > 0) { S.sheet--; renderResult(); } if (e.key === "ArrowRight" && S.sheet < sheets.length - 1) { S.sheet++; renderResult(); } };
  }
  function renderTab() {
    const p = S.pkg, bad = new Set(p.failing_tags), body = $("#tabbody");
    if (S.tab === "findings") return body.innerHTML = renderFindings(p);
    const rows = p.schedules[S.tab];
    const cols = { rooms: [["tag", "Tag"], ["storey", "Storey"], ["name", "Name"], ["category", "Category"], ["area_m2", "Area m²", 2], ["height_m", "Height m", 2], ["doors", "Doors"], ["windows", "Windows"]],
                   doors: [["tag", "Tag"], ["storey", "Storey"], ["name", "Name"], ["type", "Type"], ["width_m", "Width m", 3], ["height_m", "Height m", 3], ["external", "Ext."], ["connects", "Connects"]],
                   windows: [["tag", "Tag"], ["storey", "Storey"], ["name", "Name"], ["type", "Type"], ["width_m", "Width m", 2], ["height_m", "Height m", 2], ["glazing_m2", "Glazing m²", 2], ["room", "Room"]] }[S.tab];
    if (!rows.length) return body.innerHTML = `<div class="clear">No ${S.tab} in this model.</div>`;
    body.innerHTML = `<table><thead><tr>${cols.map(([k, l, d]) => `<th class="${d ? "num" : ""}">${l}</th>`).join("")}</tr></thead><tbody>
      ${rows.map((r) => `<tr class="${bad.has(r.tag) ? "bad" : ""}">${cols.map(([k, l, d]) => k === "tag" ? `<td><span class="tag${bad.has(r.tag) ? " bad" : ""}">${esc(r.tag)}</span></td>` :
        `<td class="${d ? "num" : ""}" title="${esc(r[k])}">${d ? num(r[k], d) : esc(r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }
  function renderFindings(p) {
    const c = p.summary.compliance;
    const groups = Object.entries(c.by_rule).map(([id, g]) => ({ id, ...g, results: p.results.filter((r) => r.rule_id === id) }));
    groups.sort((a, b) => (b.failed > 0) - (a.failed > 0) || (a.severity === "error" ? 0 : 1) - (b.severity === "error" ? 0 : 1) || b.failed - a.failed);
    const row = (r) => `<div class="finding ${r.passed ? "ok" : "bad"}"><span class="tag${r.passed ? "" : " bad"}">${esc(r.element_tag)}</span><span class="storey" title="${esc(r.storey)}">${esc(r.storey)}</span>
      <span>${esc(r.message.replace(/^\S+\s/, (m) => r.message.startsWith(r.element_tag) ? "" : m))}</span><span class="vl">${r.value != null ? num(r.value, 3) : "—"}${r.limit != null ? ` / ${num(r.limit, 3)}` : ""}</span></div>`;
    const clear = c.errors + c.warnings === 0 ? `<div class="clear"><b>Nothing to fix.</b> ${c.checks} checks across ${Object.keys(c.by_rule || {}).length} rules all pass.</div>` : "";
    return clear + groups.map((g) => {
      const fails = g.results.filter((r) => !r.passed), ok = g.results.filter((r) => r.passed);
      return `<div class="rule"><div class="head"><span class="id">${esc(g.id)}<span class="sev ${g.severity}">${g.severity}</span></span><span class="t">${esc(g.title)}</span><span class="cnt${g.failed ? " bad" : ""}">${g.failed ? `${g.failed} failed` : "all pass"} · ${g.checked} checked</span></div>
        ${fails.map(row).join("")}
        ${ok.length ? `<details><summary>${ok.length} passed</summary>${ok.map(row).join("")}</details>` : ""}</div>`;
    }).join("");
  }

  function defaultSheet(p) {
    const score = (storey) => p.results.filter((r) => !r.passed && r.storey === storey).length * 1000 + p.schedules.rooms.filter((r) => r.storey === storey).length;
    let best = 0, bestScore = -1;
    p.summary.sheets.forEach((sh, i) => { const sc = score(sh.storey); if (sc > bestScore) { best = i; bestScore = sc; } });
    return best;
  }

  // --- actions ------------------------------------------------------------------
  async function sendMessage(text, rules, errSel) {
    const el = $(errSel); if (el) el.innerHTML = "";
    if (!text && rules === null) { if (el) el.innerHTML = `<div class="note">Describe the change first.</div>`; return; }
    try {
      await api(`/api/jobs/${S.jobId}/message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, rules_yaml: rules }) });
      S.pkg = null; S.pkgRun = null; S.stamped = null;
      poll(true);
    } catch (e) { if (el) el.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  }
  async function approve() {
    const b = $("#approve"); b.disabled = true; b.textContent = "Approving…";
    try { await api(`/api/jobs/${S.jobId}/approve`, { method: "POST" }); toast(S.job.engine === "devin" ? "Pull request merged" : "Package approved"); await poll(false); }
    catch (e) { toast(e.message, true); renderResult(); }
  }

  // --- polling / render ----------------------------------------------------------
  async function poll(loop) {
    clearTimeout(S.timer);
    try { S.job = await api(`/api/jobs/${S.jobId}`); } catch (e) { app.innerHTML = `<section class="start"><div class="err">${esc(e.message)}</div><p><a href="/">Start over</a></p></section>`; return; }
    S.clockBase = S.job.elapsed; S.clockAt = performance.now();
    if (S.job.status === "done" && S.pkgRun !== S.job.runs.length) {
      S.pkg = await api(`/api/jobs/${S.jobId}/package`); S.forceResult = false;
      if (S.pkgRun === null) S.sheet = defaultSheet(S.pkg);
      S.pkgRun = S.job.runs.length;
    }
    render();
    if (loop && (S.job.status === "running" || S.job.status === "queued")) S.timer = setTimeout(() => poll(true), 1000);
  }
  function render() {
    renderTop();
    clearInterval(S.tick);
    const j = S.job;
    if (!j) return renderStart();
    if (j.status === "done" && S.pkg) return renderResult();
    if (j.status === "failed" && S.forceResult && S.pkg) return renderResult();
    renderWorking();
    if (j.status === "running" || j.status === "queued") S.tick = setInterval(() => { const c = $("#clock"); if (c) c.textContent = fmtClock(S.clockBase + (performance.now() - S.clockAt) / 1000); }, 100);
  }
  window.addEventListener("popstate", () => { const m = location.pathname.match(/^\/jobs\/([a-z0-9]+)/); S.jobId = m ? m[1] : null; S.job = null; S.pkg = null; S.pkgRun = null; if (S.jobId) poll(true); else render(); });
  if (S.jobId) poll(true); else render();
})();

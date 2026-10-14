"use strict";
// amanuense review app: every change, every decision, one place.

// The session key comes in the URL fragment (never sent to a server log); it is kept for
// this tab only, so a reload works and the address bar stays clean.
const TOKEN = (() => {
  const fromUrl = new URLSearchParams(location.hash.slice(1)).get("t");
  try {
    if (fromUrl) sessionStorage.setItem("amanuense-token", fromUrl);
    return fromUrl || sessionStorage.getItem("amanuense-token") || "";
  } catch (e) {
    return fromUrl || "";
  }
})();
history.replaceState(null, "", location.pathname);

const S = { data: null, rel: null, page: null, tab: "changes", filter: "todo", query: "", busy: false, aside: false, deciding: null, view: "review" };
let T = {};
const t = (key, fields = {}) => (T[key] || key).replace(/\{(\w+)\}/g, (_, k) => (k in fields ? fields[k] : `{${k}}`));

// ── DOM helper: text is always text, never parsed as HTML ──
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v; // via CSSOM: the CSP blocks style attributes
    else if (k === "html") el.innerHTML = v; // only for HTML the server already escaped
    else el.setAttribute(k, v === true ? "" : v);
  }
  el.append(...nodes(kids));
  return el;
}
// The DOM turns null into the text "null": drop empty children before append/replaceChildren.
const nodes = (kids) => kids.flat(Infinity).filter((k) => k != null && k !== false && k !== "").map((k) => (k.nodeType ? k : String(k)));
const $ = (sel) => document.querySelector(sel);

// ── API ──
async function api(path, body) {
  const opts = { method: body === undefined ? "GET" : "POST", headers: { "X-Amanuense-Token": TOKEN } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error(t("ui_server_gone"));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(text, kind = "ok") {
  const box = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, text);
  $("#toasts").append(box);
  setTimeout(() => box.remove(), kind === "error" ? 9000 : 4000);
}

async function act(fn, done) {
  try {
    const out = await fn();
    if (done) toast(done);
    return out;
  } catch (e) {
    toast(e.message, "error");
    return null;
  }
}

// ── Loading ──
async function load(keepPage = true) {
  const data = await act(() => api("/api/state"));
  if (!data) return;
  S.data = data;
  T = data.texts;
  document.documentElement.lang = data.lang;
  document.title = t("ui_title");
  if (keepPage && S.rel && !data.proposals.some((p) => p.rel === S.rel)) S.rel = null;
  if (!S.rel && data.proposals.length) S.rel = firstToReview()?.rel || data.proposals[0].rel;
  if (S.rel) await openPage(S.rel, false);
  render();
  if (data.job.running) watchJob();
}

function firstToReview() {
  return S.data.proposals.find((p) => p.status === "pendiente") || S.data.proposals.find((p) => p.status === "aprobada");
}

async function openPage(rel, draw = true) {
  if (draw && rel === S.rel && S.page) return;
  const page = await act(() => api(`/api/page?rel=${encodeURIComponent(rel)}`));
  if (!page) return;
  if (rel !== S.rel) S.deciding = null;
  S.rel = rel;
  S.page = page;
  S.draft = null;
  if (draw) render();
}

function applyPage(page) {
  S.page = page;
  const i = S.data.proposals.findIndex((p) => p.rel === page.proposal.rel);
  if (i >= 0) S.data.proposals[i] = page.proposal;
  render();
}

// ── Labels ──
const STATUS_ORDER = ["pendiente", "aprobada", "publicada", "descartada"];
const statusLabel = (s) => t(`status_${s}`);
// Repo names without branches; the full repo@branch list lives in the Origin tab.
function repoSummary(repos) {
  const names = [...new Set(repos.map((r) => r.split("@")[0]))];
  return names.length > 2 ? t("ui_n_repos", { n: names.length }) : names.join(", ");
}
function originLabel(o) {
  if (o.kind === "request") return t("origin_request", { by: o.by.join(", ") });
  if (o.kind === "chained") return t("origin_chained", { by: o.by.join(", ") || "?", repos: repoSummary(o.repos) });
  if (o.kind === "code") return t("origin_code", { repos: repoSummary(o.repos) });
  return t("origin_docs");
}
const isConflict = (n) => /^\**(CONFLICTO|CONFLICT)\**\s*:/.test(n);
const when = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") : "");

// ── Render ──
// Re-rendering rebuilds the panes: keep the reader where they were (the detail only on the same page).
let shownRel = null;
function render() {
  const app = $("#app");
  const keep = { inbox: $(".inbox")?.scrollTop || 0, detail: shownRel === S.rel ? $(".detail")?.scrollTop || 0 : 0 };
  const hasWork = S.data.proposals.length || S.data.set_aside.length;
  if (!hasWork) S.view = "intake"; // with nothing to review the intake screen is the app; it stays until the person leaves it
  app.replaceChildren(header(), S.view === "intake" ? intakeView() : main());
  shownRel = S.rel;
  if ($(".inbox")) $(".inbox").scrollTop = keep.inbox;
  if ($(".detail")) $(".detail").scrollTop = keep.detail;
}

function header() {
  const d = S.data;
  const job = d.job;
  return h("header", { class: "top" },
    h("div", { class: "brand" }, h("b", {}, "amanuense"), h("span", { class: "muted", title: d.workspace }, d.workspace.split(/[\\/]/).filter(Boolean).pop())),
    d.source?.kind ? h("span", { class: `source-pill ${d.source.kind}`, title: d.source.warning || sourceText(d.source) }, sourceText(d.source)) : null,
    job.running ? h("div", { class: "pill run", role: "status" }, h("span", { class: "spin" }), t(`ui_job_${job.name}`)) : null,
    h("div", { class: "grow" }),
    h("span", { class: "muted you" }, t("ui_you_are", { user: d.user })),
    h("button", { class: S.view === "intake" ? "ghost on" : "ghost", onclick: openIntake, "aria-pressed": S.view === "intake" }, t("ui_add_docs")),
    h("button", { onclick: () => startJob("run"), disabled: job.running, title: t("ui_run_help") }, t("ui_run")),
    h("button", { class: "ghost", onclick: settingsDialog }, t("ui_settings")),
    menu());
}

function menu() {
  const items = [
    [t("ui_radiator"), () => startJob("radiator")],
    [t("ui_deliver"), () => startJob("deliver")],
    [t("ui_open_log"), () => act(() => api("/api/open", { what: "log" }))],
    [t("ui_open_workspace"), () => act(() => api("/api/open", { what: "workspace" }))],
    [t("ui_close"), closeApp],
  ];
  const list = h("div", { class: "menu-list", hidden: true },
    items.map(([label, fn]) => h("button", { class: "ghost", onclick: () => { list.hidden = true; fn(); } }, label)));
  return h("div", { class: "menu" },
    h("button", { class: "ghost", "aria-haspopup": "true", onclick: () => (list.hidden = !list.hidden) }, t("ui_more")),
    list);
}

function main() {
  return h("main", { class: "layout" }, inbox(), S.page ? detail() : h("section", { class: "detail empty" }, t("ui_pick")));
}

// ── Inbox ──
const FILTERS = {
  todo: () => true,
  pendiente: (p) => p.status === "pendiente",
  conflicto: (p) => p.conflicts > 0,
  aprobada: (p) => p.status === "aprobada",
  publicada: (p) => p.status === "publicada",
  descartada: (p) => p.status === "descartada",
};

function inbox() {
  const all = S.data.proposals;
  const done = all.filter((p) => p.status === "publicada" || p.status === "descartada").length;
  const shown = all
    .filter(FILTERS[S.filter])
    .filter((p) => !S.query || p.title.toLowerCase().includes(S.query.toLowerCase()))
    .sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || b.conflicts - a.conflicts);
  const count = (f) => all.filter(FILTERS[f]).length;
  return h("aside", { class: "inbox" },
    h("div", { class: "progress", title: t("ui_progress", { done, total: all.length }) },
      h("div", { class: "bar" }, h("div", { style: `width:${all.length ? (100 * done) / all.length : 0}%` })),
      h("small", {}, t("ui_progress", { done, total: all.length }))),
    h("input", { type: "search", placeholder: t("ui_search"), value: S.query, "aria-label": t("ui_search"),
      oninput: (e) => { S.query = e.target.value; refreshInbox(); } }),
    h("div", { class: "chips", role: "tablist" },
      Object.keys(FILTERS).map((f) => h("button", { role: "tab", "aria-selected": S.filter === f, class: S.filter === f ? "chip on" : "chip",
        onclick: () => { S.filter = f; render(); } }, `${t(`ui_filter_${f}`)} ${count(f)}`))),
    h("ul", { class: "pages" }, shown.length ? shown.map(row) : h("li", { class: "muted pad" }, t("ui_none_here"))),
    setAside(),
    candidatesAside());
}

function refreshInbox() {
  const old = $(".inbox");
  if (old) {
    const pos = old.querySelector("input").selectionStart;
    old.replaceWith(inbox());
    const input = $(".inbox input");
    input.focus();
    input.setSelectionRange(pos, pos);
  }
}

function row(p) {
  return h("li", {},
    h("button", { class: `page-row ${p.rel === S.rel ? "on" : ""}`, onclick: () => openPage(p.rel), "aria-current": p.rel === S.rel },
      h("span", { class: `dot ${p.status}`, title: statusLabel(p.status) }),
      h("span", { class: "title" }, p.title, p.new ? h("em", { class: "tag" }, t("ui_new_page")) : null),
      h("small", { class: "muted" }, originLabel(p.origin)),
      h("span", { class: "badges" },
        p.conflicts ? h("span", { class: "badge red" }, t("ui_n_conflicts", { n: p.conflicts })) : null,
        p.notices.length - p.conflicts ? h("span", { class: "badge amber" }, t("ui_n_pending", { n: p.notices.length - p.conflicts })) : null,
        p.stale ? h("span", { class: "badge amber" }, t("ui_stale")) : null)));
}

function setAside() {
  const list = S.data.set_aside;
  if (!list.length) return null;
  return h("details", { class: "aside", open: S.aside, ontoggle: (e) => (S.aside = e.target.open) },
    h("summary", {}, t("ui_set_aside", { n: list.length })),
    h("p", { class: "muted" }, t("ui_set_aside_help")),
    h("ul", {}, list.map((x) => h("li", {},
      h("div", {}, h("b", {}, x.title), " ", h("span", { class: `badge ${x.categoria === "dudosa" ? "amber" : "grey"}` }, t(`ui_cat_${x.categoria}`))),
      h("small", { class: "muted" }, x.motivo || "—"),
      h("button", { class: "small", disabled: S.data.job.running,
        onclick: async () => { if (await act(() => api("/api/promote", { rel: x.rel }), t("ui_promoted"))) load(); } }, t("ui_promote"))))));
}

// ── Page detail ──
function detail() {
  const { proposal: p } = S.page;
  const tabs = [["changes", t("ui_tab_changes")], ["preview", t("ui_tab_preview")], ["edit", t("ui_tab_edit")],
    ["origin", t("ui_tab_origin")], ["history", t("ui_tab_history", { n: S.page.history.length })]];
  return h("section", { class: "detail" },
    h("div", { class: "head" },
      h("div", {},
        h("h1", {}, p.title),
        h("div", { class: "meta" },
          h("span", { class: `pill ${p.status}` }, statusLabel(p.status)),
          p.new ? h("span", { class: "pill" }, t("ui_new_page")) : null,
          h("span", { class: "muted" }, originLabel(p.origin)),
          S.page.edited ? h("span", { class: "muted" }, t("ui_edited_by_hand")) : null)),
      p.published ? published(p) : null),
    p.stale ? h("div", { class: "note amber" }, t("ui_stale_help")) : null,
    p.status === "descartada" ? h("div", { class: "note grey" }, t("ui_discarded_note", { by: p.by, note: p.note })) : null,
    notices(),
    h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, label]) =>
      h("button", { role: "tab", "aria-selected": S.tab === k, class: S.tab === k ? "tab on" : "tab", onclick: () => { S.tab = k; render(); } }, label))),
    h("div", { class: "tab-body" }, { changes: changes, preview: preview, edit: editor, origin: origin, history: historyTab }[S.tab]()),
    actions());
}

function published(p) {
  const pub = p.published;
  return h("div", { class: "published" },
    h("div", {}, t(pub.mode === "api" ? "ui_published_api" : "ui_published_manual", { by: pub.by, when: when(pub.when), version: pub.version ?? "—" })),
    pub.url ? h("a", { href: pub.url, target: "_blank", rel: "noopener" }, t("ui_open_in_mind")) : null,
    pub.mode === "api" ? h("button", { class: "small ghost", onclick: undoPublish }, t("ui_undo")) : null);
}

function notices() {
  const list = S.page.proposal.notices;
  if (!list.length) return h("div", { class: "note green" }, t("ui_no_notices"));
  return h("div", { class: "notices" },
    h("h2", {}, t("ui_notices", { n: list.length })),
    h("ul", {}, list.map((n) => {
      const conflict = isConflict(n);
      const box = h("li", { class: conflict ? "conflict" : "pending" },
        h("span", { class: `badge ${conflict ? "red" : "amber"}` }, conflict ? t("ui_conflict") : t("ui_pending")),
        h("span", { class: "txt" }, n.replace(/^\**(CONFLICTO|CONFLICT|PENDIENTE|PENDING)\**\s*:\s*/, "")),
        h("span", { class: "row" },
          h("button", { class: "small ghost", onclick: () => jumpTo(n) }, t("ui_jump")),
          h("button", { class: `small ${conflict ? "" : "ghost"}`, onclick: () => { S.deciding = { notice: n, text: "", scroll: true }; render(); } }, conflict ? t("ui_decide") : t("ui_resolve"))));
      if (S.deciding?.notice === n) box.append(decideForm(n));
      return box;
    })));
}

// The draft lives in S.deciding so a re-render (a job ending, a toast action) never loses it.
function decideForm(notice) {
  const d = S.deciding;
  const area = h("textarea", { rows: 3, required: true, placeholder: t("ui_decision_ph"), "aria-label": t("ui_decision_ph"),
    oninput: (e) => (d.text = e.target.value) });
  area.value = d.text;
  const form = h("form", { class: "decide", onsubmit: async (e) => {
      e.preventDefault();
      const page = await act(() => api("/api/resolve", { rel: S.rel, notice, decision: area.value }), t("ui_decided"));
      if (page) { S.deciding = null; applyPage(page); }
    } },
    area,
    h("p", { class: "muted" }, t("ui_decision_help")),
    h("div", { class: "row" },
      h("button", { type: "submit" }, t("ui_save_decision")),
      S.data.settings.ai_cli || S.data.settings.ai_url ? h("button", { type: "button", class: "ghost",
        onclick: () => area.value.trim() ? startJob("rework", { rel: S.rel, instruction: `${t("ui_rework_about", { notice })} ${area.value}` }) : area.reportValidity() }, t("ui_ask_ai")) : null,
      h("button", { type: "button", class: "ghost", onclick: () => { S.deciding = null; render(); } }, t("ui_cancel"))));
  if (d.scroll) {
    d.scroll = false;
    requestAnimationFrame(() => { area.focus({ preventScroll: true }); revealAboveBar(form); });
  }
  return form;
}

// scrollIntoView counts the sticky action bar as visible space, so measure against the bar itself.
function revealAboveBar(el) {
  const scroller = el.closest(".detail");
  const bar = scroller?.querySelector(".actions");
  if (!scroller || !bar) return el.scrollIntoView({ block: "nearest" });
  const hidden = el.getBoundingClientRect().bottom + 12 - bar.getBoundingClientRect().top;
  if (hidden > 0) scroller.scrollBy({ top: hidden });
}

function jumpTo(notice) {
  S.tab = "edit";
  render();
  const area = $("#editor");
  const text = area.value;
  const i = text.indexOf(notice.replace(/^\s*/, ""));
  if (i >= 0) {
    area.focus();
    area.setSelectionRange(i, i + notice.length);
    const line = text.slice(0, i).split("\n").length;
    area.scrollTop = Math.max(0, (line - 4) * parseFloat(getComputedStyle(area).lineHeight || 20));
  }
}

// Side-by-side diff; long runs of equal lines fold away.
function changes() {
  const rows = S.page.diff;
  if (!S.page.before) return h("div", {}, h("p", { class: "muted" }, t("ui_new_page_help")), preview());
  const changed = rows.filter((r) => r.op !== "equal").length;
  if (!changed) return h("p", { class: "muted pad" }, t("ui_no_changes"));
  const body = [];
  rows.forEach((r, k) => {
    if (r.op === "equal") {
      const fold = r.a.length > 6 ? r.a.length - 4 : 0;
      const pairs = r.a.map((line, i) => [r.a_start + i, line, r.b_start + i, r.b[i]]);
      const head = fold ? pairs.slice(0, k === 0 ? 0 : 2) : pairs;
      const tail = fold ? pairs.slice(k === rows.length - 1 ? pairs.length : pairs.length - 2) : [];
      head.forEach((p) => body.push(line("eq", ...p)));
      if (fold) {
        const hidden = pairs.slice(head.length, pairs.length - tail.length);
        const tr = h("tr", { class: "fold" }, h("td", { colspan: 4 },
          h("button", { class: "small ghost", onclick: () => tr.replaceWith(...hidden.map((p) => line("eq", ...p))) },
            t("ui_show_equal", { n: hidden.length }))));
        body.push(tr);
      }
      tail.forEach((p) => body.push(line("eq", ...p)));
      return;
    }
    const n = Math.max(r.a.length, r.b.length);
    for (let i = 0; i < n; i++) {
      body.push(line(r.op, i < r.a.length ? r.a_start + i : "", r.a[i], i < r.b.length ? r.b_start + i : "", r.b[i]));
    }
  });
  return h("div", {},
    h("p", { class: "muted" }, t("ui_diff_help", { n: changed })),
    h("table", { class: "diff" },
      // table-layout: fixed sizes columns from the first row (colspan headers): the colgroup sets them.
      h("colgroup", {}, h("col", { class: "n" }), h("col", {}), h("col", { class: "n" }), h("col", {})),
      h("thead", {}, h("tr", {}, h("th", { colspan: 2 }, t("ui_before")), h("th", { colspan: 2 }, t("ui_after")))),
      h("tbody", {}, body)));
}

function line(op, an, a, bn, b) {
  const cls = op === "eq" ? "" : op;
  return h("tr", { class: cls },
    h("td", { class: "n" }, an), h("td", { class: a === undefined ? "gap" : "a" }, a ?? ""),
    h("td", { class: "n" }, bn), h("td", { class: b === undefined ? "gap" : "b" }, b ?? ""));
}

function preview() {
  return h("article", { class: "preview", html: S.page.preview });
}

function editor() {
  const area = h("textarea", { id: "editor", spellcheck: "true", "aria-label": t("ui_tab_edit"),
    oninput: () => { S.draft = area.value; schedulePreview(area.value); saveBtn.disabled = false; } });
  area.value = S.draft ?? S.page.result;
  const live = h("article", { class: "preview live", id: "live", html: S.page.preview });
  const saveBtn = h("button", { disabled: S.draft == null, onclick: async () => {
      const page = await act(() => api("/api/save", { rel: S.rel, markdown: area.value }), t("ui_saved"));
      if (page) { S.draft = null; applyPage(page); }
    } }, t("ui_save"));
  return h("div", {},
    h("p", { class: "muted" }, t("ui_edit_help")),
    h("div", { class: "split" }, area, live),
    h("div", { class: "row" }, saveBtn,
      h("button", { class: "ghost", onclick: () => { S.draft = null; render(); } }, t("ui_discard_edits")),
      S.data.settings.ai_cli || S.data.settings.ai_url ? h("button", { class: "ghost", onclick: askAi }, t("ui_ask_ai")) : null));
}

let previewTimer;
function schedulePreview(markdown) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const out = await act(() => api("/api/preview", { markdown }));
    if (out && $("#live")) $("#live").innerHTML = out.html; // escaped by the server
  }, 300);
}

function askAi() {
  const area = h("textarea", { rows: 3, required: true, placeholder: t("ui_ai_ph") });
  modal(t("ui_ask_ai"), h("p", { class: "muted" }, t("ui_ai_help")), area,
    [[t("ui_ask_ai"), () => { if (!area.value.trim()) return area.reportValidity(), false; startJob("rework", { rel: S.rel, instruction: area.value }); }]]);
}

function origin() {
  const pg = S.page;
  const parts = [];
  if (pg.requests.length) parts.push(h("h3", {}, t("ui_requests")), h("ul", {}, pg.requests.map((r) =>
    h("li", {}, h("b", {}, r.by), ` · ${when(r.when)}`, h("blockquote", {}, r.text),
      r.change ? h("p", {}, h("b", {}, t("ui_what")), " ", r.change) : null, r.why ? h("p", { class: "muted" }, r.why) : null))));
  if (pg.triage.categoria) parts.push(h("h3", {}, t("ui_triage")),
    h("p", {}, h("span", { class: "badge grey" }, t(`ui_cat_${pg.triage.categoria}`)), " ", pg.triage.motivo || ""),
    pg.triage.cambios?.length ? h("ul", {}, pg.triage.cambios.map((c) => h("li", {}, c))) : null);
  if (pg.commits.length) parts.push(h("h3", {}, t("ui_commits", { n: pg.commits.length })), h("table", { class: "plain" },
    h("tbody", {}, pg.commits.map((c) => h("tr", {}, h("td", {}, h("code", {}, c.hash)), h("td", {}, `${c.repo}@${c.branch}`),
      h("td", {}, c.what), h("td", { class: "muted" }, `${c.by} · ${when(c.when)}`))))));
  if (pg.proposal.others.length) parts.push(h("p", { class: "muted" }, t("ui_others", { n: pg.proposal.others.length })));
  if (!parts.length) parts.push(h("p", {}, t("ui_origin_docs")));
  parts.push(h("button", { class: "ghost small", onclick: showTask }, t("ui_show_task")));
  return h("div", { class: "origin" }, parts);
}

async function showTask() {
  const out = await act(() => api(`/api/task?rel=${encodeURIComponent(S.rel)}`));
  if (out) modal(t("ui_task_title"), h("pre", { class: "task" }, out.text), null, [], true);
}

function historyTab() {
  const list = S.page.history;
  if (!list.length) return h("p", { class: "muted pad" }, t("ui_no_history"));
  return h("ol", { class: "history" }, [...list].reverse().map((e) => h("li", {}, h("b", {}, e.by), ` · ${when(e.when)} · `, e.what)));
}

// ── Actions ──
function actions() {
  const p = S.page.proposal;
  const running = S.data.job.running;
  const btn = (label, fn, cls = "", extra = {}) => h("button", { class: cls, onclick: fn, disabled: running || extra.disabled, title: extra.title }, label);
  const items = [];
  if (p.status !== "descartada" && p.status !== "publicada") items.push(btn(t("ui_discard"), discardDialog, "ghost"));
  if (p.status !== "pendiente") items.push(btn(t("ui_reopen"), () => doAction("/api/reopen", {}, t("ui_reopened")), "ghost"));
  if (p.status === "pendiente") items.push(btn(t("ui_approve"), () => doAction("/api/approve", {}, t("ui_approved")), "",
    { disabled: p.conflicts > 0, title: p.conflicts ? t("ui_approve_blocked") : "" }));
  if (p.status === "aprobada") items.push(btn(t("ui_publish"), publishDialog, "primary"));
  const next = nextRel();
  return h("footer", { class: "actions" },
    p.conflicts && p.status === "pendiente" ? h("span", { class: "muted" }, t("ui_approve_blocked")) : null,
    h("div", { class: "grow" }), items,
    next ? h("button", { class: "ghost", onclick: () => openPage(next), title: "j" }, t("ui_next")) : null);
}

async function doAction(path, extra, done) {
  const page = await act(() => api(path, { rel: S.rel, ...extra }), done);
  if (page) applyPage(page);
  return page;
}

function nextRel() {
  const list = S.data.proposals.filter(FILTERS[S.filter]);
  const i = list.findIndex((p) => p.rel === S.rel);
  const after = [...list.slice(i + 1), ...list.slice(0, Math.max(i, 0))];
  return (after.find((p) => p.status === "pendiente") || after[0])?.rel;
}

function discardDialog() {
  const area = h("textarea", { rows: 3, required: true, placeholder: t("ui_discard_ph") });
  modal(t("ui_discard"), h("p", { class: "muted" }, t("ui_discard_help")), area,
    [[t("ui_discard"), async () => {
      if (!area.value.trim()) return area.reportValidity(), false;
      await doAction("/api/discard", { reason: area.value }, t("ui_discarded"));
    }]]);
}

// ── Publishing ──
function publishDialog() {
  const p = S.page.proposal;
  const auto = S.data.settings.has_token && S.data.settings.url;
  const body = h("div", { class: "publish" });
  const tabs = h("div", { class: "tabs" });
  const show = (which) => {
    tabs.replaceChildren(
      h("button", { class: which === "api" ? "tab on" : "tab", onclick: () => show("api") }, t("ui_pub_api")),
      h("button", { class: which === "manual" ? "tab on" : "tab", onclick: () => show("manual") }, t("ui_pub_manual")));
    body.replaceChildren(which === "api" ? publishApi(p, auto) : publishManual(p));
  };
  modal(t("ui_publish_title", { title: p.title }), tabs, body, []);
  show(auto ? "api" : "manual");
}

function publishApi(p, configured) {
  if (!configured) return h("div", {}, h("p", {}, t("ui_pub_api_off")),
    h("button", { onclick: () => { closeModal(); settingsDialog(); } }, t("ui_settings")));
  const box = h("div", {});
  let parent = "";
  const parentInput = p.new ? h("input", { list: "mind-pages", placeholder: t("ui_parent_ph"), "aria-label": t("ui_parent"),
    onchange: (e) => { parent = e.target.value; check(); } }) : null;
  const pages = h("datalist", { id: "mind-pages" }, S.data.pages.map((x) => h("option", { value: x })));
  const out = h("div", { class: "checks", "aria-live": "polite" });
  async function check() {
    out.replaceChildren(h("p", { class: "muted" }, h("span", { class: "spin" }), t("ui_checking")));
    let res;
    try { res = await api("/api/preflight", { rel: S.rel, parent }); }
    catch (e) { out.replaceChildren(h("div", { class: "note red" }, e.message)); return; }
    const accept = h("input", { type: "checkbox", id: "accept" });
    const go = h("button", { class: "primary", disabled: res.blockers.length > 0 || res.warnings.length > 0, onclick: async () => {
        go.disabled = true;
        go.replaceChildren(h("span", { class: "spin" }), t("ui_publishing"));
        const page = await act(() => api("/api/publish", { rel: S.rel, parent, accept_warnings: accept.checked }), t("ui_published_ok"));
        if (page) { closeModal(); shownRel = null; applyPage(page); } else check();
      } }, t("ui_publish_now"));
    accept.addEventListener("change", () => (go.disabled = res.blockers.length > 0 || !accept.checked));
    out.replaceChildren(...nodes([
      res.page ? h("p", { class: "ok" }, "✓ ", t("ui_found_page", { version: res.page.version, by: res.page.by, when: when(res.page.when) }), " ",
        h("a", { href: res.page.url, target: "_blank", rel: "noopener" }, t("ui_open_in_mind"))) : null,
      res.parent ? h("p", { class: "ok" }, "✓ ", t("ui_found_parent", { title: res.parent.title })) : null,
      res.blockers.length ? h("div", { class: "note red" }, h("b", {}, t("ui_blocked")), h("ul", {}, res.blockers.map((b) => h("li", {}, b))),
        h("p", {}, t("ui_blocked_help"))) : h("p", { class: "ok" }, "✓ ", t("ui_no_blockers")),
      res.warnings.length > 0 && !res.blockers.length ? h("div", { class: "note amber" }, h("ul", {}, res.warnings.map((w) => h("li", {}, w))),
        h("label", {}, accept, " ", t("ui_accept_warnings"))) : null,
      h("p", { class: "muted" }, t("ui_pub_api_safety")),
      h("div", { class: "row" }, go, h("button", { class: "ghost", onclick: check }, t("ui_check_again")))]));
  }
  box.append(...nodes([p.new ? h("label", {}, t("ui_parent"), parentInput, pages) : null, out]));
  if (!p.new) check(); else out.append(h("p", { class: "muted" }, t("ui_parent_help")));
  return box;
}

function publishManual(p) {
  const s = S.data.settings;
  const link = s.url ? `${s.url.replace(/\/$/, "")}/display/${encodeURIComponent(s.space || "")}/${encodeURIComponent(p.title).replace(/%20/g, "+")}` : "";
  const url = h("input", { type: "url", value: link, placeholder: "https://…", "aria-label": t("ui_page_url") });
  const copied = h("span", { class: "muted" });
  return h("ol", { class: "steps" },
    h("li", {}, h("p", {}, t(p.new ? "ui_step_open_new" : "ui_step_open")),
      link ? h("a", { href: link, target: "_blank", rel: "noopener" }, t("ui_open_in_mind")) : h("span", { class: "muted" }, t("ui_no_mind_url"))),
    h("li", {}, h("p", {}, t("ui_step_copy")), h("button", { onclick: async () => { copied.textContent = (await copyPage()) ? t("ui_copied") : t("ui_copy_failed"); } }, t("ui_copy")), " ", copied),
    h("li", {}, h("p", {}, t("ui_step_paste"))),
    h("li", {}, h("p", {}, t("ui_step_done")), h("label", {}, t("ui_page_url"), url),
      h("button", { class: "primary", onclick: async () => {
        if (!url.value.trim()) return url.reportValidity();
        const page = await act(() => api("/api/mark-published", { rel: S.rel, url: url.value }), t("ui_marked"));
        if (page) { closeModal(); shownRel = null; applyPage(page); }
      } }, t("ui_mark_published"))));
}

async function copyPage() {
  const html = S.page.paste;
  try {
    await navigator.clipboard.write([new ClipboardItem({
      "text/html": new Blob([html], { type: "text/html" }),
      "text/plain": new Blob([S.page.result], { type: "text/plain" }) })]);
    return true;
  } catch (e) { /* older browsers: copy a selection of the rendered page */ }
  const holder = h("div", { class: "offscreen", html });
  document.body.append(holder);
  const range = document.createRange();
  range.selectNodeContents(holder);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  const ok = document.execCommand("copy");
  sel.removeAllRanges();
  holder.remove();
  return ok;
}

async function undoPublish() {
  modal(t("ui_undo"), h("p", {}, t("ui_undo_help")), null, [[t("ui_undo"), () => doAction("/api/undo", {}, t("ui_undone"))]]);
}

// ── Jobs ──
async function startJob(name, extra = {}) {
  closeModal();
  const job = await act(() => api("/api/job", { name, ...extra }));
  if (!job) return;
  S.data.job = job;
  render();
  watchJob();
}

let watching = false;
async function watchJob() {
  if (watching) return;
  watching = true;
  while (true) {
    await new Promise((r) => setTimeout(r, I.phase === "compare" ? 400 : 1000));
    const job = await act(() => api("/api/job"));
    if (job && S.data) S.data.job = job;
    if (job?.running && S.view === "intake" && I.phase === "compare") drawProgress();
    if (!job || !job.running) {
      watching = false;
      if (job) jobDone(job);
      return;
    }
  }
}

async function jobDone(job) {
  if (job.name === "intake") {
    intakeFinished(job);
    if (job.error) toast(t("ui_job_failed", { error: job.error }), "error");
    else toast(t("ui_run_done", { ready: job.result.ready, tasks: job.result.tasks }));
  } else if (job.error) toast(t("ui_job_failed", { error: job.error }), "error");
  else if (job.name === "run") {
    const r = job.result;
    toast(t("ui_run_done", { ready: r.ready, tasks: r.tasks }));
    if (r.warnings.length || Object.keys(r.errors).length)
      modal(t("ui_run_warnings"), h("ul", {}, [...r.warnings, ...Object.entries(r.errors).map(([k, v]) => `${k}: ${v}`)].map((x) => h("li", {}, x))), null, []);
  } else if (job.name === "deliver") {
    modal(t("ui_deliver_done"), h("p", {}, job.result), null, [[t("ui_open_folder"), () => act(() => api("/api/open", { what: "delivery" }))]]);
  } else if (job.name === "radiator") {
    modal(t("ui_radiator_done"), h("p", {}, job.result), null, [[t("ui_open_radiator"), () => act(() => api("/api/open", { what: "radiator" }))]]);
  } else toast(t("ui_job_ok"));
  await load();
}

// ── Adding documentation: drop a pile, check it, upload it, compare it with Confluence ──
// The browser lists and fingerprints the files; the server says what is used and what is not
// (the same rules it applies later), so nothing useless is uploaded. Files go one by one as
// raw bodies, a few at a time, into a batch folder of their own.
const LIST_STEP = 300; // rows drawn at once; the rest on demand
const UPLOADERS = 4;
const I = { items: [], phase: "pick", tab: "use", query: "", shown: LIST_STEP, scan: { done: 0, total: 0, found: 0 },
  batch: null, sent: 0, sentBytes: 0, failed: [], result: null, error: "", unreadable: 0, abort: null, nextId: 1 };

const fmtSize = (n) => {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i ? n.toLocaleString(undefined, { maximumFractionDigits: n < 10 ? 1 : 0 }) : n} ${units[i]}`;
};
const fmtNum = (n) => Number(n || 0).toLocaleString();
const readable = () => new Set(S.data.formats);
const extOf = (path) => { const m = /\.([^./]+)$/.exec(path); return m ? `.${m[1].toLowerCase()}` : ""; };
const live = (items) => items.filter((x) => !x.removed);

function openIntake() {
  S.view = "intake";
  if (I.phase === "done" && !I.items.length) I.phase = "pick";
  render();
  requestAnimationFrame(() => $(".intake h1")?.focus());
}

function resetIntake() {
  Object.assign(I, { items: [], phase: "pick", tab: "use", query: "", shown: LIST_STEP, batch: null, sent: 0, sentBytes: 0,
    failed: [], result: null, error: "", unreadable: 0, setAside: 0 });
}

// Folders: DataTransferItem entries must be taken during the drop event itself, then walked.
async function filesFromDrop(dt) {
  const entries = [...(dt.items || [])].filter((i) => i.kind === "file").map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
  if (!entries.length || entries.some((e) => !e)) return [...dt.files].map((file) => ({ file, path: file.name }));
  const out = [];
  const walk = async (entry) => {
    try {
      if (entry.isFile) {
        const file = await new Promise((ok, ko) => entry.file(ok, ko));
        out.push({ file, path: entry.fullPath.replace(/^\/+/, "") || file.name });
        if (out.length % 50 === 0) { I.scan.found = out.length; drawProgress(); }
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        for (;;) {
          const batch = await new Promise((ok, ko) => reader.readEntries(ok, ko));
          if (!batch.length) break;
          for (const e of batch) await walk(e);
        }
      }
    } catch (e) { I.unreadable++; }
  };
  I.phase = "scan";
  I.scan = { done: 0, total: 0, found: 0 };
  render();
  for (const e of entries) await walk(e);
  return out;
}

function filesFromInput(input) {
  return [...input.files].map((file) => ({ file, path: file.webkitRelativePath || file.name }));
}

async function sha256(file) {
  if (!crypto?.subtle) return "";
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function addFiles(found) {
  if (!found.length) { if (!I.items.length) I.phase = "pick"; render(); return; }
  const known = new Set(live(I.items).map((x) => `${x.path}\u0000${x.size}`));
  const fresh = found.filter((f) => !known.has(`${f.path}\u0000${f.file.size}`))
    .map((f) => ({ id: I.nextId++, file: f.file, path: f.path, size: f.file.size, kind: extOf(f.path).slice(1) || "—",
      sha: "", status: "skip", reason: "", detail: "", removed: false }));
  I.items.push(...fresh);
  I.phase = "scan";
  I.scan = { done: 0, total: fresh.length, found: 0 };
  render();
  // Only documents that could be used need a fingerprint (to find copies).
  const queue = fresh.filter((x) => readable().has(extOf(x.path)) && x.size > 0 && x.size <= S.data.limits.max_file);
  I.scan.total = queue.length;
  const worker = async () => {
    for (let x = queue.shift(); x; x = queue.shift()) {
      try { x.sha = await sha256(x.file); } catch (e) { x.sha = ""; }
      I.scan.done++;
      if (I.scan.done % 20 === 0) drawProgress();
    }
  };
  await Promise.all(Array.from({ length: UPLOADERS }, worker));
  await replan();
}

async function replan() {
  const items = live(I.items);
  I.phase = "scan";
  I.scan.checking = true;
  drawProgress();
  try {
    const plan = await api("/api/intake/plan", { files: items.map((x) => ({ path: x.path, size: x.size, sha256: x.sha })) });
    plan.items.forEach((p, i) => Object.assign(items[i], { status: p.status, reason: p.reason, detail: p.detail, safe: p.path }));
    I.phase = items.length ? "ready" : "pick";
    I.error = "";
  } catch (e) {
    I.phase = "ready";
    I.error = e.message;
  }
  I.scan.checking = false;
  I.tab = live(I.items).some((x) => x.status === "use") ? I.tab : "skip";
  render();
}

function removeItem(x) {
  x.removed = true;
  replan();
}

// ── Upload and compare ──
async function compareIntake() {
  const todo = live(I.items).filter((x) => x.status === "use");
  if (!todo.length) return;
  I.phase = "upload";
  I.sent = 0;
  I.sentBytes = 0;
  I.failed = [];
  I.error = "";
  render();
  const started = await act(() => api("/api/intake/start", {}));
  if (!started) { I.phase = "ready"; render(); return; }
  I.batch = started.batch;
  await upload(todo);
  if (I.phase !== "upload") return; // cancelled
  if (I.failed.length) { I.phase = "partial"; render(); return; }
  await startCompare();
}

async function upload(list) {
  I.abort = new AbortController();
  const queue = [...list];
  const worker = async () => {
    for (let x = queue.shift(); x && I.phase === "upload"; x = queue.shift()) {
      const q = new URLSearchParams({ batch: I.batch, path: x.safe || x.path });
      try {
        const res = await fetch(`/api/intake/file?${q}`, { method: "POST", body: x.file, signal: I.abort.signal,
          headers: { "X-Amanuense-Token": TOKEN, "Content-Type": "application/octet-stream", "X-Content-SHA256": x.sha } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        x.upload = "done";
      } catch (e) {
        if (e.name === "AbortError") return;
        x.upload = "failed";
        x.error = e.message === "Failed to fetch" ? t("ui_server_gone") : e.message;
        I.failed.push(x);
      }
      I.sent++;
      I.sentBytes += x.size;
      drawProgress();
    }
  };
  await Promise.all(Array.from({ length: UPLOADERS }, worker));
}

async function retryFailed() {
  const again = I.failed;
  I.failed = [];
  I.phase = "upload";
  I.sent -= again.length;
  I.sentBytes -= again.reduce((s, x) => s + x.size, 0);
  render();
  await upload(again);
  if (I.phase !== "upload") return;
  if (I.failed.length) { I.phase = "partial"; render(); return; }
  await startCompare();
}

async function cancelUpload() {
  I.phase = "ready";
  I.abort?.abort();
  if (I.batch) await act(() => api("/api/intake/cancel", { batch: I.batch }), t("ui_in_cancelled"));
  I.batch = null;
  render();
}

async function startCompare() {
  I.phase = "compare";
  I.error = "";
  render();
  const job = await act(() => api("/api/job", { name: "intake", batch: I.batch }));
  if (!job) { I.phase = "failed"; I.error = t("ui_busy"); render(); return; }
  S.data.job = job;
  render();
  watchJob();
}

function intakeFinished(job) {
  if (job.error) { I.phase = "failed"; I.error = job.error; return; }
  I.phase = "done";
  I.result = job.result;
  // what was set aside before uploading counts with what the server set aside afterwards
  I.setAside = I.items.filter((x) => !x.removed && x.status !== "use").length;
  I.items = [];
}

// ── Drawing ──
function sourceText(src) {
  if (!src || !src.kind) return "";
  const stamp = when(src.created || src.fetched);
  if (src.kind === "live") return t("ui_in_source_live", { when: stamp });
  if (src.kind === "cache") return t("ui_in_source_cache", { when: stamp });
  if (src.kind === "export") return src.created ? t("ui_in_source_export", { when: stamp }) : t("ui_in_source_export_undated");
  return t("ui_in_source_none");
}

function plannedNote() {
  const p = S.data.planned_source;
  if (p.kind === "live") return h("p", { class: "note grey source-note" }, t("ui_in_will_live", { space: p.space }),
    p.root ? ` ${t("ui_in_root", { root: p.root })}` : "");
  if (p.kind === "export") return h("p", { class: "note grey source-note" },
    t("ui_in_will_export", { files: p.files.join(", "), when: when(p.created) || "?" }));
  return h("p", { class: "note amber source-note" }, t("ui_in_will_none", { dir: S.data.export_dir }),
    " ", h("button", { class: "small ghost", onclick: settingsDialog }, t("ui_settings")));
}

function intakeView() {
  const back = S.data.proposals.length || S.data.set_aside.length;
  return h("main", { class: "intake" },
    h("div", { class: "intake-head" },
      h("div", {}, h("h1", { tabindex: -1 }, t("ui_in_title")), h("p", { class: "muted" }, t("ui_in_lead"))),
      back ? h("button", { class: "ghost", onclick: () => { S.view = "review"; render(); } }, t("ui_in_back")) : null),
    { pick: pickPanel, scan: progressPanel, ready: listPanel, upload: progressPanel, partial: partialPanel,
      compare: progressPanel, failed: failedPanel, done: donePanel }[I.phase]());
}

function dropZone(compact = false) {
  const files = h("input", { type: "file", multiple: true, class: "offscreen", tabindex: -1, "aria-hidden": "true",
    onchange: (e) => { addFiles(filesFromInput(e.target)); e.target.value = ""; } });
  const folder = h("input", { type: "file", multiple: true, webkitdirectory: true, class: "offscreen", tabindex: -1,
    "aria-hidden": "true", onchange: (e) => { addFiles(filesFromInput(e.target)); e.target.value = ""; } });
  const formats = S.data.formats.join(" ");
  return h("section", { class: `drop${compact ? " compact" : ""}`, "aria-label": t("ui_in_drop") },
    h("div", { class: "drop-icon", "aria-hidden": "true" }),
    h("p", { class: "drop-title" }, t("ui_in_drop")),
    h("div", { class: "row center" },
      h("button", { class: compact ? "ghost" : "", onclick: () => files.click() }, t("ui_in_choose_files")),
      h("span", { class: "muted" }, t("ui_in_or")),
      h("button", { class: "ghost", onclick: () => folder.click() }, t("ui_in_choose_folder"))),
    compact ? null : h("p", { class: "muted small-print" },
      t("ui_in_formats", { formats, mb: Math.round(S.data.limits.max_file / 1048576) }), " ", t("ui_in_pdf_note")),
    files, folder);
}

function pickPanel() {
  const summary = S.data.intake;
  return h("div", { class: "intake-body" },
    I.error ? h("div", { class: "note red", role: "alert" }, I.error) : null,
    dropZone(),
    plannedNote(),
    summary?.unmatched_total ? candidatesCard(summary, 5) : null,
    S.data.proposals.length ? null : h("details", { class: "other-ways" },
      h("summary", {}, t("ui_in_other_ways")),
      h("ol", {}, h("li", {}, t("ui_empty_1")), h("li", {}, t("ui_empty_2")), h("li", {}, t("ui_empty_3"))),
      h("div", { class: "row" },
        h("button", { class: "ghost", onclick: () => act(() => api("/api/open", { what: "workspace" })) }, t("ui_open_workspace")),
        h("button", { class: "ghost", onclick: () => startJob("run"), disabled: S.data.job.running }, t("ui_run")))));
}

function bar(fraction, label) {
  const pct = Math.max(0, Math.min(100, Math.round(fraction * 100)));
  return h("div", { class: "bar big", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": pct, "aria-label": label },
    h("div", { style: `width:${pct}%` }));
}

function progressPanel() {
  let title, detail, fraction = null, cancel = null;
  if (I.phase === "scan") {
    if (I.scan.checking) title = t("ui_in_checking");
    else if (I.scan.total) { title = t("ui_in_reading", { done: fmtNum(I.scan.done), total: fmtNum(I.scan.total) }); fraction = I.scan.done / I.scan.total; }
    else title = t("ui_in_listing", { n: fmtNum(I.scan.found) });
  } else if (I.phase === "upload") {
    const todo = live(I.items).filter((x) => x.status === "use");
    const bytes = todo.reduce((s, x) => s + x.size, 0) || 1;
    title = t("ui_in_uploading", { done: fmtNum(I.sent), total: fmtNum(todo.length) });
    detail = t("ui_in_uploaded_bytes", { sent: fmtSize(I.sentBytes), size: fmtSize(bytes) });
    fraction = I.sentBytes / bytes;
    cancel = h("button", { class: "ghost", onclick: cancelUpload }, t("ui_cancel"));
  } else {
    const p = S.data.job.progress || {};
    title = t("ui_in_comparing");
    detail = p.stage ? t(`ui_stage_${p.stage}`, { done: fmtNum(p.done + 1 > p.total ? p.total : p.done + 1), total: fmtNum(p.total) }) : "";
    fraction = p.stage === "write" && p.total ? p.done / p.total : p.stage === "log" ? 1 : null;
  }
  return h("div", { class: "intake-body" },
    h("section", { class: "card progress-card", "aria-live": "polite", "aria-busy": "true" },
      h("p", { class: "progress-title" }, h("span", { class: "spin" }), title),
      fraction == null ? h("div", { class: "bar big indeterminate", role: "progressbar", "aria-label": title }, h("div", {})) : bar(fraction, title),
      detail ? h("p", { class: "muted" }, detail) : null,
      cancel ? h("div", { class: "row end" }, cancel) : null));
}

// The progress card redraws alone, so a big list is not rebuilt for every file.
function drawProgress() {
  const card = $(".progress-card");
  if (card && ["scan", "upload", "compare"].includes(I.phase)) card.replaceWith(progressPanel().firstChild);
  else if (S.view === "intake" && ["scan", "upload", "compare"].includes(I.phase)) render();
}

function reasonText(x) {
  const label = t(`ui_reason_${x.reason}`);
  if (x.reason === "duplicate" || x.reason === "known") return `${label} · ${t("ui_in_same_as", { path: x.detail })}`;
  if (x.reason === "noise" && x.detail) return `${label} · ${t("ui_in_matches", { pattern: x.detail })}`;
  return label;
}

function listPanel() {
  const items = live(I.items);
  const used = items.filter((x) => x.status === "use");
  const skipped = items.filter((x) => x.status !== "use");
  const usedBytes = used.reduce((s, x) => s + x.size, 0);
  const kinds = {};
  items.forEach((x) => { kinds[x.kind] = kinds[x.kind] || { all: 0, used: 0 }; kinds[x.kind].all++; if (x.status === "use") kinds[x.kind].used++; });
  const reasons = {};
  skipped.forEach((x) => (reasons[x.reason] = (reasons[x.reason] || 0) + 1));
  const shown = (I.tab === "use" ? used : skipped)
    .filter((x) => !I.query || x.path.toLowerCase().includes(I.query.toLowerCase()));
  return h("div", { class: "intake-body" },
    I.error ? h("div", { class: "note red", role: "alert" }, I.error) : null,
    I.unreadable ? h("div", { class: "note amber" }, t("ui_in_unreadable", { n: I.unreadable })) : null,
    h("div", { class: "tiles" },
      tile(t("ui_in_files"), fmtNum(items.length), fmtSize(items.reduce((s, x) => s + x.size, 0))),
      tile(t("ui_in_used"), fmtNum(used.length), fmtSize(usedBytes), "green"),
      tile(t("ui_in_skipped"), fmtNum(skipped.length), Object.entries(reasons).map(([r, n]) => `${t(`ui_reason_${r}`)} ${fmtNum(n)}`).join(" · "), skipped.length ? "amber" : "")),
    h("div", { class: "kinds", "aria-label": t("ui_in_types") },
      h("span", { class: "muted" }, t("ui_in_types")),
      Object.entries(kinds).sort((a, b) => b[1].all - a[1].all).map(([k, n]) =>
        h("span", { class: `chip${n.used ? "" : " off"}`, title: t("ui_in_kind_help", { used: n.used, all: n.all }) }, `${k} ${fmtNum(n.all)}`))),
    plannedNote(),
    h("section", { class: "card list-card" },
      h("div", { class: "list-tools" },
        h("div", { class: "tabs", role: "tablist" },
          [["use", t("ui_in_tab_used", { n: fmtNum(used.length) })], ["skip", t("ui_in_tab_skipped", { n: fmtNum(skipped.length) })]].map(([k, label]) =>
            h("button", { role: "tab", "aria-selected": I.tab === k, class: I.tab === k ? "tab on" : "tab", onclick: () => { I.tab = k; I.shown = LIST_STEP; render(); } }, label))),
        h("input", { type: "search", placeholder: t("ui_in_filter"), "aria-label": t("ui_in_filter"), value: I.query,
          oninput: (e) => { I.query = e.target.value; I.shown = LIST_STEP; redrawList(); } })),
      h("div", { class: "file-list-holder" }, fileList(shown))),
    I.tab === "skip" ? h("p", { class: "muted" }, t("ui_in_ignore_hint", { file: S.data.ignore_file })) : null,
    dropZone(true),
    h("footer", { class: "actions intake-actions" },
      h("button", { class: "ghost", onclick: () => { resetIntake(); render(); } }, t("ui_in_clear")),
      h("div", { class: "grow" }),
      used.length ? h("span", { class: "muted" }, t("ui_in_ready_n", { n: fmtNum(used.length), size: fmtSize(usedBytes) })) : h("span", { class: "muted" }, t("ui_in_nothing_to_use")),
      h("button", { class: "primary", disabled: !used.length || S.data.job.running, onclick: compareIntake }, t("ui_in_compare"))));
}

function tile(label, value, sub, tone = "") {
  return h("div", { class: `tile ${tone}` }, h("span", { class: "tile-label" }, label), h("b", {}, value), sub ? h("small", { class: "muted" }, sub) : null);
}

function fileList(shown) {
  if (!shown.length) return h("p", { class: "muted pad" }, t("ui_none_here"));
  return h("div", {},
    h("ul", { class: "file-list" }, shown.slice(0, I.shown).map((x) =>
      h("li", { class: x.status === "use" ? "" : "skipped" },
        h("span", { class: "kind" }, x.kind),
        h("span", { class: "path", title: x.path }, x.path),
        h("span", { class: "muted size" }, fmtSize(x.size)),
        x.status === "use" ? null : h("span", { class: `badge ${x.reason === "duplicate" || x.reason === "known" ? "grey" : "amber"} why` }, reasonText(x)),
        h("button", { class: "small ghost remove", "aria-label": t("ui_in_remove_one", { path: x.path }), title: t("ui_in_remove"), onclick: () => removeItem(x) }, "✕")))),
    shown.length > I.shown ? h("button", { class: "ghost more", onclick: () => { I.shown = shown.length; redrawList(); } },
      t("ui_in_show_all", { n: fmtNum(shown.length - I.shown) })) : null);
}

function redrawList() {
  const items = live(I.items).filter((x) => (I.tab === "use" ? x.status === "use" : x.status !== "use"))
    .filter((x) => !I.query || x.path.toLowerCase().includes(I.query.toLowerCase()));
  $(".file-list-holder")?.replaceChildren(fileList(items));
}

function partialPanel() {
  return h("div", { class: "intake-body" },
    h("section", { class: "card" },
      h("div", { class: "note red", role: "alert" }, h("b", {}, t("ui_in_failed_n", { n: I.failed.length })),
        h("ul", {}, I.failed.slice(0, 20).map((x) => h("li", {}, h("code", {}, x.path), " — ", x.error)))),
      h("div", { class: "row end" },
        h("button", { class: "ghost", onclick: cancelUpload }, t("ui_cancel")),
        h("button", { class: "ghost", onclick: retryFailed }, t("ui_in_retry")),
        h("button", { class: "primary", onclick: startCompare }, t("ui_in_continue")))));
}

function failedPanel() {
  return h("div", { class: "intake-body" },
    h("section", { class: "card" },
      h("div", { class: "note red", role: "alert" }, t("ui_job_failed", { error: I.error })),
      h("div", { class: "row end" },
        h("button", { class: "ghost", onclick: () => { resetIntake(); render(); } }, t("ui_in_clear")),
        I.batch ? h("button", { class: "primary", onclick: startCompare }, t("ui_in_compare_again")) : null)));
}

function donePanel() {
  const r = I.result || {};
  const b = r.batch || {};
  const src = r.source || {};
  const summary = S.data.intake || {};
  const noAi = !(S.data.settings.ai_cli || S.data.settings.ai_url);
  return h("div", { class: "intake-body" },
    h("section", { class: "card done" },
      h("h2", { tabindex: -1 }, t("ui_in_done_title")),
      h("p", { class: "muted" }, t("ui_in_compared_with", { source: sourceText(src), n: fmtNum(src.count || 0) })),
      src.warning ? h("div", { class: "note amber" }, src.warning) : null,
      h("div", { class: "tiles" },
        tile(t("ui_in_updates"), fmtNum(b.updates || 0), t("ui_in_updates_help", { ready: fmtNum(r.ready || 0), n: fmtNum(r.tasks || 0) }), "green"),
        tile(t("ui_in_identical"), fmtNum(b.identical || 0), t("ui_in_identical_help")),
        tile(t("ui_in_unmatched"), fmtNum(b.unmatched || 0), t("ui_in_unmatched_help"), b.unmatched ? "amber" : ""),
        tile(t("ui_in_skipped"), fmtNum((b.skipped || 0) + (I.setAside || 0)), t("ui_in_skipped_help"))),
      noAi && r.tasks ? h("div", { class: "note amber" }, t("ui_in_no_ai"), " ",
        h("button", { class: "small ghost", onclick: settingsDialog }, t("ui_settings"))) : null,
      r.warnings?.length ? h("details", {}, h("summary", {}, t("ui_run_warnings")), h("ul", {}, r.warnings.map((w) => h("li", {}, w)))) : null,
      h("div", { class: "row end" },
        h("button", { class: "ghost", onclick: () => { resetIntake(); render(); } }, t("ui_in_add_another")),
        S.data.proposals.length ? h("button", { class: "primary", onclick: () => { S.view = "review"; resetIntake(); render(); } }, t("ui_in_go_review")) : null)),
    summary.unmatched_total ? candidatesCard(summary, 10) : null);
}

function candidatesCard(summary, first) {
  const list = summary.unmatched;
  const open = I.allCandidates ? list : list.slice(0, first);
  const rest = summary.unmatched_total - open.length;
  return h("section", { class: "card candidates" },
    h("h2", {}, t("ui_in_candidates", { n: fmtNum(summary.unmatched_total) })),
    h("p", { class: "muted" }, t("ui_in_candidates_help")),
    h("ol", { class: "cand-list" }, open.map((c) => h("li", {},
      h("div", { class: "cand-text" }, h("b", {}, c.title), h("small", { class: "muted" }, `${c.rel} · ${t("ui_in_words", { n: fmtNum(c.words) })}`)),
      h("button", { class: "small ghost", disabled: S.data.job.running, onclick: async () => {
        if (await act(() => api("/api/intake/promote", { rel: c.rel }), t("ui_in_promoted"))) await load();
      } }, t("ui_in_promote"))))),
    rest > 0 && list.length > open.length ? h("button", { class: "ghost more", onclick: () => { I.allCandidates = true; render(); } }, t("ui_in_show_all", { n: fmtNum(list.length - open.length) })) : null,
    rest > 0 && list.length <= open.length ? h("p", { class: "muted" }, t("ui_in_more_in_report", { n: fmtNum(rest) })) : null,
    summary.promoted?.length ? h("div", { class: "row" }, h("span", { class: "muted" }, t("ui_in_promoted_n", { n: summary.promoted.length })),
      h("button", { class: "small", disabled: S.data.job.running, onclick: () => (I.batch ? startCompare() : startJob("run")) },
        t("ui_in_compare_again"))) : null);
}

function candidatesAside() {
  const summary = S.data.intake;
  if (!summary?.unmatched_total) return null;
  return h("details", { class: "aside" },
    h("summary", {}, t("ui_in_candidates", { n: fmtNum(summary.unmatched_total) })),
    h("p", { class: "muted" }, t("ui_in_candidates_help")),
    h("button", { class: "small ghost", onclick: openIntake }, t("ui_in_see_candidates")));
}

// Dropping files anywhere opens the intake with them; the browser never navigates to a file.
let dragDepth = 0;
document.addEventListener("dragenter", (e) => {
  if (!S.data || ![...(e.dataTransfer?.types || [])].includes("Files")) return;
  dragDepth++;
  if (!$("#drop-overlay")) document.body.append(h("div", { id: "drop-overlay", "aria-hidden": "true" }, h("p", {}, t("ui_in_drop_here"))));
  document.body.classList.add("dragging");
});
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
document.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) e.preventDefault(); });
document.addEventListener("drop", (e) => {
  if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  if (!S.data || !["pick", "ready", "done", "failed"].includes(I.phase)) return;
  if (I.phase === "done" || I.phase === "failed") resetIntake();
  S.view = "intake";
  const pending = filesFromDrop(e.dataTransfer); // takes the entries now, walks them after
  pending.then(addFiles);
});

// ── Settings ──
function settingsDialog() {
  const s = S.data.settings;
  const f = (name, label, attrs = {}) => h("label", {}, label, h("input", { name, value: s[name] || "", ...attrs }));
  const engine = h("select", { name: "ai_cli" }, h("option", { value: "" }, t("ui_ai_none")),
    S.data.engines.map((e) => h("option", { value: e, selected: s.ai_cli === e }, e)));
  const result = h("p", { class: "muted", "aria-live": "polite" });
  const form = h("form", { class: "settings", onsubmit: (e) => e.preventDefault() },
    h("h3", {}, t("ui_mind")),
    h("p", { class: "muted" }, t("ui_mind_help")),
    f("url", t("ui_mind_url"), { type: "url", placeholder: "https://mind.example.org" }),
    f("space", t("ui_mind_space"), { placeholder: "DOCS" }),
    f("root_page", t("ui_mind_root"), { placeholder: t("ui_mind_root_ph") }),
    h("label", {}, t("ui_mind_token"), h("input", { name: "token", type: "password", autocomplete: "off",
      placeholder: s.has_token ? t("ui_token_saved") : t("ui_token_ph") })),
    h("p", { class: "muted" }, t("ui_token_help")),
    f("user", t("ui_mind_user"), { placeholder: t("ui_mind_user_ph") }),
    h("div", { class: "row" },
      h("button", { type: "button", class: "ghost", onclick: async () => {
        await save();
        result.textContent = t("ui_testing");
        try { result.textContent = t("ui_test_ok", { user: (await api("/api/settings/test", {})).user }); }
        catch (e) { result.textContent = e.message; }
      } }, t("ui_test")),
      s.has_token ? h("button", { type: "button", class: "ghost", onclick: async () => {
        const out = await act(() => api("/api/settings/forget", {}), t("ui_token_forgotten"));
        if (out) { S.data.settings = out; closeModal(); settingsDialog(); }
      } }, t("ui_forget_token")) : null),
    result,
    h("h3", {}, t("ui_ai")),
    h("p", { class: "muted" }, t("ui_ai_settings_help")),
    h("label", {}, t("ui_ai_cli"), engine),
    f("ai_url", t("ui_ai_url"), { placeholder: "http://localhost:11434/v1" }),
    f("ai_model", t("ui_ai_model")),
    s.from_env.length ? h("p", { class: "note amber" }, t("ui_from_env", { fields: s.from_env.join(", ") })) : null);
  async function save() {
    const values = Object.fromEntries(new FormData(form).entries());
    const out = await act(() => api("/api/settings", values));
    if (out) S.data.settings = out;
    return out;
  }
  modal(t("ui_settings"), form, null, [[t("ui_save"), async () => { if (await save()) { toast(t("ui_saved")); render(); } }]]);
}

// ── Modal ──
function modal(title, a, b, buttons, wide = false) {
  closeModal();
  const dlg = h("dialog", { class: wide ? "wide" : "", "aria-label": title, onclose: () => dlg.remove() },
    h("div", { class: "dlg-head" }, h("h2", {}, title), h("button", { class: "ghost", "aria-label": t("ui_cancel"), onclick: closeModal }, "✕")),
    a, b,
    buttons.length ? h("div", { class: "row end" },
      h("button", { class: "ghost", onclick: closeModal }, t("ui_cancel")),
      buttons.map(([label, fn]) => h("button", { class: "primary", onclick: async () => { if ((await fn()) !== false) closeModal(); } }, label))) : null);
  document.body.append(dlg);
  dlg.showModal();
}
function closeModal() {
  const d = document.querySelector("dialog[open]");
  if (d) d.close();
}

async function closeApp() {
  await act(() => api("/api/shutdown", {}));
  document.body.replaceChildren(h("main", { class: "empty" }, h("h1", {}, t("ui_closed")), h("p", {}, t("ui_closed_help"))));
}

// ── Keys: j / k move between pages, ? shows them ──
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea, select, dialog") || e.metaKey || e.ctrlKey || e.altKey || S.view === "intake") return;
  const list = S.data?.proposals.filter(FILTERS[S.filter]) || [];
  const i = list.findIndex((p) => p.rel === S.rel);
  if (e.key === "j" && list[i + 1]) openPage(list[i + 1].rel);
  if (e.key === "k" && i > 0) openPage(list[i - 1].rel);
});

document.body.append(h("div", { id: "toasts", "aria-live": "polite" }));
if (!TOKEN) document.getElementById("app").textContent =
  "Abre amanuense desde su lanzador (amanuense.bat). · Open amanuense from its launcher.";
else load();

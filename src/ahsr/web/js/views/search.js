import { api, ApiError } from "../api.js";
import { copyText, fmtMs, h, icon, mount, plural, debounce } from "../dom.js";
import { renderMarkdown } from "../mdrender.js";
import { buildHash, navigate } from "../router.js";
import { history, prefs } from "../state.js";
import { queryTerms } from "../terms.js";
import { createBalance } from "../ui/balance.js";
import { announce, emptyState, errorBlock, notice, skeleton, toast } from "../ui/feedback.js";
import { passageRow } from "../ui/passage.js";
import { createSources } from "../ui/sources.js";
import { createWorklog } from "../ui/worklog.js";

const KIND = { identifier: ["Exact", "e"], concept: ["Plain language", "m"], multi: ["Two questions in one", "both"] };
const MODES = { ask: { label: "Ask", placeholder: "Ask a question or paste an error code", hint: "Get an answer with sources" },
  search: { label: "Search", placeholder: "Search the docs", hint: "Show matching passages" } };

export function SearchView(ctx) {
  let mode = prefs.mode, runId = 0, abort = null, routeSeq = 0, suggestionsCache = null;

  const input = h("textarea", { class: "q-input", rows: 1, "aria-label": "Question or search", spellcheck: "false", autocomplete: "off", autocapitalize: "off" });
  const goBtn = h("button", { type: "submit", class: "btn primary go" });
  const modeBtns = Object.entries(MODES).map(([key, m]) => h("button", { type: "button", role: "radio", class: "seg-btn", title: m.hint, dataset: { mode: key },
    onclick: () => setMode(key), onkeydown: (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { setMode(mode === "ask" ? "search" : "ask"); modeBtns.find((b) => b.dataset.mode === mode).focus(); } } }, icon(key === "ask" ? "ask" : "search", 15), m.label));
  const balance = createBalance();
  const intro = h("div", { class: "intro" }, h("h1", {}, "Ask the docs"),
    h("p", {}, "Paste an error code or describe the problem. Two engines search side by side: one matches meaning, the other matches exact text."));
  const stage = h("div", { class: "stage" });

  const form = h("form", { class: "finder", role: "search", onsubmit: (e) => { e.preventDefault(); submit(); } },
    h("div", { class: "finder-box" }, h("div", { class: "finder-top" }, input), h("div", { class: "finder-bar" }, h("div", { class: "seg", role: "radiogroup", "aria-label": "What to do" }, modeBtns), h("span", { class: "kbd-hint" }, h("kbd", {}, "Enter"), " to run, ", h("kbd", {}, "Shift"), "+", h("kbd", {}, "Enter"), " for a new line"), goBtn)),
    balance.el);
  const el = h("section", { class: "view view-search" }, intro, form, stage);

  // ---- finder behaviour ----------------------------------------------------------------------
  function setMode(m) {
    mode = m; prefs.mode = m;
    modeBtns.forEach((b) => { const on = b.dataset.mode === m; b.setAttribute("aria-checked", String(on)); b.tabIndex = on ? 0 : -1; b.classList.toggle("on", on); });
    goBtn.replaceChildren(icon(m === "ask" ? "ask" : "search", 16), MODES[m].label);
    input.placeholder = MODES[m].placeholder;
  }
  const autosize = () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 168)}px`; };
  const liveRoute = debounce(async () => {
    const q = input.value.trim(), seq = ++routeSeq;
    if (q.length < 2) return balance.idle();
    try { const r = await api.route(q); if (seq === routeSeq) balance.set(r); } catch { /* the readout is a nicety; never nag */ }
  }, 160);
  input.addEventListener("input", () => { autosize(); liveRoute(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (e.metaKey || e.ctrlKey) setMode(mode === "ask" ? "search" : "ask"); submit(); }
    else if (e.key === "Escape") input.blur();
  });

  function submit(q = input.value.trim(), m = mode) {
    if (!q) { input.focus(); return; }
    if (q.length > ctx.health().max_query_chars) { toast(`That’s longer than the ${ctx.health().max_query_chars}-character limit.`, { kind: "error" }); return; }
    setMode(m);
    navigate(buildHash("search", { params: { q, mode: m, view: m === "search" && stage.dataset.view === "compare" ? "compare" : "" } }));
  }

  // ---- route entry ---------------------------------------------------------------------------
  function show(params) {
    const m = params.mode === "ask" || params.mode === "search" ? params.mode : prefs.mode;
    setMode(m);
    const q = (params.q || "").trim();
    input.value = q; autosize(); liveRoute.cancel();
    el.dataset.hasQuery = q ? "true" : "false";
    stage.dataset.view = params.view === "compare" ? "compare" : "fused";
    if (!q) { cancel(); balance.idle(); home(); input.focus(); document.title = `${ctx.health().app_name || "Hybrid Search"}`; return; }
    history.add(q, m);
    document.title = `${q} · ${ctx.health().app_name || "Hybrid Search"}`;
    m === "ask" ? runAsk(q) : runSearch(q);
    api.route(q).then((r) => { if (input.value.trim() === q) balance.set(r); }).catch(() => {});
  }
  function cancel() { abort?.abort(); abort = null; runId++; }

  // ---- home ----------------------------------------------------------------------------------
  function suggestionList(items) {
    return h("ul", { class: "suggest-list" }, items.map((s) => {
      const [label, tone] = KIND[s.kind] || ["Try", "m"];
      return h("li", {}, h("button", { type: "button", class: "suggest", onclick: () => submit(s.query, mode) },
        h("span", { class: `tag ${tone}` }, label), h("span", { class: "suggest-q" }, s.query)));
    }));
  }

  function home() {
    const health = ctx.health();
    const blocks = [];
    if (health.chunks === 0) {
      blocks.push(emptyState({ title: "There’s nothing to search yet", body: "Add some Markdown documents and they’ll be indexed straight away.",
        actions: [h("a", { class: "btn primary", href: "#/library" }, icon("plus", 16), "Add documents")] }));
    } else {
      const slot = h("div", { class: "home-block" });
      const paint = (items) => { slot.replaceChildren(items.length ? h("h2", { class: "block-title" }, "Try one of these") : null, items.length ? suggestionList(items) : null); };
      if (suggestionsCache) paint(suggestionsCache);
      api.suggestions().then((r) => { suggestionsCache = r.suggestions; paint(suggestionsCache); }).catch(() => {});
      blocks.push(slot);
    }
    const recent = history.all();
    if (recent.length) {
      blocks.push(h("div", { class: "home-block" },
        h("div", { class: "block-head" }, h("h2", { class: "block-title" }, "Recent"), h("button", { type: "button", class: "link-btn", onclick: () => { history.clear(); home(); } }, "Clear")),
        h("ul", { class: "recent-list" }, recent.map((r) => h("li", {}, h("button", { type: "button", class: "recent", onclick: () => submit(r.q, r.mode) }, icon(r.mode === "ask" ? "ask" : "search", 14), h("span", {}, r.q)))))));
    }
    mount(stage, h("div", { class: "home" }, blocks));
  }

  // ---- ask -----------------------------------------------------------------------------------
  async function runAsk(q) {
    cancel();
    const id = runId, ctl = (abort = new AbortController());
    const terms = queryTerms(q), worklog = createWorklog(), sources = createSources(terms);
    const body = h("div", { class: "answer-body" }, skeleton(4));
    sources.el.hidden = true;
    mount(stage, h("div", { class: "ask-grid" }, h("article", { class: "answer" }, h("h2", { class: "question" }, q), worklog.el, body), sources.el));
    worklog.start();
    const live = (fn) => (d) => { if (id === runId) fn(d); };
    const fail = (message) => { worklog.fail(); body.replaceChildren(errorBlock({ title: "Couldn’t finish this answer", message, onRetry: () => runAsk(q) })); announce("The answer could not be completed."); };

    try {
      await api.askStream(q, {
        decompose: live(worklog.decompose),
        research: live(worklog.research),
        synthesize: live((f) => { worklog.synthesize(f); sources.set(f.citations); renderAnswer(body, q, f, sources); announce(`Answer ready with ${plural(f.citations.length, "source")}.`); }),
        error: live((e) => fail(e.message || "The agent stopped unexpectedly.")),
      }, ctl.signal);
    } catch (e) { if (id === runId) fail(e instanceof ApiError ? e.friendly : "Something unexpected happened."); }
  }

  function renderAnswer(body, q, f, sources) {
    const statuses = f.research.map((r) => r.status);
    const parts = [];
    if (statuses.every((s) => s === "none")) parts.push(notice("warn", "Nothing relevant found", "Try different words, or add the missing documentation to the Library."));
    else if (statuses.includes("weak")) parts.push(notice("warn", "Some of this is unconfirmed", "For part of the question nothing was confirmed as relevant, so the closest matches are shown and marked as unconfirmed."));
    parts.push(renderMarkdown(f.answer, { cite: sources.cite }));
    const claude = f.llm_mode === "claude";
    const copy = h("button", { type: "button", class: "btn sm", onclick: async () => { toast((await copyText(f.answer)) ? "Answer copied" : "Couldn’t copy", { kind: "ok", timeout: 1800 }); } }, icon("copy", 14), "Copy answer");
    parts.push(h("div", { class: "answer-foot" },
      h("span", { class: `chip ${claude ? "" : "muted"}`, title: claude ? "Written by Claude from the sources listed." : "No language model is configured, so this is assembled from the best passages rather than written." }, claude ? "Written by Claude" : "Quoted from sources"),
      h("span", { class: "foot-meta" }, fmtMs(f.took_ms)), h("span", { class: "grow" }), copy,
      h("button", { type: "button", class: "btn sm", onclick: () => submit(q, "search") }, icon("search", 14), "See the passages")));
    body.replaceChildren(...parts);
  }

  // ---- search --------------------------------------------------------------------------------
  async function runSearch(q) {
    cancel();
    const id = runId, ctl = (abort = new AbortController()), compare = stage.dataset.view === "compare", terms = queryTerms(q);
    mount(stage, h("div", { class: "results" }, skeleton(5)));
    try {
      const [fused, dense, sparse] = await Promise.all([
        api.search(q, "hybrid", compare ? 5 : 6, { signal: ctl.signal }),
        compare ? api.search(q, "dense", 5, { signal: ctl.signal }) : null,
        compare ? api.search(q, "sparse", 5, { signal: ctl.signal }) : null]);
      if (id !== runId) return;
      balance.set(fused.route);
      mount(stage, h("div", { class: "results" }, resultsHead(q, fused, compare), fused.hits.length === 0
        ? emptyState({ title: "No passages matched", body: "Try different words, or add the missing documentation in the Library.", actions: [h("a", { class: "btn", href: "#/library" }, "Open library")] })
        : compare ? compareGrid(fused, dense, sparse, terms) : h("ol", { class: "passages" }, fused.hits.map((hit, i) => passageRow(hit, i, terms)))));
      announce(`${plural(fused.hits.length, "passage")} found.`);
    } catch (e) {
      if (id !== runId || ctl.signal.aborted) return;
      mount(stage, errorBlock({ title: "Search didn’t work", message: e instanceof ApiError ? e.friendly : "Something unexpected happened.", onRetry: () => runSearch(q) }));
    }
  }

  function resultsHead(q, res, compare) {
    const toggle = (view, label, ic) => h("button", { type: "button", role: "radio", "aria-checked": String((view === "compare") === compare), class: `seg-btn${(view === "compare") === compare ? " on" : ""}`,
      onclick: () => navigate(buildHash("search", { params: { q, mode: "search", view: view === "compare" ? "compare" : "" } })) }, icon(ic, 15), label);
    return h("div", { class: "results-head" },
      h("p", { class: "results-meta" }, h("strong", {}, q.length > 60 ? q.slice(0, 59) + "…" : q), ` · ${plural(res.hits.length, "passage")} in ${fmtMs(res.took_ms)}`),
      h("div", { class: "seg", role: "radiogroup", "aria-label": "Layout" }, toggle("fused", "Ranked", "list"), toggle("compare", "Side by side", "columns")));
  }

  function compareGrid(fused, dense, sparse, terms) {
    const col = (title, sub, tone, res) => h("section", { class: `col ${tone}` }, h("header", { class: "col-head" }, h("h3", {}, title), h("p", {}, sub)),
      res.hits.length ? h("ol", { class: "passages" }, res.hits.map((hit, i) => passageRow(hit, i, terms, { compact: true }))) : h("p", { class: "col-empty" }, "No matches from this engine."));
    const grid = h("div", { class: "compare" },
      col("Meaning only", "Finds passages about the same idea", "m", dense),
      col("Exact only", "Finds passages containing the same terms", "e", sparse),
      col("Fused", `Both, weighted ${fused.route.dense_weight.toFixed(1)} : ${fused.route.sparse_weight.toFixed(1)}`, "f", fused));
    grid.addEventListener("mouseover", (e) => { const li = e.target.closest?.(".passage"); grid.querySelectorAll(".passage.linked").forEach((n) => n.classList.remove("linked")); if (li) grid.querySelectorAll(`.passage[data-id="${li.dataset.id}"]`).forEach((n) => n.classList.add("linked")); });
    grid.addEventListener("mouseleave", () => grid.querySelectorAll(".passage.linked").forEach((n) => n.classList.remove("linked")));
    return h("div", { class: "compare-wrap" }, h("p", { class: "compare-note" }, "The same passage is linked across columns when you hover it. Fusion rewards passages both engines agree on."), grid);
  }

  setMode(mode); balance.idle();
  return { el, show, hide: cancel, focus: () => { input.focus(); input.select(); } };
}

import { api, ApiError } from "../api.js";
import { fmtMs, h, icon, mount, plural } from "../dom.js";
import { emptyState, errorBlock, notice, skeleton } from "../ui/feedback.js";

const MODES = [["dense", "Meaning only", "m"], ["sparse", "Exact only", "e"], ["hybrid_flat", "Fused, equal weights", "f"], ["hybrid", "Fused, routed", "r"]];
const TYPES = [["identifier", "Exact identifiers"], ["concept", "Plain language"], ["multi", "Multi-part"], ["overall", "Overall"]];
const f2 = (x) => x.toFixed(2);
let last = null;                                                  // keep the latest run while navigating around

export function EvaluateView(ctx) {
  let running = false, onlyMisses = false;
  const body = h("div", { class: "eval-body" });
  const runBtn = h("button", { type: "button", class: "btn primary", onclick: run });
  const kSel = h("select", { class: "field sm", "aria-label": "Top results to consider", onchange: () => {} },
    [3, 5, 10].map((k) => h("option", { value: k, selected: k === 5 }, `Top ${k}`)));
  const el = h("section", { class: "view view-eval" },
    h("header", { class: "view-head" }, h("div", {}, h("h1", {}, "Evaluate retrieval"),
      h("p", { class: "lede" }, "Run the labelled test queries against each engine, and against both fused. This shows what routing buys you.")),
      h("div", { class: "head-actions" }, kSel, runBtn)), body);

  function setRunning(v) { running = v; runBtn.disabled = v; runBtn.replaceChildren(icon(v ? "refresh" : "chart", 16, v ? "spin" : ""), v ? "Running…" : last ? "Run again" : "Run evaluation"); }

  async function run() {
    if (running) return;
    setRunning(true); mount(body, skeleton(6));
    try { last = await api.evaluate(Number(kSel.value)); paint(); }
    catch (e) { mount(body, e instanceof ApiError && e.code === "eval_set_missing"
      ? emptyState({ title: "No evaluation set found", body: "Add labelled queries to data/eval/queries.jsonl (or set EVAL_FILE) and run again." })
      : errorBlock({ title: "The evaluation didn’t run", message: e instanceof ApiError ? e.friendly : "Unexpected error.", onRetry: run })); }
    setRunning(false);
  }

  function paint() {
    const { modes, queries, k } = last;
    setRunning(false);
    const types = TYPES.filter(([t]) => modes.hybrid[t]);
    const matrix = h("div", { class: "table-wrap", tabindex: "0" }, h("table", { class: "matrix" },
      h("caption", {}, `Mean reciprocal rank (bar) and recall at ${k}, by type of query`),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Method"), types.map(([t, label]) => h("th", { scope: "col" }, label, h("span", { class: "th-n" }, `${plural(modes.hybrid[t].n, "query", "queries")}`))))),
      h("tbody", {}, MODES.map(([key, label, tone]) => h("tr", { class: key === "hybrid" ? "ours" : "" }, h("th", { scope: "row" }, h("span", { class: `swatch ${tone}` }), label),
        types.map(([t]) => { const c = modes[key][t]; return h("td", {}, h("div", { class: `mrr ${tone}` }, h("i", { style: { width: `${Math.max(2, c.mrr * 100)}%` } })), h("span", { class: "mrr-v" }, f2(c.mrr)), h("span", { class: "rec-v" }, `R@${k} ${f2(c.recall)}`)); }))))));

    const best = Math.max(modes.dense.overall.mrr, modes.sparse.overall.mrr), routed = modes.hybrid.overall.mrr;
    const insight = routed >= best - 1e-9
      ? `Routed fusion reaches ${f2(routed)} MRR overall${routed > best + 1e-9 ? `, ahead of the better single engine (${f2(best)})` : ", matching the better single engine"}. It doesn’t have to be told which kind of query it’s facing.`
      : `Routed fusion scored ${f2(routed)} MRR overall; the better single engine scored ${f2(best)}. Check the misses below.`;

    const rows = queries.filter((q) => !onlyMisses || MODES.some(([m]) => q.modes[m].rank !== 1));
    const cell = (c) => c.rank === null ? h("span", { class: "rank miss" }, "miss") : h("span", { class: `rank ${c.rank === 1 ? "top" : "low"}` }, `#${c.rank}`);
    mount(body,
      last.demo_mode ? notice("warn", "These numbers aren’t representative", "The offline stand-in encoders are active, so this only proves the pipeline works. Switch to the real models to judge quality.") : null,
      h("p", { class: "insight" }, insight), matrix,
      h("p", { class: "meta-line" }, `${plural(last.n, "query", "queries")} · top ${k} · ${fmtMs(last.took_ms)}. MRR rewards putting the right document first; recall asks whether it appeared at all.`),
      h("div", { class: "block-head spaced" }, h("h2", { class: "block-title" }, "Query by query"),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: onlyMisses, onchange: (e) => { onlyMisses = e.target.checked; paint(); } }), "Only queries where a method didn’t rank the right document first")),
      rows.length ? h("div", { class: "table-wrap", tabindex: "0" }, h("table", { class: "queries" },
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Query"), MODES.map(([, label]) => h("th", { scope: "col" }, label)))),
        h("tbody", {}, rows.map((q) => h("tr", {}, h("th", { scope: "row" }, h("span", { class: "q-text" }, q.query), h("span", { class: "q-type" }, q.type), h("span", { class: "q-want" }, `expects ${q.relevant.join(", ")}`)),
          MODES.map(([m]) => h("td", {}, cell(q.modes[m]))))))))
        : h("p", { class: "meta-line" }, "Every method ranked the right document first for every query."));
  }

  return {
    el,
    show() {
      document.title = `Evaluate · ${ctx.health().app_name || "Hybrid Search"}`;
      setRunning(false);
      if (last) paint();
      else mount(body, emptyState({ title: "No results yet", body: "Evaluation runs every test query through every method. It takes a few seconds." }));
    },
    hide() {},
  };
}

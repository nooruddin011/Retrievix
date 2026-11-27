// Live "how the agent is working" timeline, fed by the SSE events from /ask/stream.
import { fmtMs, h, icon, plural } from "../dom.js";

const STATUS = {
  docs: ["ok", "Answered from the docs"],
  tools: ["info", "Not in the docs; found in code or issues"],
  weak: ["warn", "Nothing confirmed; showing closest matches"],
  none: ["miss", "Nothing found"],
};
const LEAN = { identifier: "exact-leaning", conceptual: "meaning-leaning", mixed: "balanced" };

function stepLine(s) {
  if (s.kind === "retrieve") return [`Searched${s.attempt > 1 ? ` again (try ${s.attempt})` : ""}`, `${plural(s.hits, "passage")}, ${LEAN[s.route] || s.route}`, "search"];
  if (s.kind === "grade") return [`Checked relevance`, `${s.relevant} of ${s.total} judged relevant`, s.relevant ? "ok" : "miss"];
  if (s.kind === "rewrite") return ["Rewrote the query", `“${s.query}”`, "rewrite"];
  if (s.kind === "tools") return [s.tools.length ? `Looked in ${s.tools.join(" and ").replace(/_/g, " ")}` : "No code or issue search configured",
    s.tools.length ? `${plural(s.results, "result")}${s.failed?.length ? `, ${s.failed.join(", ")} unavailable` : ""}` : "", "tools"];
  return null;
}

export function createWorklog() {
  let startedAt = 0, subs = [], collapsed = false;
  const dot = h("span", { class: "wl-dot" }), title = h("span", { class: "wl-title" }, "Reading the question"), meta = h("span", { class: "wl-meta" });
  const head = h("button", { type: "button", class: "wl-head", "aria-expanded": "true", onclick: () => setCollapsed(!collapsed) }, dot, title, meta, icon("chevron", 16, "wl-chev"));
  const list = h("ol", { class: "wl-list" });
  const el = h("section", { class: "worklog", dataset: { state: "running" }, "aria-label": "Agent progress" }, head, list);

  function setCollapsed(v) { collapsed = v; el.classList.toggle("collapsed", v); head.setAttribute("aria-expanded", String(!v)); }
  const li = (label, detail, state = "pending") => h("li", { class: "wl-item wl-in", dataset: { state } }, h("span", { class: "wl-node" }), h("div", { class: "wl-body" }, h("div", { class: "wl-label" }, label), detail));
  const set = (item, state) => { item.dataset.state = state; };

  const understand = li("Reading the question", h("div", { class: "wl-detail" }), "active");
  const write = li("Writing the answer", null);
  list.append(understand, write);

  return {
    el,
    start() { startedAt = performance.now(); },
    decompose({ sub_queries }) {
      set(understand, "done");
      understand.querySelector(".wl-label").textContent = sub_queries.length === 1 ? "Understood: one question" : `Split into ${sub_queries.length} questions`;
      title.textContent = "Searching the docs";
      subs = sub_queries.map((q) => {
        const steps = h("ul", { class: "wl-steps" }), status = h("div", { class: "wl-status" }), refs = h("span", { class: "wl-refs" });
        const item = li(h("span", { class: "wl-q" }, q), h("div", { class: "wl-detail" }, steps, status), "active");
        write.before(item);
        return { q, item, steps, status, refs, done: false, rewrites: 0 };
      });
    },
    research(r) {
      const sub = subs.find((s) => s.q === r.sub_query && !s.done);
      if (!sub) return;
      sub.done = true; sub.rewrites = r.steps.filter((s) => s.kind === "rewrite").length;
      for (const s of r.steps) {
        const line = stepLine(s);
        if (line) sub.steps.append(h("li", { class: "wl-step", dataset: { kind: line[2] } }, h("span", { class: "wl-step-label" }, line[0]), line[1] ? h("span", { class: "wl-step-note" }, line[1]) : null));
      }
      const [kind, text] = STATUS[r.status] || STATUS.none;
      sub.status.replaceChildren(h("span", { class: `wl-result ${kind}` }, text), sub.refs);
      set(sub.item, "done");
      const n = subs.filter((s) => s.done).length;
      title.textContent = n === subs.length ? "Putting it together" : `Searched ${n} of ${subs.length}`;
      if (n === subs.length) set(write, "active");
    },
    synthesize(final) {
      final.research?.forEach((r, i) => {
        if (subs[i] && r.refs?.length) subs[i].refs.textContent = ` Sources ${r.refs.join(", ")}`;
      });
      set(write, "done");
      const rewrites = subs.reduce((a, s) => a + s.rewrites, 0);
      el.dataset.state = "done";
      title.textContent = [subs.length > 1 ? `${subs.length} questions` : "1 question", rewrites ? plural(rewrites, "rewrite") : null, plural(final.citations.length, "source")].filter(Boolean).join(", ");
      meta.textContent = fmtMs(final.took_ms ?? performance.now() - startedAt);
      setCollapsed(true);
    },
    fail() {
      el.dataset.state = "error"; title.textContent = "Stopped before finishing";
      list.querySelectorAll('[data-state="active"]').forEach((n) => set(n, "error"));
      setCollapsed(false);
    },
  };
}

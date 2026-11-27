// The signature element: how the router weighs "Meaning" (dense) against "Exact" (sparse) for a query.
import { h } from "../dom.js";

const WHAT = { error_code: "an error code", cli_flag: "a CLI flag", call_signature: "a function call",
  snake_case: "a snake_case name", dotted_path: "a dotted path", camel_case: "a camelCase name",
  backtick: "inline code", path_or_version: "a path or version" };

export function describeRoute(route) {
  if (!route) return "Type a question or paste an identifier. The router decides how much to rely on meaning versus exact matches.";
  const what = route.reasons?.map((r) => WHAT[r]).find(Boolean);
  if (route.label === "identifier") return `Reads as an exact lookup${what ? ` (${what})` : ""}. Leaning on exact matches.`;
  if (route.label === "conceptual") return "Reads as a plain-language question. Leaning on meaning.";
  return `Mixes an identifier${what ? ` (${what})` : ""} with plain language. Weighing both.`;
}

export function createBalance({ compact = false } = {}) {
  const meaning = h("span", { class: "bal-m" }), exact = h("span", { class: "bal-e" });
  const mVal = h("b"), eVal = h("b"), read = h("p", { class: "bal-read" });
  const el = h("div", { class: `balance${compact ? " compact" : ""}` },
    h("div", { class: "bal-labels" }, h("span", { class: "bal-lm" }, "Meaning ", mVal), h("span", { class: "bal-le" }, eVal, " Exact")),
    h("div", { class: "bal-bar", "aria-hidden": "true" }, meaning, exact), compact ? null : read);

  const paint = (m, e, text, mTxt, eTxt, label) => {
    meaning.style.flexGrow = String(m); exact.style.flexGrow = String(e);
    mVal.textContent = mTxt; eVal.textContent = eTxt; read.textContent = text;
    el.dataset.label = label;
  };
  return {
    el,
    idle() { paint(1, 1, describeRoute(null), "", "", "idle"); },
    set(route) { paint(route.dense_weight, route.sparse_weight, describeRoute(route), route.dense_weight.toFixed(1), route.sparse_weight.toFixed(1), route.label); },
    /** Fixed engine choice (dense / sparse / flat) instead of a routed decision. */
    fixed(kind) {
      if (kind === "dense") paint(1, 0.0001, "Meaning engine only. The router is bypassed.", "1.0", "0", "dense");
      else if (kind === "sparse") paint(0.0001, 1, "Exact-match engine only. The router is bypassed.", "0", "1.0", "sparse");
      else paint(1, 1, "Equal weights. The router is bypassed.", "1.0", "1.0", "flat");
    },
  };
}

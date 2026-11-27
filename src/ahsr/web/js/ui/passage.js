import { h } from "../dom.js";
import { markTerms } from "../terms.js";
import { renderMarkdown } from "../mdrender.js";
import { rankPips } from "./pips.js";

export function crumbs(section) {
  const parts = String(section || "").split(" > ").filter(Boolean);
  const last = parts.pop();
  return h("span", { class: "crumbs" }, parts.map((p) => [h("span", { class: "crumb" }, p), h("span", { class: "crumb-sep", "aria-hidden": "true" }, "/")]), h("span", { class: "crumb-last" }, last || ""));
}

/** Rendered passage body with exact-match highlights and an expand toggle for long ones. */
export function passageBody(text, terms, { limit = 340 } = {}) {
  const body = h("div", { class: "p-body" }, renderMarkdown(text, { headingBase: 3 }));
  markTerms(body, terms);
  const long = text.length > limit || text.includes("```");
  if (!long) return body;
  body.classList.add("clamped");
  const btn = h("button", { type: "button", class: "link-btn", "aria-expanded": "false", onclick: () => {
    const open = body.classList.toggle("clamped") === false;
    btn.textContent = open ? "Show less" : "Show full passage";
    btn.setAttribute("aria-expanded", String(open));
  } }, "Show full passage");
  return h("div", { class: "p-wrap" }, body, btn);
}

export function passageRow(hit, index, terms, { compact = false } = {}) {
  const row = h("li", { class: `passage${compact ? " compact" : ""}`, dataset: { id: hit.id } },
    h("div", { class: "p-rank" }, h("span", { class: "p-n" }, index + 1), compact ? null : rankPips(hit.ranks)),
    h("div", { class: "p-main" },
      h("div", { class: "p-head" }, h("h3", { class: "p-title" }, crumbs(hit.section)), h("span", { class: "p-src" }, hit.source)),
      passageBody(hit.body, terms)));
  markTerms(row.querySelector(".p-title"), terms);          // the heading often holds the identifier itself
  return row;
}

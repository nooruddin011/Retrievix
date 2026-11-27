import { h, icon } from "../dom.js";
import { markTerms } from "../terms.js";
import { crumbs, passageBody } from "./passage.js";

const ORIGIN = { code: ["code", "Code"], github: ["issue", "Issue"] };

export function createSources(terms) {
  const list = h("ol", { class: "src-list" });
  const count = h("span", { class: "count" });
  const el = h("aside", { class: "sources", "aria-label": "Sources" }, h("h2", { class: "side-title" }, "Sources ", count), list);
  const items = new Map();

  function set(citations) {
    list.replaceChildren(); items.clear();
    count.textContent = citations.length ? String(citations.length) : "";
    el.hidden = citations.length === 0;
    for (const c of citations) {
      const [ic, label] = ORIGIN[c.origin] || [null, null];
      const isUrl = /^https?:\/\//.test(c.source);
      const file = isUrl ? h("a", { href: c.source, target: "_blank", rel: "noopener noreferrer", class: "src-file" }, c.source.replace(/^https?:\/\//, "")) : h("span", { class: "src-file" }, c.source);
      const li = h("li", { class: `src${c.low_confidence ? " low" : ""}`, id: `src-${c.n}`, tabindex: "-1" },
        h("span", { class: "src-n" }, c.n),
        h("div", { class: "src-main" },
          h("div", { class: "src-head" }, h("span", { class: "src-title" }, c.section ? crumbs(c.section) : c.title),
            label ? h("span", { class: "chip" }, icon(ic, 12), label) : null,
            c.low_confidence ? h("span", { class: "chip warn", title: "Nothing in the docs was confirmed as relevant, so this is the closest match." }, "Unconfirmed") : null),
          file, passageBody(c.text, terms, { limit: 220 })));
      markTerms(li.querySelector(".src-title"), terms);
      items.set(c.n, li); list.append(li);
    }
  }

  const flash = (n, on) => items.get(n)?.classList.toggle("flash", on);
  function reveal(n) {
    const li = items.get(n);
    if (!li) return;
    li.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    li.focus({ preventScroll: true });
    flash(n, true); setTimeout(() => flash(n, false), 1600);
  }
  /** Factory for the [n] chips in answer text. Returns null for unknown numbers so they stay plain text. */
  const cite = (n) => items.has(n)
    ? h("button", { type: "button", class: "cite", "aria-label": `Source ${n}`, onclick: () => reveal(n), onmouseenter: () => flash(n, true), onmouseleave: () => flash(n, false), onfocus: () => flash(n, true), onblur: () => flash(n, false) }, n)
    : null;
  return { el, set, cite, has: (n) => items.has(n) };
}

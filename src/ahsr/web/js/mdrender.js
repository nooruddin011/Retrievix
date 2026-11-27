// AST -> DOM. Built only from createElement/createTextNode, so output is XSS-safe by construction.
import { copyText, h, icon } from "./dom.js";
import { tokenizeCode } from "./highlight.js";
import { parseInline, parseMarkdown } from "./markdown.js";

function codeBlock(b) {
  const code = h("code", { class: b.lang ? `lang-${b.lang}` : "" });
  for (const tok of tokenizeCode(b.code, b.lang)) code.append(tok.t === "plain" ? document.createTextNode(tok.v) : h("span", { class: `tok-${tok.t}` }, tok.v));
  const btn = h("button", { type: "button", class: "icon-btn sm", "aria-label": "Copy code", title: "Copy code",
    onclick: async () => {
      const ok = await copyText(b.code);
      btn.replaceChildren(icon(ok ? "check" : "x", 14));
      setTimeout(() => btn.replaceChildren(icon("copy", 14)), 1400);
    } }, icon("copy", 14));
  return h("figure", { class: "code" }, h("figcaption", { class: "code-head" }, h("span", {}, b.lang || "code"), btn), h("pre", { tabindex: "0" }, code));
}

export function renderInline(nodes, opts = {}) {
  const frag = document.createDocumentFragment();
  for (const n of nodes) {
    if (n.t === "text") frag.append(document.createTextNode(n.v));
    else if (n.t === "code") frag.append(h("code", { class: "inline" }, n.v));
    else if (n.t === "strong") frag.append(h("strong", {}, renderInline(n.c, opts)));
    else if (n.t === "em") frag.append(h("em", {}, renderInline(n.c, opts)));
    else if (n.t === "link") frag.append(h("a", { href: n.href, target: n.href.startsWith("#") ? null : "_blank", rel: "noopener noreferrer" }, renderInline(n.c, opts)));
    else if (n.t === "cite") frag.append((opts.cite && opts.cite(n.n)) || document.createTextNode(`[${n.n}]`));
  }
  return frag;
}

function renderBlocks(blocks, opts) {
  const frag = document.createDocumentFragment();
  const base = opts.headingBase ?? 0;
  for (const b of blocks) {
    if (b.type === "heading") frag.append(h(`h${Math.min(6, b.level + base)}`, {}, renderInline(parseInline(b.text), opts)));
    else if (b.type === "para") frag.append(h("p", {}, renderInline(parseInline(b.text), opts)));
    else if (b.type === "code") frag.append(codeBlock(b));
    else if (b.type === "hr") frag.append(h("hr"));
    else if (b.type === "quote") frag.append(h("blockquote", {}, renderBlocks(b.children, opts)));
    else if (b.type === "list") {
      frag.append(h(b.ordered ? "ol" : "ul", { start: b.ordered && b.start !== 1 ? b.start : null },
        b.items.map((it) => h("li", {}, renderInline(parseInline(it.text), opts), renderBlocks(it.children, opts)))));
    } else if (b.type === "table") {
      const cell = (tag, c, i) => h(tag, { style: { textAlign: b.align[i] || "" } }, renderInline(parseInline(c), opts));
      frag.append(h("div", { class: "table-wrap", tabindex: "0" }, h("table", {},
        h("thead", {}, h("tr", {}, b.head.map((c, i) => cell("th", c, i)))),
        h("tbody", {}, b.rows.map((r) => h("tr", {}, r.map((c, i) => cell("td", c, i))))))));
    }
  }
  return frag;
}

/** Render Markdown into a new element. opts.cite(n) may return an element for a [n] citation. */
export function renderMarkdown(src, opts = {}) {
  return h("div", { class: "md" }, renderBlocks(parseMarkdown(src), opts));
}

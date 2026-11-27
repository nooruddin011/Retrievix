// Minimal, safe Markdown parser (pure: no DOM). Produces an AST; mdrender.js turns it into elements.
// Supports what documentation and model answers actually use: headings, paragraphs, fenced code,
// lists (nested), blockquotes, tables, rules, **bold**, *italic*, `code`, [links](url) and [n] citations.
const FENCE = /^\s{0,3}(```+|~~~+)\s*([\w+#.-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const LIST = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const SAFE_URL = /^(https?:\/\/|mailto:|#|\/|\.{1,2}\/)/i;

export const isSafeUrl = (u) => SAFE_URL.test(u);

function cells(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

const startsBlock = (ln, next) =>
  FENCE.test(ln) || HEADING.test(ln) || HR.test(ln) || /^\s{0,3}>/.test(ln) || LIST.test(ln) ||
  (ln.includes("|") && next !== undefined && TABLE_SEP.test(next) && next.includes("-"));

export function parseMarkdown(src) {
  return parseBlocks(String(src).replace(/\r\n?/g, "\n").replace(/\t/g, "    ").split("\n"));
}

function parseBlocks(lines) {
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (!ln.trim()) { i++; continue; }

    let m = FENCE.exec(ln);
    if (m) {
      const [, fence, lang] = m;
      const body = [];
      i++;
      while (i < lines.length && !(lines[i].trim().startsWith(fence[0].repeat(fence.length)) && /^\s*[`~]+\s*$/.test(lines[i]))) body.push(lines[i++]);
      i++;                                                      // closing fence (or end of input)
      blocks.push({ type: "code", lang: lang || "", code: body.join("\n") });
      continue;
    }
    if ((m = HEADING.exec(ln))) { blocks.push({ type: "heading", level: m[1].length, text: m[2] }); i++; continue; }
    if (HR.test(ln)) { blocks.push({ type: "hr" }); i++; continue; }

    if (/^\s{0,3}>/.test(ln)) {
      const q = [];
      while (i < lines.length && /^\s{0,3}>/.test(lines[i])) q.push(lines[i++].replace(/^\s{0,3}>\s?/, ""));
      blocks.push({ type: "quote", children: parseBlocks(q) });
      continue;
    }

    if (ln.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = cells(ln);
      const align = cells(lines[i + 1]).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : ""));
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(cells(lines[i++]));
      blocks.push({ type: "table", head, align, rows });
      continue;
    }

    if ((m = LIST.exec(ln))) {
      const base = m[1].length, ordered = /\d/.test(m[2][0]);
      const items = [];
      while (i < lines.length) {
        const lm = LIST.exec(lines[i]);
        if (!lm || lm[1].length !== base || /\d/.test(lm[2][0]) !== ordered) break;
        const item = { text: lm[3], rest: [] };
        i++;
        while (i < lines.length) {                              // continuation + nested lines
          const next = lines[i];
          if (!next.trim()) { if (i + 1 < lines.length && /^\s/.test(lines[i + 1]) && lines[i + 1].search(/\S/) > base) { item.rest.push(""); i++; continue; } break; }
          if (next.search(/\S/) > base) { item.rest.push(next.slice(Math.min(next.search(/\S/), base + 2))); i++; continue; }
          break;
        }
        items.push({ text: item.text, children: item.rest.length ? parseBlocks(item.rest) : [] });
      }
      blocks.push({ type: "list", ordered, start: ordered ? parseInt(m[2], 10) : 1, items });
      continue;
    }

    const para = [ln.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i], lines[i + 1])) para.push(lines[i++].trim());
    blocks.push({ type: "para", text: para.join(" ") });
  }
  return blocks;
}

// ---- inline ---------------------------------------------------------------------------------------
const INLINE = [
  ["code", /`([^`\n]+)`/],
  ["link", /\[([^\]\n]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)/],
  ["cite", /\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()/],
  ["strong", /\*\*(?=\S)([\s\S]*?\S)\*\*|(?<![\w])__(?=\S)([\s\S]*?\S)__(?![\w])/],
  ["em", /\*(?=[^\s*])([^*\n]*?[^\s*])\*|(?<![\w])_(?=[^\s_])([^_\n]*?[^\s_])_(?![\w])/],
];

export function parseInline(text) {
  const out = [];
  let rest = text;
  while (rest) {
    let best = null;
    for (const [type, re] of INLINE) {
      const m = re.exec(rest);
      if (m && (!best || m.index < best.m.index)) best = { type, m };
    }
    if (!best) { out.push({ t: "text", v: rest }); break; }
    const { type, m } = best;
    if (m.index > 0) out.push({ t: "text", v: rest.slice(0, m.index) });
    if (type === "code") out.push({ t: "code", v: m[1] });
    else if (type === "link") out.push(isSafeUrl(m[2]) ? { t: "link", href: m[2], c: parseInline(m[1]) } : { t: "text", v: m[1] });
    else if (type === "cite") for (const n of m[1].split(",")) out.push({ t: "cite", n: parseInt(n, 10) });
    else out.push({ t: type, c: parseInline(m[1] ?? m[2]) });
    rest = rest.slice(m.index + m[0].length);
  }
  return out;
}

// Which parts of a passage matched the query *exactly*? Used to paint the amber highlights.
const STOP = new Set(["the", "and", "for", "with", "how", "why", "what", "when", "where", "does", "did", "can", "could",
  "should", "would", "this", "that", "from", "into", "also", "are", "was", "were", "has", "have", "had", "not",
  "you", "your", "our", "any", "all", "get", "got", "way", "use", "using", "its", "but", "than", "then", "too"]);

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Identifiers (ERR_0x884A, --dry-run, client.create_webhook) are kept whole; plain words need 3+ letters. */
export function queryTerms(query) {
  const found = new Map();
  for (const raw of String(query).match(/[\w.\-:]+/g) || []) {
    const t = raw.replace(/^[.:]+|[.:,]+$/g, "");
    const isIdent = /[_.\-:]/.test(t) || /\d/.test(t) && /[a-z]/i.test(t) || /[a-z][A-Z]/.test(t);
    const low = t.toLowerCase();
    if (t.length < 3 || (!isIdent && STOP.has(low))) continue;
    found.set(low, { text: t, ident: isIdent });
  }
  return [...found.values()].sort((a, b) => b.text.length - a.text.length);
}

export function termRegex(terms) {
  if (!terms.length) return null;
  const parts = terms.map((t) => (t.ident ? esc(t.text) : `(?<![\\w])${esc(t.text)}(?![\\w])`));
  return new RegExp(parts.join("|"), "gi");
}

/** Split text into [{text, hit}] segments. */
export function splitByTerms(text, terms) {
  const re = termRegex(terms);
  if (!re) return [{ text, hit: false }];
  const out = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), hit: false });
    out.push({ text: m[0], hit: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), hit: false });
  return out;
}

/** Wrap matches in <mark> inside an element, touching text nodes only (never markup). */
export function markTerms(root, terms) {
  const re = termRegex(terms);
  if (!re) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement.closest("button, mark, .code-head") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const segs = splitByTerms(node.nodeValue, terms);
    if (segs.length === 1 && !segs[0].hit) continue;
    const frag = document.createDocumentFragment();
    for (const s of segs) {
      if (s.hit) { const m = document.createElement("mark"); m.textContent = s.text; frag.append(m); }
      else frag.append(document.createTextNode(s.text));
    }
    node.replaceWith(frag);
  }
}

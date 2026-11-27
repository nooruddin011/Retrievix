// Small syntax highlighter for documentation snippets. Pure: returns tokens, the renderer builds spans.
const KW = {
  python: "def class return if elif else for while in not and or is None True False import from as with try except finally raise lambda yield async await pass break continue",
  js: "function const let var return if else for while in of new class extends import from export default async await try catch finally throw null undefined true false typeof this",
  bash: "if then else fi for do done while case esac function export in",
  go: "func package import return if else for range var const type struct interface go defer nil true false",
};
KW.javascript = KW.js; KW.typescript = KW.js; KW.ts = KW.js; KW.sh = KW.bash; KW.shell = KW.bash; KW.zsh = KW.bash; KW.py = KW.python;

const HASH_COMMENT = new Set(["python", "py", "bash", "sh", "shell", "zsh", "yaml", "yml", "toml", "ruby", "rb"]);
const cache = new Map();

function build(lang) {
  const kws = (KW[lang] || "").split(" ").filter(Boolean);
  const comment = HASH_COMMENT.has(lang) ? String.raw`#[^\n]*` : String.raw`//[^\n]*|/\*[\s\S]*?\*/`;
  const parts = [
    ["com", comment],
    ["str", String.raw`"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|` + "`(?:\\\\.|[^`\\\\])*`"],
    ["num", String.raw`\b0x[0-9a-fA-F]+\b|\b\d+(?:\.\d+)?\b`],
  ];
  if (["bash", "sh", "shell", "zsh"].includes(lang)) parts.push(["flag", String.raw`(?<![\w-])--?[A-Za-z][\w-]*`]);
  if (kws.length) parts.push(["kw", String.raw`\b(?:${kws.join("|")})\b`]);
  parts.push(["fn", String.raw`\b[A-Za-z_][\w]*(?=\()`]);
  return { names: parts.map((p) => p[0]), re: new RegExp(parts.map((p) => `(${p[1]})`).join("|"), "g") };
}

export function tokenizeCode(code, lang = "") {
  const key = String(lang).toLowerCase();
  if (!cache.has(key)) cache.set(key, build(key));
  const { names, re } = cache.get(key);
  const out = [];
  let last = 0;
  re.lastIndex = 0;
  for (let m; (m = re.exec(code)); ) {
    if (m[0] === "") { re.lastIndex++; continue; }
    if (m.index > last) out.push({ t: "plain", v: code.slice(last, m.index) });
    out.push({ t: names[m.slice(1).findIndex((g) => g !== undefined)], v: m[0] });
    last = m.index + m[0].length;
  }
  if (last < code.length) out.push({ t: "plain", v: code.slice(last) });
  return out;
}

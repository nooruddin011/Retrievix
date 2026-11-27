import assert from "node:assert/strict";
import { test } from "node:test";
import { tokenizeCode } from "../../src/ahsr/web/js/highlight.js";
import { isSafeUrl, parseInline, parseMarkdown } from "../../src/ahsr/web/js/markdown.js";
import { queryTerms, splitByTerms } from "../../src/ahsr/web/js/terms.js";

const types = (nodes) => nodes.map((n) => n.t);

test("blocks: headings, paragraphs, hr, fenced code keeps # lines intact", () => {
  const b = parseMarkdown("# Title\n\nSome *text*\nwrapped.\n\n---\n\n```python\n# not a heading\nx = 1\n```\n");
  assert.deepEqual(b.map((x) => x.type), ["heading", "para", "hr", "code"]);
  assert.equal(b[1].text, "Some *text* wrapped.");
  assert.deepEqual([b[3].lang, b[3].code], ["python", "# not a heading\nx = 1"]);
});

test("unterminated code fence consumes the rest instead of throwing", () => {
  const b = parseMarkdown("```js\nlet a = 1;\nstill code");
  assert.equal(b.length, 1);
  assert.equal(b[0].code, "let a = 1;\nstill code");
});

test("lists: ordered/unordered, nesting and start numbers", () => {
  const [ul, ol] = parseMarkdown("- one\n- two\n  - nested a\n  - nested b\n- three\n\n3. third\n4. fourth\n");
  assert.equal(ul.items.length, 3);
  assert.equal(ul.items[1].children[0].items.length, 2);
  assert.deepEqual([ol.ordered, ol.start, ol.items.length], [true, 3, 2]);
});

test("tables with alignment", () => {
  const [t] = parseMarkdown("| Name | Qty |\n|:--|--:|\n| a \\| b | 2 |\n");
  assert.deepEqual(t.head, ["Name", "Qty"]);
  assert.deepEqual(t.align, ["", "right"]);
  assert.deepEqual(t.rows, [["a | b", "2"]]);
});

test("blockquote parses its content as blocks", () => {
  const [q] = parseMarkdown("> **Note**\n> second line\n");
  assert.equal(q.type, "quote");
  assert.equal(q.children[0].type, "para");
});

test("inline: code first, citations, grouped citations, strong/em", () => {
  assert.deepEqual(types(parseInline("Use `a*b*c` then **bold** and *em* [1] [2, 3]")),
    ["text", "code", "text", "strong", "text", "em", "text", "cite", "text", "cite", "cite"]);
  assert.deepEqual(parseInline("[2, 3]").map((n) => n.n), [2, 3]);
});

test("inline: snake_case and identifiers are not mistaken for emphasis", () => {
  for (const s of ["rotate_webhook_secret grace_period_s", "ERR_0x884A and ERR_0x1F02", "my_var_name", "a * b * c"]) {
    assert.deepEqual(types(parseInline(s)), ["text"], s);
  }
  assert.equal(parseInline("_real emphasis_").length, 1);
  assert.equal(parseInline("_real emphasis_")[0].t, "em");
});

test("links: only safe schemes become links (no javascript: / data: URLs)", () => {
  assert.equal(parseInline("[x](https://a.example/p?q=1)")[0].t, "link");
  assert.equal(parseInline("[x](#section)")[0].t, "link");
  const wiki = parseInline("[w](https://en.wikipedia.org/wiki/Foo_(bar))");
  assert.deepEqual([wiki.length, wiki[0].href], [1, "https://en.wikipedia.org/wiki/Foo_(bar)"]);
  for (const evil of ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<b>", "vbscript:x"]) {
    const n = parseInline(`[click](${evil})`);
    assert.deepEqual(types(n), ["text"], evil);
    assert.ok(!isSafeUrl(evil));
  }
});

test("raw HTML stays inert text in the AST", () => {
  const [p] = parseMarkdown("<script>alert(1)</script> <img src=x onerror=alert(1)>");
  assert.equal(p.type, "para");
  const nodes = parseInline(p.text);
  assert.ok(nodes.every((n) => n.t === "text"));
});

test("code tokenizer: python, bash flags, strings with # are not comments", () => {
  const py = tokenizeCode('x = hmac.new(secret, "a # b", 3)  # why', "python");
  assert.deepEqual(py.filter((t) => t.t !== "plain").map((t) => [t.t, t.v]),
    [["fn", "new"], ["str", '"a # b"'], ["num", "3"], ["com", "# why"]]);
  const sh = tokenizeCode("acme deploy --max-retries 5 --dry-run", "bash");
  assert.deepEqual(sh.filter((t) => t.t === "flag").map((t) => t.v), ["--max-retries", "--dry-run"]);
  assert.equal(tokenizeCode("a b c", "unknown-lang").map((t) => t.v).join(""), "a b c");
});

test("code tokenizer is lossless", () => {
  const src = 'def f(a):\n    return "s" + str(0x1F) # c\n';
  assert.equal(tokenizeCode(src, "python").map((t) => t.v).join(""), src);
});

test("queryTerms keeps identifiers whole and drops filler words", () => {
  const t = queryTerms("how do I fix ERR_0x884A with --dry-run and client.create_webhook(url)");
  const texts = t.map((x) => x.text);
  assert.ok(texts.includes("ERR_0x884A") && texts.includes("--dry-run") && texts.includes("client.create_webhook"));
  assert.ok(!texts.includes("how") && !texts.includes("with") && !texts.includes("and"));
  assert.deepEqual(queryTerms("how to stop billing").map((x) => x.text).sort(), ["billing", "stop"]);
});

test("splitByTerms is case-insensitive, respects word boundaries and loses no text", () => {
  const text = "Stopping billing: err_0x884a means Billing stops.";
  const segs = splitByTerms(text, queryTerms("ERR_0X884A billing stop"));
  assert.equal(segs.map((s) => s.text).join(""), text);
  assert.deepEqual(segs.filter((s) => s.hit).map((s) => s.text), ["billing", "err_0x884a", "Billing"]);   // "Stopping"/"stops" not matched by "stop"
});

test("special regex characters in queries cannot break matching", () => {
  const text = "call a.b(c) [x] (y)* now";
  assert.equal(splitByTerms(text, queryTerms("a.b(c) [x] (y)*")).map((s) => s.text).join(""), text);
});

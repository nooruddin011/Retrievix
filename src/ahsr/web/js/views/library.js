import { api, ApiError } from "../api.js";
import { fmtBytes, h, icon, mount, plural, timeAgo } from "../dom.js";
import { renderMarkdown } from "../mdrender.js";
import { buildHash, navigate } from "../router.js";
import { documentDialog, confirmDialog } from "../ui/dialogs.js";
import { crumbs } from "../ui/passage.js";
import { emptyState, errorBlock, notice, skeleton, toast } from "../ui/feedback.js";

export function LibraryView(ctx) {
  let data = null, selected = "", busy = false;
  const listEl = h("aside", { class: "doc-list", "aria-label": "Documents" });
  const readerEl = h("article", { class: "doc-reader", "aria-live": "polite" });
  const summary = h("p", { class: "lede" });
  const actions = h("div", { class: "head-actions" });
  const banner = h("div", { class: "banner-slot" });
  const overlay = h("div", { class: "drop-overlay", hidden: true, "aria-hidden": "true" }, icon("upload", 28), h("p", {}, "Drop Markdown files to add them"));
  const fileInput = h("input", { type: "file", accept: ".md,text/markdown", multiple: true, hidden: true, onchange: () => { upload([...fileInput.files]); fileInput.value = ""; } });
  const el = h("section", { class: "view view-library" },
    h("header", { class: "view-head" }, h("div", {}, h("h1", {}, "Library"), summary), actions), banner,
    h("div", { class: "library-grid" }, listEl, readerEl), overlay, fileInput);

  const readOnly = () => Boolean(data?.read_only);

  // ---- data ---------------------------------------------------------------------------------
  async function refresh() {
    try {
      data = await api.documents();
      if (selected && !data.documents.some((d) => d.path === selected)) selected = "";
      paint();
    } catch (e) {
      mount(listEl); mount(readerEl, errorBlock({ title: "Couldn’t load the library", message: e instanceof ApiError ? e.friendly : "Unexpected error.", onRetry: refresh }));
    }
  }

  function paint() {
    const { documents: docs, totals, orphaned } = data;
    summary.textContent = docs.length ? `${plural(totals.documents, "document")}, ${totals.indexed} of ${plural(totals.chunks, "passage")} indexed` : "No documents yet";
    const stale = docs.filter((d) => !d.in_sync).length;
    mount(banner,
      readOnly() ? notice("info", "Read-only", "This server doesn’t allow changing documents.") : null,
      !readOnly() && (stale || orphaned.length) ? notice("warn", stale ? `${plural(stale, "document")} out of sync with the search index` : "The index contains documents that no longer exist",
        "Re-index to bring search up to date.", [h("button", { type: "button", class: "btn sm", onclick: reindex }, icon("refresh", 14), "Re-index now")]) : null);
    mount(actions, readOnly() ? null : [
      h("button", { type: "button", class: "btn", onclick: () => fileInput.click() }, icon("upload", 16), "Upload"),
      h("button", { type: "button", class: "btn", onclick: () => newDoc() }, icon("plus", 16), "New"),
      h("button", { type: "button", class: "btn", disabled: busy, onclick: reindex }, icon("refresh", 16, busy ? "spin" : ""), "Re-index")]);

    if (!docs.length) {
      mount(listEl); listEl.hidden = true;
      mount(readerEl, emptyState({ title: "Add your first document", body: "Documents are Markdown files. Each section becomes a passage that can be found by meaning or by exact text.",
        actions: readOnly() ? [] : [h("button", { type: "button", class: "btn primary", onclick: () => fileInput.click() }, icon("upload", 16), "Upload Markdown"), h("button", { type: "button", class: "btn", onclick: () => newDoc() }, "Write one")] }));
      return;
    }
    listEl.hidden = false;
    mount(listEl, h("ul", {}, docs.map((d) => h("li", {}, h("a", { class: "doc-item", href: buildHash("library", { rest: d.path }), "aria-current": d.path === selected ? "page" : null },
      h("span", { class: `dot ${d.in_sync ? "ok" : "warn"}`, title: d.in_sync ? "Indexed and up to date" : "Needs re-indexing" }),
      h("span", { class: "doc-title" }, d.title), h("span", { class: "doc-path" }, d.path), h("span", { class: "doc-meta" }, `${plural(d.chunks, "passage")} · ${fmtBytes(d.bytes)}`))))));
    if (!selected) mount(readerEl, h("div", { class: "reader-hint" }, h("p", {}, "Choose a document to see how it’s split into passages for search.")));
  }

  // ---- reader -------------------------------------------------------------------------------
  async function open(path) {
    selected = path;
    if (data) paint();
    mount(readerEl, skeleton(6));
    try {
      const d = await api.document(path);
      if (selected !== path) return;
      const n = d.chunks.length;
      mount(readerEl,
        h("a", { class: "back-link link-btn", href: "#/library" }, "All documents"),
        h("header", { class: "reader-head" }, h("div", {}, h("h2", {}, d.title), h("p", { class: "doc-path" }, d.path)),
          readOnly() ? null : h("div", { class: "head-actions" },
            h("button", { type: "button", class: "btn sm", onclick: () => edit(d) }, icon("edit", 14), "Edit"),
            h("button", { type: "button", class: "btn sm danger-ghost", onclick: () => remove(d) }, icon("trash", 14), "Delete"))),
        h("p", { class: "reader-meta" }, `${fmtBytes(d.bytes)} · ${plural(n, "passage")} · edited ${timeAgo(d.modified)} · `, h("span", { class: d.in_sync ? "ok-text" : "warn-text" }, d.in_sync ? "indexed" : "needs re-indexing")),
        h("p", { class: "reader-explain" }, "This is how the document is split for search. Each passage is embedded and indexed on its own, with its heading path kept as context."),
        h("ol", { class: "chunks" }, d.chunks.map((c, i) => h("li", { class: "chunk" },
          h("div", { class: "chunk-head" }, h("span", { class: "chunk-n" }, `Passage ${i + 1} of ${n}`), h("span", { class: "chunk-chars" }, `${c.chars} characters`)),
          h("div", { class: "chunk-crumbs" }, crumbs(c.section)), renderMarkdown(c.body, { headingBase: 3 })))));
      readerEl.scrollTop = 0;
    } catch (e) {
      if (selected !== path) return;
      mount(readerEl, e instanceof ApiError && e.status === 404
        ? emptyState({ title: "That document doesn’t exist", body: "It may have been deleted.", actions: [h("a", { class: "btn", href: "#/library" }, "Back to the library")] })
        : errorBlock({ message: e instanceof ApiError ? e.friendly : "Unexpected error.", onRetry: () => open(path) }));
    }
  }

  // ---- actions ------------------------------------------------------------------------------
  const maxBytes = () => ctx.health().max_doc_bytes || 524288;
  async function save(path, content) {
    const r = await api.saveDocument(path, content);
    toast(`${r.created ? "Added" : "Saved"} ${r.path}. ${plural(r.chunks, "passage")} indexed.`, { kind: "ok" });
    ctx.refreshHealth();
    return r;
  }
  async function newDoc() {
    const r = await documentDialog({ maxBytes: maxBytes() });
    if (!r) return;
    try { await save(r.path, r.content); await refresh(); navigate(buildHash("library", { rest: r.path })); }
    catch (e) { toast(e instanceof ApiError ? e.friendly : "Couldn’t save the document.", { kind: "error", timeout: 7000 }); }
  }
  async function edit(d) {
    const r = await documentDialog({ path: d.path, content: d.markdown, maxBytes: maxBytes() });
    if (!r) return;
    try { await save(d.path, r.content); await refresh(); await open(d.path); }
    catch (e) { toast(e instanceof ApiError ? e.friendly : "Couldn’t save the document.", { kind: "error", timeout: 7000 }); }
  }
  async function remove(d) {
    if (!(await confirmDialog({ title: `Delete ${d.path}?`, message: `This removes the file and its ${plural(d.chunks, "passage")} from search. It can’t be undone.`, confirm: "Delete document", danger: true }))) return;
    try { await api.deleteDocument(d.path); toast(`Deleted ${d.path}`, { kind: "ok" }); selected = ""; ctx.refreshHealth(); navigate("#/library"); await refresh(); }
    catch (e) { toast(e instanceof ApiError ? e.friendly : "Couldn’t delete the document.", { kind: "error", timeout: 7000 }); }
  }
  async function reindex() {
    if (busy) return;
    busy = true; paint();
    try {
      const r = await api.reindex(false);
      toast(r.added || r.removed ? `Index updated: ${r.added} added, ${r.removed} removed.` : "The index was already up to date.", { kind: "ok" });
      ctx.refreshHealth();
    } catch (e) { toast(e instanceof ApiError ? e.friendly : "Re-indexing failed.", { kind: "error", timeout: 7000 }); }
    busy = false; await refresh();
    if (selected) open(selected);
  }

  async function upload(files) {
    if (readOnly() || !files.length) return;
    const md = files.filter((f) => /\.md$/i.test(f.name)), skipped = files.length - md.length;
    if (skipped) toast(`${plural(skipped, "file")} skipped: only Markdown (.md) is supported.`, { kind: "error", timeout: 6000 });
    let ok = 0, last = "";
    for (const f of md) {
      if (f.size > maxBytes()) { toast(`${f.name} is larger than ${Math.floor(maxBytes() / 1024)} KB.`, { kind: "error", timeout: 7000 }); continue; }
      try { const r = await api.saveDocument(f.name, await f.text()); ok++; last = r.path; }
      catch (e) { toast(`${f.name}: ${e instanceof ApiError ? e.friendly : "upload failed"}`, { kind: "error", timeout: 7000 }); }
    }
    if (ok) { toast(`${plural(ok, "document")} added and indexed.`, { kind: "ok" }); ctx.refreshHealth(); }
    await refresh();
    if (ok === 1) navigate(buildHash("library", { rest: last }));
  }

  // drag & drop anywhere on the view
  let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  el.addEventListener("dragenter", (e) => { if (hasFiles(e) && !readOnly()) { e.preventDefault(); depth++; overlay.hidden = false; } });
  el.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  el.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; overlay.hidden = true; } });
  el.addEventListener("drop", (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; overlay.hidden = true; upload([...e.dataTransfer.files]); });

  return {
    el,
    async show({ rest }) {
      document.title = `Library · ${ctx.health().app_name || "Hybrid Search"}`;
      el.dataset.reading = rest ? "true" : "false";
      if (!data) mount(listEl, skeleton(5));
      selected = rest || "";
      await refresh();
      if (rest) open(rest);
    },
    hide() { selected = ""; },
  };
}

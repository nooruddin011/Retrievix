import { h } from "../dom.js";

function open(dlg) {
  document.body.append(dlg);
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => { const v = dlg.returnValue; dlg.remove(); resolve(v); }, { once: true });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(""); });        // backdrop click
    dlg.showModal();
  });
}

export async function confirmDialog({ title, message, confirm = "Confirm", danger = false }) {
  const dlg = h("dialog", { class: "dialog", "aria-labelledby": "dlg-title" },
    h("form", { method: "dialog" }, h("h2", { id: "dlg-title" }, title), h("p", {}, message),
      h("div", { class: "dialog-actions" }, h("button", { class: "btn", value: "" }, "Cancel"), h("button", { class: `btn ${danger ? "danger" : "primary"}`, value: "yes", autofocus: true }, confirm))));
  return (await open(dlg)) === "yes";
}

export async function keyDialog(current = "") {
  const input = h("input", { type: "password", class: "field", autocomplete: "off", spellcheck: "false", value: current, "aria-label": "API key", placeholder: "Paste your API key" });
  const dlg = h("dialog", { class: "dialog", "aria-labelledby": "dlg-title" },
    h("form", { method: "dialog" }, h("h2", { id: "dlg-title" }, "API key required"),
      h("p", {}, "This server only answers requests that include a key. It’s kept for this browser tab only and cleared when you close it."),
      input, h("div", { class: "dialog-actions" }, h("button", { class: "btn", value: "" }, "Cancel"), h("button", { class: "btn primary", value: "save" }, "Save key"))));
  const result = await open(dlg);
  return result === "save" ? input.value.trim() : null;
}

/** Create or edit a Markdown document. Resolves to {path, content} or null. */
export async function documentDialog({ path = "", content = "", maxBytes = 524288 } = {}) {
  const editing = Boolean(path);
  const name = h("input", { class: "field", value: path, disabled: editing, spellcheck: "false", placeholder: "guides/setup.md", "aria-label": "File name", "aria-describedby": "doc-hint" });
  const area = h("textarea", { class: "field mono", rows: 14, spellcheck: "false", "aria-label": "Markdown content", placeholder: "# Title\n\n## A section\nWrite in Markdown. Each section is indexed as its own passage." });
  area.value = content;
  const err = h("p", { class: "field-error", role: "alert" });
  const dlg = h("dialog", { class: "dialog wide", "aria-labelledby": "dlg-title" },
    h("form", { method: "dialog" }, h("h2", { id: "dlg-title" }, editing ? `Edit ${path}` : "New document"),
      editing ? null : [h("label", { class: "label" }, "File name", name), h("p", { class: "hint", id: "doc-hint" }, "Use letters, numbers, dashes and underscores. Folders like guides/setup.md are fine.")],
      h("label", { class: "label" }, "Content", area), err,
      h("div", { class: "dialog-actions" }, h("button", { class: "btn", value: "", formnovalidate: true }, "Cancel"),
        h("button", { class: "btn primary", value: "save", onclick: (e) => {
          let p = name.value.trim();
          if (!editing && p && !/\.md$/i.test(p)) p += ".md";
          const problem = !p ? "Give the document a file name." : !area.value.trim() ? "The document is empty." : new Blob([area.value]).size > maxBytes ? `Documents can be at most ${Math.floor(maxBytes / 1024)} KB.` : "";
          if (problem) { e.preventDefault(); err.textContent = problem; (p ? area : name).focus(); } else name.value = p;
        } }, editing ? "Save and re-index" : "Add and index"))));
  const result = await open(dlg);
  return result === "save" ? { path: name.value.trim(), content: area.value } : null;
}

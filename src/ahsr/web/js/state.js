// Preferences and history. localStorage may be unavailable (private mode, blocked): fall back to memory.
const mem = new Map();
const backend = (kind) => { try { const s = window[kind]; s.setItem("_t", "1"); s.removeItem("_t"); return s; } catch { return null; } };
const local = backend("localStorage"), session = backend("sessionStorage");

function read(store, key, fallback) {
  try { const raw = store ? store.getItem(key) : mem.get(key); return raw == null ? fallback : JSON.parse(raw); } catch { return fallback; }
}
function write(store, key, value) {
  const raw = JSON.stringify(value);
  try { store ? store.setItem(key, raw) : mem.set(key, raw); } catch { mem.set(key, raw); }
}

export const prefs = {
  get theme() { return read(local, "hs.theme", "system"); },
  set theme(v) { write(local, "hs.theme", v); },
  get mode() { return read(local, "hs.mode", "ask"); },
  set mode(v) { write(local, "hs.mode", v); },
  get demoDismissed() { return read(session, "hs.demo", false); },
  set demoDismissed(v) { write(session, "hs.demo", v); },
  // The API key lives in sessionStorage only: it disappears with the tab.
  get apiKey() { return read(session, "hs.key", ""); },
  set apiKey(v) { write(session, "hs.key", v); },
};

const HISTORY_MAX = 8;
export const history = {
  all() { return read(local, "hs.history", []); },
  add(q, mode) {
    const rest = this.all().filter((h) => !(h.q === q && h.mode === mode));
    write(local, "hs.history", [{ q, mode, t: Date.now() }, ...rest].slice(0, HISTORY_MAX));
  },
  clear() { write(local, "hs.history", []); },
};

export function applyTheme() {
  const t = prefs.theme;
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}

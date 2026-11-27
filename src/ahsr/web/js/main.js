import { api } from "./api.js";
import { $, h, icon, mount, plural } from "./dom.js";
import { onRoute, buildHash } from "./router.js";
import { applyTheme, prefs } from "./state.js";
import { keyDialog } from "./ui/dialogs.js";
import { toast } from "./ui/feedback.js";
import { EvaluateView } from "./views/evaluate.js";
import { LibraryView } from "./views/library.js";
import { SearchView } from "./views/search.js";

let health = { reachable: false, app_name: "Hybrid Search", max_query_chars: 2000 };
const ctx = { health: () => health, refreshHealth };

const NAV = [["search", "Search", "search"], ["library", "Library", "library"], ["evaluate", "Evaluate", "chart"]];
const views = {}, factories = { search: SearchView, library: LibraryView, evaluate: EvaluateView };
let current = null, currentName = "";

// ---- header --------------------------------------------------------------------------------------
const statusDot = h("span", { class: "dot" }), statusText = h("span", { class: "status-text" });
const statusBtn = h("button", { type: "button", class: "status-btn", "aria-haspopup": "dialog", "aria-expanded": "false", onclick: togglePanel }, statusDot, statusText);
const themeBtn = h("button", { type: "button", class: "icon-btn", onclick: toggleTheme });
const panel = h("div", { class: "status-panel", role: "dialog", "aria-label": "System status", hidden: true });
const navEl = h("nav", { class: "nav", "aria-label": "Primary" }, NAV.map(([key, label, ic]) => h("a", { href: buildHash(key), dataset: { nav: key } }, icon(ic, 16), h("span", {}, label))));

function mark() {
  return h("svg", { viewBox: "0 0 32 32", width: 26, height: 26, class: "mark", "aria-hidden": "true" },
    h("rect", { class: "mk-m", x: 6, y: 5, width: 8, height: 22, rx: 4 }), h("rect", { class: "mk-e", x: 17, y: 11, width: 8, height: 16, rx: 4 }));
}

function buildBar() {
  mount($("#bar"), h("div", { class: "bar-in" },
    h("a", { class: "brand", href: "#/", "aria-label": `${health.app_name} home` }, mark(), h("span", {}, health.app_name)),
    navEl, h("div", { class: "bar-right" }, h("div", { class: "status-wrap" }, statusBtn, panel), themeBtn)));
  paintTheme();
}

function resolvedTheme() { return prefs.theme === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : prefs.theme; }
function paintTheme() {
  const dark = resolvedTheme() === "dark";
  themeBtn.replaceChildren(icon(dark ? "sun" : "moon", 18));
  themeBtn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
}
function toggleTheme() { prefs.theme = resolvedTheme() === "dark" ? "light" : "dark"; applyTheme(); paintTheme(); }
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintTheme);

// ---- status --------------------------------------------------------------------------------------
function paintStatus() {
  const ok = health.reachable && health.status === "ok";
  statusDot.className = `dot ${ok ? "ok" : health.reachable ? "warn" : "bad"}`;
  statusBtn.setAttribute("aria-label", `System status: ${!health.reachable ? "server unreachable" : ok ? `${plural(health.documents ?? 0, "document")}, ${plural(health.chunks ?? 0, "passage")} indexed` : "degraded"}`);
  statusText.textContent = !health.reachable ? "Offline" : !ok ? "Degraded" : `${plural(health.documents ?? 0, "doc")} · ${plural(health.chunks ?? 0, "passage")}`;
  if (!panel.hidden) paintPanel();
  paintBanners();
}

function row(label, value, note) { return h("div", { class: "kv" }, h("dt", {}, label), h("dd", {}, value, note ? h("span", { class: "kv-note" }, note) : null)); }
function paintPanel() {
  const hs = health, up = hs.uptime_s ?? 0;
  mount(panel, h("h2", {}, "System"), h("dl", {},
    row("Search engines", hs.demo_mode ? "Offline stand-ins" : "Hugging Face models", hs.demo_mode ? "Demo quality" : hs.encoder_backend),
    row("Answers", hs.llm_mode === "claude" ? "Claude" : "Offline extraction", hs.llm_mode === "claude" ? "" : "No API key set"),
    row("Extra tools", hs.tools?.length ? hs.tools.join(", ").replace(/_/g, " ") : "None configured"),
    row("Index", `${plural(hs.chunks ?? 0, "passage")} in ${plural(hs.documents ?? 0, "document")}`),
    row("Access", hs.read_only ? "Read-only" : "Can edit documents"),
    row("Version", `${hs.version || "?"}`, up ? `up ${up < 3600 ? Math.ceil(up / 60) + " min" : Math.floor(up / 3600) + " h"}` : "")),
    hs.auth_required ? h("button", { type: "button", class: "btn sm", onclick: () => { closePanel(); askKey(); } }, icon("key", 14), prefs.apiKey ? "Change API key" : "Set API key") : null,
    prefs.theme !== "system" ? h("button", { type: "button", class: "link-btn", onclick: () => { prefs.theme = "system"; applyTheme(); paintTheme(); } }, "Use the system theme") : null);
}
function closePanel() { panel.hidden = true; statusBtn.setAttribute("aria-expanded", "false"); }
function togglePanel() { panel.hidden = !panel.hidden; statusBtn.setAttribute("aria-expanded", String(!panel.hidden)); if (!panel.hidden) paintPanel(); }
addEventListener("click", (e) => { if (!panel.hidden && !e.target.closest(".status-wrap")) closePanel(); });
addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) { closePanel(); statusBtn.focus(); } });

// ---- banners -------------------------------------------------------------------------------------
function paintBanners() {
  const items = [];
  if (!health.reachable) {
    items.push(h("div", { class: "banner bad", role: "alert" }, icon("alert", 16), h("span", {}, "Can’t reach the server. Searches won’t work until it’s back."), h("button", { type: "button", class: "btn sm", onclick: refreshHealth }, "Retry")));
  } else if (health.status !== "ok") {
    items.push(h("div", { class: "banner bad", role: "alert" }, icon("alert", 16), h("span", {}, "The vector store isn’t responding. Search is unavailable until it recovers.")));
  } else if (health.demo_mode && !prefs.demoDismissed) {
    items.push(h("div", { class: "banner" }, icon("info", 16), h("span", {}, h("strong", {}, "Demo mode. "), "The search engines here are lightweight stand-ins, so results only preview the real thing. Set ", h("code", { class: "inline" }, "ENCODER_BACKEND=hf"), " for the real models."),
      h("button", { type: "button", class: "icon-btn sm", "aria-label": "Dismiss", onclick: () => { prefs.demoDismissed = true; paintBanners(); } }, icon("x", 14))));
  }
  mount($("#banners"), items);
}

// ---- auth ----------------------------------------------------------------------------------------
let asking = false;
async function askKey() {
  if (asking) return;
  asking = true;
  const key = await keyDialog(prefs.apiKey);
  asking = false;
  if (key === null) return;
  prefs.apiKey = key;
  await refreshHealth();
  dispatchEvent(new HashChangeEvent("hashchange"));
}
addEventListener("hs:auth", () => { if (!asking) { toast(prefs.apiKey ? "That API key was rejected." : "This server needs an API key.", { kind: "error" }); askKey(); } });

async function refreshHealth() {
  health = await api.health();
  paintStatus();
  return health;
}

// ---- routing -------------------------------------------------------------------------------------
function route({ view, rest, params }) {
  const name = factories[view] ? view : "search";
  views[name] ||= factories[name](ctx);
  if (current && currentName !== name) current.hide?.();
  if (currentName !== name) { mount($("#main"), views[name].el); current = views[name]; currentName = name; }
  navEl.querySelectorAll("a").forEach((a) => (a.dataset.nav === name ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  views[name].show({ rest, ...params });
  scrollTo({ top: 0 });
}

// ---- keyboard ------------------------------------------------------------------------------------
addEventListener("keydown", (e) => {
  const t = e.target, typing = t.matches?.("input, textarea, select, [contenteditable]");
  if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
    e.preventDefault();
    if (currentName !== "search") location.hash = "#/search";
    setTimeout(() => views.search?.focus(), 0);
  }
});
$("#skip").addEventListener("click", (e) => { e.preventDefault(); $("#main").focus(); });

// ---- boot ----------------------------------------------------------------------------------------
applyTheme();
buildBar();
await refreshHealth();
buildBar();
paintStatus();
setInterval(refreshHealth, 30000);
if (health.auth_required && !prefs.apiKey) askKey();
onRoute(route);

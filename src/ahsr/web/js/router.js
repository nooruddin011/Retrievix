// Hash routing: #/search?q=...&mode=ask, #/library/<path>, #/evaluate. No server fallback needed.
export function parseHash(hash = location.hash) {
  const raw = hash.replace(/^#/, "") || "/";
  const [pathPart, query = ""] = raw.split("?");
  const segs = pathPart.split("/").filter(Boolean).map((s) => { try { return decodeURIComponent(s); } catch { return s; } });
  return { view: segs[0] || "search", rest: segs.slice(1).join("/"), params: Object.fromEntries(new URLSearchParams(query)) };
}

export function buildHash(view, { rest = "", params = {} } = {}) {
  const path = ["", view, ...rest.split("/").filter(Boolean).map(encodeURIComponent)].join("/");
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null)).toString();
  return `#${path}${qs ? "?" + qs : ""}`;
}

export const navigate = (hash) => { if (location.hash !== hash) location.hash = hash; else dispatchEvent(new HashChangeEvent("hashchange")); };
export const onRoute = (cb) => { addEventListener("hashchange", () => cb(parseHash())); cb(parseHash()); };

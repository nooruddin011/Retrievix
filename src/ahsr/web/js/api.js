import { prefs } from "./state.js";

export class ApiError extends Error {
  constructor(status, code, message, retryAfter = 0) { super(message); this.status = status; this.code = code; this.retryAfter = retryAfter; }
  /** Wording for people, not for logs. */
  get friendly() {
    if (this.code === "network") return "Can’t reach the server. Check that it’s running, then try again.";
    if (this.status === 429) return `You’re going a little fast. Try again in ${this.retryAfter || "a few"} seconds.`;
    if (this.status === 401) return "This server needs an API key.";
    if (this.status >= 500 && this.code === "internal_error") return "Something went wrong on the server. Try again in a moment.";
    return this.message;
  }
}

function headers(json) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  if (prefs.apiKey) h["X-API-Key"] = prefs.apiKey;
  return h;
}

async function toError(res) {
  let body = {};
  try { body = await res.json(); } catch { /* non-JSON error */ }
  const e = body.error || {};
  if (res.status === 401) dispatchEvent(new CustomEvent("hs:auth"));
  return new ApiError(res.status, e.code || "http_error", e.message || `Request failed (${res.status}).`, Number(res.headers.get("Retry-After")) || 0);
}

async function request(method, url, body, { signal, timeout = 30000 } = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(new DOMException("timeout", "TimeoutError")), timeout);
  signal?.addEventListener("abort", () => ctl.abort(signal.reason), { once: true });
  let res;
  try {
    res = await fetch(url, { method, headers: headers(body !== undefined), body: body === undefined ? undefined : JSON.stringify(body), signal: ctl.signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError(0, e?.name === "TimeoutError" || ctl.signal.aborted ? "timeout" : "network",
      ctl.signal.aborted ? "The request took too long." : "Can’t reach the server.");
  } finally { clearTimeout(timer); }
  if (!res.ok) throw await toError(res);
  return res.json();
}

const docUrl = (p) => "/documents/" + p.split("/").map(encodeURIComponent).join("/");

export const api = {
  async health() {                                        // 503 still carries a useful body
    try {
      const res = await fetch("/health", { headers: headers(false) });
      return { ...(await res.json()), reachable: true };
    } catch { return { reachable: false, status: "down" }; }
  },
  suggestions: (o) => request("GET", "/suggestions", undefined, o),
  route: (query, o) => request("POST", "/route", { query }, { timeout: 8000, ...o }),
  search: (query, mode = "hybrid", top_k = 6, o) => request("POST", "/search", { query, mode, top_k }, o),
  documents: (o) => request("GET", "/documents", undefined, o),
  document: (path, o) => request("GET", docUrl(path), undefined, o),
  saveDocument: (path, content, o) => request("PUT", docUrl(path), { content }, { timeout: 120000, ...o }),
  deleteDocument: (path, o) => request("DELETE", docUrl(path), undefined, o),
  reindex: (full = false, o) => request("POST", `/ingest?full=${full}`, undefined, { timeout: 300000, ...o }),
  evaluate: (k = 5, o) => request("POST", "/eval", { k }, { timeout: 300000, ...o }),

  /** Server-sent events over fetch (EventSource can neither POST nor send the API-key header). */
  async askStream(question, handlers, signal) {
    let res;
    try {
      res = await fetch("/ask/stream", { method: "POST", headers: headers(true), body: JSON.stringify({ question }), signal });
    } catch (e) {
      if (signal?.aborted) return;
      throw new ApiError(0, "network", "Can’t reach the server.");
    }
    if (!res.ok) throw await toError(res);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "", finished = false;
    const dispatch = (frame) => {
      let event = "message", data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) return;
      let payload; try { payload = JSON.parse(data); } catch { return; }
      if (event === "done" || event === "error") finished = true;
      handlers[event]?.(payload);
    };
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) { dispatch(buf.slice(0, idx)); buf = buf.slice(idx + 2); }
      }
    } catch (e) { if (signal?.aborted) return; }
    if (!finished && !signal?.aborted) handlers.error?.({ code: "stream_interrupted", message: "The connection dropped before the answer was ready." });
  },
};

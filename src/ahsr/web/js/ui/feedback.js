import { h, icon } from "../dom.js";

let host;
export function toast(message, { kind = "info", timeout = 4500 } = {}) {
  host ||= document.body.appendChild(h("div", { id: "toasts", role: "status", "aria-live": "polite" }));
  const t = h("div", { class: `toast ${kind}` }, icon(kind === "error" ? "alert" : kind === "ok" ? "check" : "info", 16), h("span", {}, message),
    h("button", { type: "button", class: "icon-btn sm", "aria-label": "Dismiss", onclick: () => t.remove() }, icon("x", 14)));
  host.append(t);
  if (timeout) setTimeout(() => t.remove(), timeout);
  return t;
}

export function errorBlock({ title = "Something went wrong", message, onRetry }) {
  return h("div", { class: "notice error", role: "alert" }, icon("alert", 18),
    h("div", { class: "notice-body" }, h("strong", {}, title), h("p", {}, message)),
    onRetry ? h("button", { type: "button", class: "btn", onclick: onRetry }, "Try again") : null);
}

export function notice(kind, title, message, actions = []) {
  return h("div", { class: `notice ${kind}` }, icon(kind === "warn" ? "alert" : "info", 18),
    h("div", { class: "notice-body" }, title ? h("strong", {}, title) : null, message ? h("p", {}, message) : null), ...actions);
}

export function emptyState({ title, body, actions = [] }) {
  return h("div", { class: "empty" }, h("h2", {}, title), body ? h("p", {}, body) : null, actions.length ? h("div", { class: "empty-actions" }, actions) : null);
}

/** Politely announce a result to screen readers (the visible UI updates are not live regions). */
export function announce(message) {
  const live = document.getElementById("sr-live");
  if (!live) return;
  live.textContent = "";
  setTimeout(() => { live.textContent = message; }, 50);
}

export function skeleton(lines = 3) {
  return h("div", { class: "skeleton", "aria-hidden": "true" }, Array.from({ length: lines }, (_, i) => h("i", { style: { width: `${92 - i * 14}%` } })));
}

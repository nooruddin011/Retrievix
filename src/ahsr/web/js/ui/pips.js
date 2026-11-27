// Two tiny bars per result: how high the Meaning engine (blue) and the Exact engine (amber) ranked it.
import { h } from "../dom.js";

const HEIGHT = [1, 0.8, 0.64, 0.5, 0.4];
const ordinal = (r) => (r ? `rank ${r}` : "not in its top results");

export function rankPips(ranks = {}) {
  const bar = (kind, rank) => h("i", { class: `pip ${kind}${rank ? "" : " absent"}`, style: { "--h": rank ? HEIGHT[rank - 1] ?? 0.3 : 0.1 } });
  const label = `Meaning engine: ${ordinal(ranks.dense)}. Exact engine: ${ordinal(ranks.sparse)}.`;
  return h("span", { class: "pips", role: "img", "aria-label": label, title: label }, bar("m", ranks.dense), bar("e", ranks.sparse));
}

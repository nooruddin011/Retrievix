"""Retrieval ablation: dense vs sparse vs hybrid (flat RRF) vs hybrid (router-weighted RRF).

Relevance is judged by source document. Metrics per query type and overall:
  Recall@k = fraction of the relevant sources found in the top-k ; MRR = 1/rank of the first relevant hit.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

MODES = ["dense", "sparse", "hybrid_flat", "hybrid"]


def score_query(hits, relevant: list[str], k: int) -> tuple[float, float]:
    sources = [h.source for h in hits[:k]]
    recall = sum(1 for r in relevant if r in sources) / len(relevant)
    mrr = next((1.0 / (i + 1) for i, s in enumerate(sources) if s in relevant), 0.0)
    return recall, mrr


def first_relevant_rank(hits, relevant: list[str], k: int) -> int | None:
    """1-based rank of the first relevant source within the top-k, or None."""
    return next((i + 1 for i, h in enumerate(hits[:k]) if h.source in relevant), None)


def evaluate_detailed(retriever, queries: list[dict], k: int = 5) -> dict:
    """Aggregates per mode and query type, plus a per-query breakdown for drill-down."""
    table: dict[str, dict[str, list[tuple[float, float]]]] = {m: defaultdict(list) for m in MODES}
    per_query = []
    for q in queries:
        row = {"query": q["query"], "type": q["type"], "relevant": q["relevant"], "modes": {}}
        for m in MODES:
            res = retriever.search(q["query"], top_k=k, mode=m)
            recall, mrr = score_query(res.hits, q["relevant"], k)
            table[m][q["type"]].append((recall, mrr))
            table[m]["overall"].append((recall, mrr))
            row["modes"][m] = {"rank": first_relevant_rank(res.hits, q["relevant"], k),
                               "recall": recall, "sources": [h.source for h in res.hits[:k]]}
        per_query.append(row)
    modes = {m: {t: {"recall": sum(x[0] for x in v) / len(v), "mrr": sum(x[1] for x in v) / len(v), "n": len(v)}
                 for t, v in by.items()} for m, by in table.items()}
    return {"k": k, "modes": modes, "queries": per_query}


def evaluate(retriever, queries: list[dict], k: int = 5) -> dict:
    """Aggregate table only: ``{mode: {query_type|'overall': {recall, mrr, n}}}``."""
    return evaluate_detailed(retriever, queries, k)["modes"]


def render(report: dict, k: int) -> str:
    types = ["identifier", "concept", "multi", "overall"]
    head = "| mode | " + " | ".join(f"{t} R@{k}/MRR" for t in types) + " |"
    rows = [head, "|" + "---|" * (len(types) + 1)]
    for m in MODES:
        cells = [f"{report[m][t]['recall']:.2f} / {report[m][t]['mrr']:.2f}" if t in report[m] else "-" for t in types]
        rows.append(f"| {m} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    from ahsr.config import get_settings
    from ahsr.container import build_container
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=get_settings().eval_file, help="labelled queries (default: EVAL_FILE)")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--min-hybrid-mrr", type=float, default=0.0, help="exit 1 if router-hybrid overall MRR is below this")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    c = build_container()
    qs = [json.loads(line) for line in Path(args.queries).read_text().splitlines() if line.strip()]
    rep = evaluate(c.retriever, qs, args.k)
    print(render(rep, args.k))
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2))
    if rep["hybrid"]["overall"]["mrr"] < args.min_hybrid_mrr:
        print(f"FAIL: hybrid MRR {rep['hybrid']['overall']['mrr']:.2f} < {args.min_hybrid_mrr}")
        sys.exit(1)

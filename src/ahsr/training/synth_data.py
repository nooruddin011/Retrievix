"""Build training data from your docs (no labels needed).

Outputs (JSONL):
  pairs.jsonl  : {"query","positive"}  -> train_dense.py / train_sparse.py
  router.jsonl : {"query","label"}     -> train_router.py   (1 = identifier lookup, 0 = conceptual)

Default queries are heuristic (identifiers mined from chunks + heading-derived questions).
Pass --llm to also have Claude write natural conceptual paraphrases per chunk (needs ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from ahsr.ingestion.ingest import load_chunks
from ahsr.router.heuristic import PATTERNS

ID_TEMPLATES = ["{x}", "{x}", "what does {x} mean", "{x} usage", "{x} not working", "fix {x}"]
CONCEPT_TEMPLATES = ["how do I {h}", "{h}", "what is the way to {h}", "help with {h}", "{h} not working"]


def mine_identifiers(text: str) -> set[str]:
    found: set[str] = set()
    for name, pat, _ in PATTERNS:
        if name in ("error_code", "cli_flag", "snake_case", "dotted_path"):
            found |= {m.group(0) for m in pat.finditer(text) if len(m.group(0)) > 3}
    return found


def llm_queries(chunk_text: str, n: int = 3) -> list[str]:
    import anthropic
    from ahsr.config import get_settings
    s = get_settings()
    r = anthropic.Anthropic(api_key=s.anthropic_api_key).messages.create(
        model=s.llm_model, max_tokens=300,
        messages=[{"role": "user", "content": f"Write {n} different questions a developer might type into a search "
                   f"box that this documentation passage answers. Do NOT reuse the passage's exact headings or "
                   f"identifiers; paraphrase the intent. Output ONLY a JSON array of strings.\n\n{chunk_text[:1500]}"}])
    m = re.search(r"\[.*\]", r.content[0].text, re.S)
    return json.loads(m.group(0)) if m else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="data/docs")
    ap.add_argument("--out", default="data/train")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    random.seed(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pairs, router = [], []
    for c in load_chunks(a.docs):
        heading = c.metadata["section"].split(" > ")[-1]
        h = re.sub(r"^[A-Z_0-9x]+:\s*", "", heading).lower()
        if not mine_identifiers(heading) and not re.search(r"[A-Z_]{3}|\d", heading):   # skip identifier headings
            q = random.choice(CONCEPT_TEMPLATES).format(h=h)
            pairs.append({"query": q, "positive": c.text})
            router.append({"query": q, "label": 0})
        for x in random.sample(sorted(mine_identifiers(c.text)), k=min(3, len(mine_identifiers(c.text)))):
            q = random.choice(ID_TEMPLATES).format(x=x)
            pairs.append({"query": q, "positive": c.text})
            router.append({"query": q, "label": 1})
        if a.llm:
            for q in llm_queries(c.text):
                pairs.append({"query": q, "positive": c.text})
                router.append({"query": q, "label": 0})
    for name, rows in (("pairs.jsonl", pairs), ("router.jsonl", router)):
        (out / name).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    print(f"wrote {len(pairs)} pairs and {len(router)} router examples to {out}/")


if __name__ == "__main__":
    main()

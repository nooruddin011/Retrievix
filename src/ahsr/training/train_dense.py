"""Fine-tune the dense bi-encoder with in-batch-negative contrastive loss (InfoNCE).

    python -m ahsr.training.train_dense --data data/train/pairs.jsonl --base BAAI/bge-small-en-v1.5 --out models/dense
Optional "negative" field per row adds a hard negative to the candidate pool.
"""
from __future__ import annotations

import argparse
import json
import random

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

from ahsr.models.dense import pool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--out", default="models/dense")
    ap.add_argument("--pooling", default="cls")
    ap.add_argument("--prefix", default="Represent this sentence for searching relevant passages: ")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--temp", type=float, default=0.05)
    a = ap.parse_args()

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok, model = AutoTokenizer.from_pretrained(a.base), AutoModel.from_pretrained(a.base).to(dev)
    rows = [json.loads(x) for x in open(a.data) if x.strip()]
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    steps = a.epochs * ((len(rows) + a.batch - 1) // a.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / max(1, 0.1 * steps)))

    def enc(texts, max_len):
        b = tok(texts, padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(dev)
        return F.normalize(pool(model(**b).last_hidden_state, b["attention_mask"], a.pooling), dim=-1)

    model.train()
    for ep in range(a.epochs):
        random.shuffle(rows)
        for i in range(0, len(rows), a.batch):
            batch = rows[i:i + a.batch]
            if len(batch) < 2:
                continue
            q = enc([a.prefix + r["query"] for r in batch], 64)
            docs = [r["positive"] for r in batch]
            if all(r.get("negative") for r in batch):
                docs += [r["negative"] for r in batch]
            d = enc(docs, 384)
            loss = F.cross_entropy(q @ d.T / a.temp, torch.arange(len(batch), device=dev))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
        print(f"epoch {ep + 1}/{a.epochs} last-batch loss {loss.item():.4f}")
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    print(f"saved -> {a.out}  (set DENSE_MODEL={a.out} DENSE_POOLING={a.pooling})")


if __name__ == "__main__":
    main()

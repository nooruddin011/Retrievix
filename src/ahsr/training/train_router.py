"""Train the query router: DistilBERT binary classifier (1 = exact-identifier lookup, 0 = conceptual).

    python -m ahsr.training.train_router --data data/train/router.jsonl --out models/router
"""
from __future__ import annotations

import argparse
import json
import random

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="distilbert-base-uncased")
    ap.add_argument("--out", default="models/router")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-5)
    a = ap.parse_args()
    random.seed(0)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.base)
    model = AutoModelForSequenceClassification.from_pretrained(a.base, num_labels=2).to(dev)
    rows = [json.loads(x) for x in open(a.data) if x.strip()]
    random.shuffle(rows)
    cut = max(1, int(0.1 * len(rows)))
    val, train = rows[:cut], rows[cut:]
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr)

    def batches(data, shuffle):
        data = random.sample(data, len(data)) if shuffle else data
        for i in range(0, len(data), a.batch):
            part = data[i:i + a.batch]
            enc = tok([r["query"] for r in part], padding=True, truncation=True, max_length=64,
                      return_tensors="pt").to(dev)
            yield enc, torch.tensor([r["label"] for r in part], device=dev)

    for ep in range(a.epochs):
        model.train()
        for enc, y in batches(train, True):
            loss = model(**enc, labels=y).loss
            loss.backward(); opt.step(); opt.zero_grad()
        model.eval()
        ok = 0
        with torch.inference_mode():
            for enc, y in batches(val, False):
                ok += (model(**enc).logits.argmax(-1) == y).sum().item()
        print(f"epoch {ep + 1}/{a.epochs} val acc {ok / len(val):.3f}")
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    print(f"saved -> {a.out}  (set ROUTER_MODEL={a.out})")


if __name__ == "__main__":
    main()

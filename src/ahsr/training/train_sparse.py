"""Fine-tune a SPLADE-style learned sparse encoder.

Loss = in-batch contrastive CE on sparse dot-products
       + lambda_q * FLOPS(query reps) + lambda_d * FLOPS(doc reps)      (quadratic warm-up)
FLOPS regulariser = sum_j (mean_i w_ij)^2 : pushes activations to be sparse, so the index stays small.

    python -m ahsr.training.train_sparse --data data/train/pairs.jsonl --out models/sparse
"""
from __future__ import annotations

import argparse
import json
import random

import torch
import torch.nn.functional as F
from transformers import AutoModelForMaskedLM, AutoTokenizer

from ahsr.models.sparse import splade_activations


def flops(w: torch.Tensor) -> torch.Tensor:
    return (w.abs().mean(dim=0) ** 2).sum()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="naver/splade-cocondenser-ensembledistil")
    ap.add_argument("--out", default="models/sparse")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--lambda-q", type=float, default=3e-4)
    ap.add_argument("--lambda-d", type=float, default=1e-4)
    a = ap.parse_args()

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok, model = AutoTokenizer.from_pretrained(a.base), AutoModelForMaskedLM.from_pretrained(a.base).to(dev)
    rows = [json.loads(x) for x in open(a.data) if x.strip()]
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr)
    total = a.epochs * ((len(rows) + a.batch - 1) // a.batch)
    step = 0

    def enc(texts, max_len):
        b = tok(texts, padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(dev)
        return splade_activations(model(**b).logits, b["attention_mask"])

    model.train()
    for ep in range(a.epochs):
        random.shuffle(rows)
        for i in range(0, len(rows), a.batch):
            batch = rows[i:i + a.batch]
            if len(batch) < 2:
                continue
            q, d = enc([r["query"] for r in batch], 64), enc([r["positive"] for r in batch], 256)
            ce = F.cross_entropy(q @ d.T, torch.arange(len(batch), device=dev))
            ramp = min(1.0, (step / max(1, 0.3 * total)) ** 2)
            loss = ce + ramp * (a.lambda_q * flops(q) + a.lambda_d * flops(d))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); opt.zero_grad(); step += 1
        nnz = (d > 0).sum(1).float().mean().item()
        print(f"epoch {ep + 1}/{a.epochs} ce={ce.item():.4f} avg doc nnz={nnz:.0f}")
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    print(f"saved -> {a.out}  (set SPARSE_MODEL={a.out})")


if __name__ == "__main__":
    main()

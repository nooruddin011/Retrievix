"""Fine-tuned transformer router (see training/train_router.py). Blended with the heuristic."""
from __future__ import annotations

from ahsr.config import Settings
from ahsr.router.heuristic import HeuristicRouter, RouteDecision, identifier_probability, to_decision


class TransformerRouter:
    def __init__(self, model_path: str, blend: float = 0.7, device: str | None = None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path).to(self.device).eval()
        self.blend = blend

    def route(self, query: str) -> RouteDecision:
        b = self.tok(query, truncation=True, max_length=64, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            p_model = float(self.model(**b).logits.softmax(-1)[0, 1])    # label 1 = identifier
        p_heur, reasons = identifier_probability(query)
        p = self.blend * p_model + (1 - self.blend) * p_heur
        return to_decision(p, [f"model={p_model:.2f}", *reasons])


def build_router(s: Settings):
    return TransformerRouter(s.router_model) if s.router_model else HeuristicRouter()

"""Query router: is this an exact technical identifier lookup or a conceptual question?

Outputs a *soft* weight (not a hard switch) that scales each engine's contribution to RRF,
so a misclassified query degrades gracefully instead of failing outright.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# (name, pattern, weight) -- evidence that the query is an exact-identifier lookup
PATTERNS = [
    ("error_code", re.compile(
        r"\b(?:ERR|ERROR|E|HTTP|ORA|SQLSTATE)?[_-]?0x[0-9A-Fa-f]{3,}\b"
        r"|\b[A-Z]{2,}[_-][A-Z0-9_]{3,}\b|\b[A-Z]{1,4}\d{3,5}\b"), 3.0),
    ("cli_flag", re.compile(r"(?<![\w-])--?[A-Za-z][\w-]*"), 2.5),
    ("call_signature", re.compile(r"[\w.]+\([^)]*\)"), 3.0),
    ("snake_case", re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b"), 2.0),
    ("dotted_path", re.compile(r"\b[a-z]{2,}(?:\.[a-z_]{2,})+\b"), 2.0),
    ("camel_case", re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b|\b(?:[A-Z][a-z0-9]+){2,}\b"), 2.0),
    ("backtick", re.compile(r"`[^`]+`"), 1.5),
    ("path_or_version", re.compile(r"[\w.-]*/[\w./-]+|\bv?\d+\.\d+(?:\.\d+)+\b"), 1.5),
]
NL_WORDS = {"how", "why", "what", "when", "which", "should", "can", "could", "do", "does", "is",
            "are", "to", "i", "my", "way", "best", "without", "keeps", "get", "getting"}


@dataclass
class RouteDecision:
    label: str                      # identifier | conceptual | mixed
    p_identifier: float
    sparse_weight: float
    dense_weight: float
    reasons: list[str] = field(default_factory=list)


def to_decision(p: float, reasons: list[str]) -> RouteDecision:
    p_c = min(0.9, max(0.1, p))     # clamp so neither engine is ever silenced
    label = "identifier" if p >= 0.65 else "conceptual" if p <= 0.35 else "mixed"
    return RouteDecision(label, round(p, 3), round(2 * p_c, 3), round(2 * (1 - p_c), 3), reasons)


def identifier_probability(query: str) -> tuple[float, list[str]]:
    reasons, z = [], -0.5
    for name, pat, w in PATTERNS:
        if pat.search(query):
            z += w
            reasons.append(name)
    nl = sum(1 for t in re.findall(r"[a-z']+", query.lower()) if t in NL_WORDS)
    if nl:
        z -= min(3.0, 0.7 * nl)
        reasons.append(f"nl_words={nl}")
    return 1 / (1 + math.exp(-z)), reasons


class HeuristicRouter:
    def route(self, query: str) -> RouteDecision:
        p, reasons = identifier_probability(query)
        return to_decision(p, reasons)

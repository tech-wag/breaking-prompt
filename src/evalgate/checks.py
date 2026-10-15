"""
Checks, arranged as a test pyramid.

    deterministic  cheap, exact, no model calls (string, regex, JSON, length)
    semantic       meaning-level comparison against a reference answer
    judge          an LLM grades the output against a rubric (slowest, priciest)

Write your checks in that order inside a test. The first failing check stops
the sample, so expensive judge calls only happen when the cheap layers pass,
and every failure is attributed to the layer that caught it.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Callable, Iterable

LAYERS = ("deterministic", "semantic", "judge")


class CheckFailed(AssertionError):
    def __init__(self, layer: str, message: str):
        super().__init__(message)
        self.layer = layer


def _fail(layer: str, msg: str, text: str):
    snippet = text if len(text) <= 160 else text[:157] + "..."
    raise CheckFailed(layer, f"{msg} | output: {snippet!r}")


# --------------------------------------------------------------------------- #
# Layer 1: deterministic                                                      #
# --------------------------------------------------------------------------- #
def contains(text: str, needle: str, *, case: bool = False) -> None:
    hay, ndl = (text, needle) if case else (text.lower(), needle.lower())
    if ndl not in hay:
        _fail("deterministic", f"expected to contain {needle!r}", text)


def contains_any(text: str, needles: Iterable[str], *, case: bool = False) -> None:
    needles = list(needles)
    hay = text if case else text.lower()
    if not any((n if case else n.lower()) in hay for n in needles):
        _fail("deterministic", f"expected any of {needles!r}", text)


def not_contains(text: str, needle: str, *, case: bool = False) -> None:
    hay, ndl = (text, needle) if case else (text.lower(), needle.lower())
    if ndl in hay:
        _fail("deterministic", f"must not contain {needle!r}", text)


def matches(text: str, pattern: str, flags: int = re.IGNORECASE) -> re.Match:
    m = re.search(pattern, text, flags)
    if not m:
        _fail("deterministic", f"expected to match /{pattern}/", text)
    return m


def not_matches(text: str, pattern: str, flags: int = re.IGNORECASE) -> None:
    m = re.search(pattern, text, flags)
    if m:
        _fail("deterministic", f"must not match /{pattern}/ (found {m.group(0)!r})", text)


def max_words(text: str, n: int) -> None:
    count = len(text.split())
    if count > n:
        _fail("deterministic", f"expected at most {n} words, got {count}", text)


def is_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        _fail("deterministic", f"expected valid JSON ({e.msg})", text)


# --------------------------------------------------------------------------- #
# Layer 2: semantic                                                           #
# --------------------------------------------------------------------------- #
_STOP = set("a an the and or of to in on for is are be it this that you your we our i with "
            "as at by from can will up any".split())


def _tokens(s: str) -> Counter:
    words = re.findall(r"[a-z0-9]+", s.lower())
    return Counter(w.rstrip("s") for w in words if w not in _STOP)


def lexical_similarity(a: str, b: str) -> float:
    """Cosine similarity over word counts. Offline and dependency-free.

    Good enough to catch an answer that drifted off-topic. For paraphrase-level
    comparison, plug in an embedding model with set_similarity().
    """
    ta, tb = _tokens(a), _tokens(b)
    dot = sum(ta[w] * tb[w] for w in ta)
    na = math.sqrt(sum(v * v for v in ta.values()))
    nb = math.sqrt(sum(v * v for v in tb.values()))
    return dot / (na * nb) if na and nb else 0.0


_similarity: Callable[[str, str], float] = lexical_similarity


def set_similarity(fn: Callable[[str, str], float]) -> None:
    """Swap in your own scorer, e.g. cosine similarity of embeddings."""
    global _similarity
    _similarity = fn


def similar_to(text: str, reference: str, *, min_score: float = 0.35) -> float:
    score = _similarity(text, reference)
    if score < min_score:
        _fail("semantic", f"similarity {score:.2f} < {min_score:.2f} to reference", text)
    return score


# --------------------------------------------------------------------------- #
# Layer 3: LLM-as-judge                                                       #
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = (
    "You are a strict grader for a customer-support assistant. "
    "Read the rubric and the response. Reply with exactly one line: "
    "PASS, or FAIL: <short reason>."
)


def judge(text: str, rubric: str, *, model=None) -> None:
    """Ask a judge model to grade `text` against `rubric`.

    The judge defaults to the model configured with --evalgate-judge (or the
    one under test). Its cost is recorded against the sample like any call.
    """
    from .case import current_judge

    jm = model or current_judge()
    if jm is None:
        raise RuntimeError("no judge model configured (use --evalgate-judge or pass model=)")
    prompt = f"<rubric>\n{rubric}\n</rubric>\n<response>\n{text}\n</response>"
    verdict = jm.complete(JUDGE_SYSTEM, prompt, temperature=0.0, max_tokens=60).text.strip()
    if not verdict.upper().startswith("PASS"):
        _fail("judge", f"judge said {verdict!r}", text)

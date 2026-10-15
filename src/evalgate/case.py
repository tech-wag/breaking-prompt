"""
@eval_case: turn an ordinary pytest test into a repeated, scored eval.

    @eval_case(samples=10, threshold=0.9, budget={"cost_usd": 0.004})
    def test_fraud_over_1000_escalates(peach):
        reply = peach("Someone charged $2,400 on my card that I didn't make.")
        checks.contains_any(reply, ["human agent", "specialist"])

The body runs `samples` times. Each run is one sample; a failing check marks
that sample failed (and records which pyramid layer caught it). After all
samples, the case gets a verdict (PASS / FAIL / FLAKY) and a budget check.
"""
from __future__ import annotations

import contextvars
import functools
import statistics
from dataclasses import asdict, dataclass, field

import pytest

from .checks import LAYERS, CheckFailed
from .models import Completion
from .stats import FAIL, FLAKY, verdict, wilson_interval


# --------------------------------------------------------------------------- #
# Session-wide settings (filled in by the pytest plugin)                      #
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    samples_override: int | None = None
    strict_flaky: bool = False
    judge: object = None


SETTINGS = Settings()
REGISTRY: dict[str, "CaseResult"] = {}

_nodeid = contextvars.ContextVar("evalgate_nodeid", default="<unknown>")
_sample = contextvars.ContextVar("evalgate_sample", default=None)


@dataclass
class _SampleState:
    index: int
    calls: list[Completion] = field(default_factory=list)


def current_sample_index() -> int:
    s = _sample.get()
    return s.index if s else 0


def record_call(c: Completion) -> None:
    s = _sample.get()
    if s is not None:
        s.calls.append(c)


def current_judge():
    return SETTINGS.judge


# --------------------------------------------------------------------------- #
# Results                                                                     #
# --------------------------------------------------------------------------- #
@dataclass
class CaseResult:
    nodeid: str
    layer: str
    samples: int
    passes: int
    threshold: float
    verdict: str
    ci_low: float
    ci_high: float
    failed_by_layer: dict
    cost_usd_per_sample: float
    tokens_per_sample: float
    latency_s_per_call: float
    budget: dict
    budget_violations: list
    example_failure: str | None

    @property
    def pass_rate(self) -> float:
        return self.passes / self.samples if self.samples else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pass_rate"] = round(self.pass_rate, 4)
        return d


def _mean(xs):
    return statistics.fmean(xs) if xs else 0.0


def eval_case(samples: int = 10, threshold: float = 0.9, layer: str = "deterministic",
              budget: dict | None = None):
    """Decorate a pytest test to run it as a sampled eval.

    samples    how many times to run the body (override: --evalgate-samples)
    threshold  pass rate the case must reach
    layer      pyramid layer of the test's most expensive check; used to order
               the run (cheap first) and to skip with --evalgate-max-layer
    budget     per-sample limits: {"cost_usd": ..., "tokens": ..., "latency_s": ...}
               (latency is per model call)
    """
    if layer not in LAYERS:
        raise ValueError(f"layer must be one of {LAYERS}")
    budget = dict(budget or {})

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            n = SETTINGS.samples_override or samples
            passes, by_layer, example = 0, {}, None
            costs, tokens, latencies = [], [], []

            for i in range(n):
                state = _SampleState(i)
                tok = _sample.set(state)
                try:
                    fn(*args, **kwargs)
                    passes += 1
                except CheckFailed as e:
                    by_layer[e.layer] = by_layer.get(e.layer, 0) + 1
                    example = example or str(e)
                except AssertionError as e:          # plain asserts count at the case's layer
                    by_layer[layer] = by_layer.get(layer, 0) + 1
                    example = example or (str(e) or "assertion failed")
                finally:
                    _sample.reset(tok)
                costs.append(sum(c.cost_usd for c in state.calls))
                tokens.append(sum(c.input_tokens + c.output_tokens for c in state.calls))
                latencies.extend(c.latency_s for c in state.calls)

            lo, hi = wilson_interval(passes, n)
            res = CaseResult(
                nodeid=_nodeid.get(), layer=layer, samples=n, passes=passes,
                threshold=threshold, verdict=verdict(passes, n, threshold),
                ci_low=round(lo, 4), ci_high=round(hi, 4), failed_by_layer=by_layer,
                cost_usd_per_sample=_mean(costs), tokens_per_sample=_mean(tokens),
                latency_s_per_call=_mean(latencies), budget=budget,
                budget_violations=[], example_failure=example)

            limits = {"cost_usd": res.cost_usd_per_sample, "tokens": res.tokens_per_sample,
                      "latency_s": res.latency_s_per_call}
            for key, limit in budget.items():
                if limits.get(key, 0) > limit:
                    res.budget_violations.append(f"{key} {limits[key]:.4g} > budget {limit:.4g}")
            REGISTRY[res.nodeid] = res

            head = f"{passes}/{n} samples passed (needs {threshold:.0%})"
            if res.verdict == FAIL:
                pytest.fail(f"FAIL: {head}\n  first failure: {example}", pytrace=False)
            if res.budget_violations:
                pytest.fail(f"OVER BUDGET: {'; '.join(res.budget_violations)}", pytrace=False)
            if res.verdict == FLAKY and SETTINGS.strict_flaky:
                pytest.fail(f"FLAKY (strict mode): {head}\n  first failure: {example}", pytrace=False)

        wrapper._evalgate = {"layer": layer, "samples": samples, "threshold": threshold}
        return wrapper

    return deco

"""Run files, baseline comparison, and the pull-request report."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .stats import FAIL, FLAKY, PASS, fisher_one_sided

ALPHA = 0.05


# --------------------------------------------------------------------------- #
# Run files                                                                   #
# --------------------------------------------------------------------------- #
def _git_sha() -> str | None:
    if os.getenv("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"][:7]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def build_run(cases: dict, model: str, suite: str) -> dict:
    return {
        "evalgate": 1,
        "suite": suite,
        "model": model,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "cases": {k: v.to_dict() for k, v in cases.items()},   # run order: cheap layers first
    }


def save(run: dict, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")


def load(path: str | Path) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def suite_cost(run: dict) -> float:
    return sum(c["cost_usd_per_sample"] for c in run["cases"].values())


def mean_latency(run: dict) -> float:
    xs = [c["latency_s_per_call"] for c in run["cases"].values() if c["latency_s_per_call"]]
    return sum(xs) / len(xs) if xs else 0.0


def counts(run: dict) -> dict:
    out = {PASS: 0, FAIL: 0, FLAKY: 0}
    for c in run["cases"].values():
        out[c["verdict"]] += 1
    return out


# --------------------------------------------------------------------------- #
# Comparison                                                                  #
# --------------------------------------------------------------------------- #
@dataclass
class CaseDiff:
    nodeid: str
    status: str            # REGRESSED, IMPROVED, UNCHANGED, NEW, REMOVED
    base: dict | None
    cur: dict | None
    p_value: float | None = None


@dataclass
class Comparison:
    diffs: list[CaseDiff] = field(default_factory=list)
    cost_change: float | None = None      # fractional, e.g. -0.31
    cost_tolerance: float = 0.20

    @property
    def regressions(self):
        return [d for d in self.diffs if d.status == "REGRESSED"]

    @property
    def improvements(self):
        return [d for d in self.diffs if d.status == "IMPROVED"]

    @property
    def cost_regressed(self) -> bool:
        return self.cost_change is not None and self.cost_change > self.cost_tolerance

    @property
    def gate_failed(self) -> bool:
        return bool(self.regressions) or self.cost_regressed


def compare(base: dict, cur: dict, cost_tolerance: float = 0.20) -> Comparison:
    comp = Comparison(cost_tolerance=cost_tolerance)
    for nid in sorted(set(base["cases"]) | set(cur["cases"])):
        b, c = base["cases"].get(nid), cur["cases"].get(nid)
        if b is None:
            comp.diffs.append(CaseDiff(nid, "NEW", None, c))
            continue
        if c is None:
            comp.diffs.append(CaseDiff(nid, "REMOVED", b, None))
            continue
        p_down = fisher_one_sided(b["passes"], b["samples"], c["passes"], c["samples"])
        p_up = fisher_one_sided(c["passes"], c["samples"], b["passes"], b["samples"])
        newly_failing = b["verdict"] != FAIL and c["verdict"] == FAIL
        if (c["pass_rate"] < b["pass_rate"] and p_down < ALPHA) or newly_failing:
            comp.diffs.append(CaseDiff(nid, "REGRESSED", b, c, p_down))
        elif (c["pass_rate"] > b["pass_rate"] and p_up < ALPHA) or (b["verdict"] == FAIL and c["verdict"] == PASS):
            comp.diffs.append(CaseDiff(nid, "IMPROVED", b, c, p_up))
        else:
            comp.diffs.append(CaseDiff(nid, "UNCHANGED", b, c, p_down))
    bc = suite_cost(base)
    if bc > 0:
        comp.cost_change = suite_cost(cur) / bc - 1
    return comp


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #
def short(nodeid: str) -> str:
    return nodeid.split("::")[-1]


def _pct(x: float) -> str:
    return f"{x * 100:+.0f}%"


def _rate(c: dict | None) -> str:
    return "—" if c is None else f"{c['passes']}/{c['samples']}"


def render_markdown(cur: dict, comp: Comparison | None, base: dict | None) -> str:
    n_cases = len(cur["cases"])
    samples = {c["samples"] for c in cur["cases"].values()}
    s_txt = f"{samples.pop()} samples each" if len(samples) == 1 else "varied samples"
    lines = [f"## evalgate · {cur['suite']}", ""]

    if comp is None:
        cnt = counts(cur)
        status = "FAILED" if cnt[FAIL] else "PASSED"
        lines += [f"**Gate: {'❌' if cnt[FAIL] else '✅'} {status}** · no baseline to compare against", ""]
    else:
        reasons = []
        if comp.regressions:
            reasons.append(f"{len(comp.regressions)} regression{'s' * (len(comp.regressions) > 1)}")
        if comp.cost_regressed:
            reasons.append(f"cost {_pct(comp.cost_change)} (tolerance {_pct(comp.cost_tolerance)})")
        if comp.gate_failed:
            head = "**Gate: ❌ FAILED** · " + ", ".join(reasons)
        else:
            head = "**Gate: ✅ PASSED** · no regressions"
        if comp.cost_change is not None and not comp.cost_regressed:
            head += f" · cost {_pct(comp.cost_change)}"
        lines += [head, ""]

    sha = f" `{base['git_sha']}`" if base and base.get("git_sha") else ""
    lines += [f"Model `{cur['model']}` · {n_cases} cases, {s_txt}"
              + (f" · compared with baseline{sha}" if base else ""), ""]

    cc = counts(cur)
    if base:
        bc_ = counts(base)
        bcost, ccost = suite_cost(base), suite_cost(cur)
        cost_cell = f"${ccost:.4f}" + (f" ({_pct(ccost / bcost - 1)})" if bcost else "")
        lines += ["| | Baseline | This change |", "|---|---|---|",
                  f"| Passing | {bc_[PASS]} | {cc[PASS]} |",
                  f"| Failing | {bc_[FAIL]} | {cc[FAIL]} |",
                  f"| Flaky (quarantined) | {bc_[FLAKY]} | {cc[FLAKY]} |",
                  f"| Cost per suite pass | ${bcost:.4f} | {cost_cell} |",
                  f"| Mean latency per call | {mean_latency(base):.2f} s | {mean_latency(cur):.2f} s |", ""]
    else:
        lines += [f"Passing {cc[PASS]} · Failing {cc[FAIL]} · Flaky {cc[FLAKY]} · "
                  f"cost per suite pass ${suite_cost(cur):.4f}", ""]

    if comp and comp.regressions:
        lines += ["### ❌ Regressions", "",
                  "| Case | Baseline | This change | p-value | First failure |", "|---|---|---|---|---|"]
        for d in comp.regressions:
            ex = (d.cur.get("example_failure") or "").replace("|", "\\|")
            ex = ex if len(ex) < 140 else ex[:137] + "..."
            p = "<0.0001" if d.p_value < 1e-4 else f"{d.p_value:.4f}"
            lines.append(f"| `{short(d.nodeid)}` | {_rate(d.base)} | {_rate(d.cur)} | {p} | {ex} |")
        lines.append("")

    flaky = [(k, c) for k, c in cur["cases"].items() if c["verdict"] == FLAKY]
    if flaky:
        lines += ["### ⚠️ Flaky, quarantined (not blocking)", ""]
        for k, c in flaky:
            lines.append(f"- `{short(k)}`: {_rate(c)} passed, needs {c['threshold']:.0%} "
                         f"(95% CI {c['ci_low']:.0%}–{c['ci_high']:.0%}). Too noisy to call; "
                         f"add samples or tighten the prompt.")
        lines.append("")

    over = [(k, c) for k, c in cur["cases"].items() if c["budget_violations"]]
    if over:
        lines += ["### 💸 Over budget", ""]
        lines += [f"- `{short(k)}`: {'; '.join(c['budget_violations'])}" for k, c in over]
        lines.append("")

    if comp and comp.improvements:
        lines += ["### ✅ Improved", ""]
        lines += [f"- `{short(d.nodeid)}`: {_rate(d.base)} → {_rate(d.cur)}" for d in comp.improvements]
        lines.append("")

    lines += ["<details><summary>All cases</summary>", "",
              "| Case | Layer | Passed | 95% CI | Verdict | Cost / sample |", "|---|---|---|---|---|---|"]
    for k, c in cur["cases"].items():
        lines.append(f"| `{short(k)}` | {c['layer']} | {_rate(c)} | {c['ci_low']:.0%}–{c['ci_high']:.0%} | "
                     f"{c['verdict']} | ${c['cost_usd_per_sample']:.5f} |")
    lines += ["", "</details>", "",
              "<sub>PASS: met its threshold. FAIL: the 95% interval is entirely below the threshold. "
              "FLAKY: below the threshold but inconclusive. A regression is a one-sided Fisher exact "
              f"p < {ALPHA} against the baseline, or a case that newly fails.</sub>", ""]
    return "\n".join(lines)

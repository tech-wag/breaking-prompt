"""
The statistics behind every verdict. Standard library only.

LLM outputs are random, so a single run of a test tells you very little.
evalgate runs each case N times and asks two questions a QA engineer cares about:

1. Verdict: given k passes out of n, did this case meet its bar?
       PASS   observed pass rate >= threshold
       FAIL   even the optimistic end of the confidence interval is below the bar
       FLAKY  below the bar, but too noisy to call: quarantine and investigate
2. Regression: is the pass rate on this branch genuinely lower than on the
   baseline, or is the drop just noise? (one-sided Fisher exact test)
"""
from __future__ import annotations

import math

PASS, FAIL, FLAKY = "PASS", "FAIL", "FLAKY"


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a pass rate of k/n.

    Better behaved than the textbook normal approximation at small n and at
    rates near 0 or 1, which is exactly where eval suites live.
    """
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def verdict(k: int, n: int, threshold: float) -> str:
    if n == 0:
        return FAIL
    if k / n >= threshold:
        return PASS
    _, hi = wilson_interval(k, n)
    return FAIL if hi < threshold else FLAKY


def fisher_one_sided(base_k: int, base_n: int, cur_k: int, cur_n: int) -> float:
    """P-value for H1: the current pass rate is LOWER than the baseline's.

    Exact hypergeometric tail: with the total number of passes fixed, how
    likely is it that the current run got this few (or fewer) of them by chance?
    """
    total_k = base_k + cur_k
    total_n = base_n + cur_n
    if cur_n == 0 or base_n == 0:
        return 1.0
    denom = math.comb(total_n, cur_n)
    lo = max(0, cur_n - (total_n - total_k))
    p = 0.0
    for x in range(lo, cur_k + 1):
        p += math.comb(total_k, x) * math.comb(total_n - total_k, cur_n - x)
    return min(1.0, p / denom)

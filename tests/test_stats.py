import pytest

from evalgate.stats import FAIL, FLAKY, PASS, fisher_one_sided, verdict, wilson_interval


def test_wilson_matches_known_values():
    lo, hi = wilson_interval(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-3) and hi == 1.0
    lo, hi = wilson_interval(7, 10)
    assert lo == pytest.approx(0.3968, abs=1e-3) and hi == pytest.approx(0.8922, abs=1e-3)


@pytest.mark.parametrize("k,n,thr,expected", [
    (10, 10, 0.9, PASS), (9, 10, 0.9, PASS),
    (8, 10, 0.9, FLAKY),            # below the bar, but the interval still reaches it
    (7, 10, 0.9, FAIL),             # upper bound 0.89 < 0.9
    (7, 10, 0.8, FLAKY), (0, 10, 0.9, FAIL), (0, 0, 0.9, FAIL),
])
def test_verdicts(k, n, thr, expected):
    assert verdict(k, n, thr) == expected


def test_fisher_detects_real_drops_but_not_noise():
    assert fisher_one_sided(10, 10, 0, 10) < 1e-4
    assert fisher_one_sided(10, 10, 3, 10) < 0.01
    assert fisher_one_sided(10, 10, 9, 10) > 0.4          # one miss is noise
    assert fisher_one_sided(5, 10, 10, 10) == pytest.approx(1.0)

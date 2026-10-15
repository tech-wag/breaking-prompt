"""End-to-end tests of the plugin, each in a fresh pytest subprocess."""
import json

import pytest

pytest_plugins = ["pytester"]

CONFTEST = '''
import os
from evalgate import register_model, ScriptedModel, Price

def respond(system, user, i):
    rate = float(os.environ.get("RATE", "1.0"))
    pad = " word" * int(os.environ.get("WORDS", "5"))
    return ("yes" if i < round(rate * 10) else "no") + pad, 0.1

register_model("mock", lambda _: ScriptedModel("fake", respond, Price(1.0, 1.0)))
'''

TESTS = '''
import os
from evalgate import eval_case, checks as c

@eval_case(samples=10, threshold=float(os.environ.get("THR", "0.9")),
           budget={"tokens": float(os.environ.get("TOKEN_BUDGET", "1e9"))})
def test_says_yes(evalgate_model):
    c.contains(evalgate_model.complete("sys", "hi").text, "yes")

@eval_case(samples=2, threshold=1.0, layer="judge")
def test_expensive(evalgate_model):
    c.contains(evalgate_model.complete("sys", "hi").text, "word")
'''


@pytest.fixture
def suite(pytester):
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_suite=TESTS)
    return pytester


def run(suite, monkeypatch, *args, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return suite.runpytest_subprocess("-p", "no:cacheprovider", "--evalgate-baseline", "base.json", *args)


def test_flaky_is_reported_but_not_blocking(suite, monkeypatch):
    r = run(suite, monkeypatch, RATE=0.8)
    outcomes = r.parseoutcomes()
    assert outcomes.get("passed") == 1 and outcomes.get("flaky") == 1
    assert r.ret == 0


def test_strict_mode_fails_flaky(suite, monkeypatch):
    run(suite, monkeypatch, "--evalgate-strict", RATE=0.8).assert_outcomes(passed=1, failed=1)


def test_regression_fails_the_gate_even_when_tests_pass(suite, monkeypatch):
    run(suite, monkeypatch, "--evalgate-update-baseline", RATE=1.0)
    r = run(suite, monkeypatch, "--evalgate-report", "report.md", RATE=0.3, THR=0.2)
    r.assert_outcomes(passed=2)                      # 3/10 clears the 20% bar...
    assert r.ret == 1                                # ...but it's a real drop from 10/10
    r.stdout.fnmatch_lines(["*GATE FAILED*1 regression*"])
    report = (suite.path / "report.md").read_text()
    assert "Gate: ❌ FAILED" in report and "### ❌ Regressions" in report and "test_says_yes" in report


def test_cost_increase_beyond_tolerance_fails(suite, monkeypatch):
    run(suite, monkeypatch, "--evalgate-update-baseline", WORDS=5)
    r = run(suite, monkeypatch, WORDS=40)
    assert r.ret == 1
    r.stdout.fnmatch_lines(["*GATE FAILED*cost over tolerance*"])


def test_budget_violation_fails_the_case(suite, monkeypatch):
    r = run(suite, monkeypatch, TOKEN_BUDGET=3)
    r.assert_outcomes(failed=1, passed=1)
    r.stdout.fnmatch_lines(["*OVER BUDGET*tokens*"])


def test_max_layer_skips_expensive_tests(suite, monkeypatch):
    r = run(suite, monkeypatch, "--evalgate-max-layer", "deterministic")
    r.assert_outcomes(passed=1, skipped=1)


def test_run_file_is_written(suite, monkeypatch):
    run(suite, monkeypatch, "--evalgate-out", "out.json", RATE=1.0)
    data = json.loads((suite.path / "out.json").read_text())
    case = data["cases"]["test_suite.py::test_says_yes"]
    assert case["passes"] == 10 and case["verdict"] == "PASS" and data["model"] == "fake"

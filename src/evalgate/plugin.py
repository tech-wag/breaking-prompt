"""
The pytest plugin. Registered through the `pytest11` entry point, so it is
active as soon as the package is installed.

What it adds to a normal pytest run:
  * a `evalgate_model` fixture (the model under test, with call recording)
  * cheap-first ordering of eval tests (deterministic -> semantic -> judge)
  * a FLAKY outcome next to passed / failed
  * a results file, a baseline comparison and a Markdown report
  * a non-zero exit code when quality regresses against the baseline
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from . import results
from .case import REGISTRY, SETTINGS, _nodeid
from .checks import LAYERS
from .models import RecordingModel, load_model


class _LazyModel:
    """Defers load_model() until first use, so conftest files can register mocks."""

    loaded_name: str | None = None      # name of the model under test, for reports

    def __init__(self, spec: str, under_test: bool = False):
        self.spec = spec
        self.under_test = under_test
        self._m = None

    @property
    def model(self):
        if self._m is None:
            self._m = RecordingModel(load_model(self.spec))
            if self.under_test:
                _LazyModel.loaded_name = self._m.name
        return self._m

    @property
    def name(self):
        return self.model.name

    def complete(self, system, user, **kw):
        return self.model.complete(system, user, **kw)


def pytest_addoption(parser):
    g = parser.getgroup("evalgate", "LLM eval gating")
    g.addoption("--evalgate-model", default=os.getenv("EVALGATE_MODEL", "mock"),
                help="model under test: mock | anthropic:<id> | openai:<id> | gemini:<id>")
    g.addoption("--evalgate-judge", default=os.getenv("EVALGATE_JUDGE"),
                help="judge model for checks.judge (default: the model under test)")
    g.addoption("--evalgate-samples", type=int, default=None, help="override samples per case")
    g.addoption("--evalgate-strict", action="store_true", help="treat FLAKY cases as failures")
    g.addoption("--evalgate-max-layer", choices=LAYERS, default="judge",
                help="skip eval tests above this pyramid layer (e.g. 'deterministic' for a fast run)")
    g.addoption("--evalgate-out", default=".evalgate/last-run.json", help="where to write this run")
    g.addoption("--evalgate-baseline", default=None, help="baseline run to compare against")
    g.addoption("--evalgate-update-baseline", action="store_true",
                help="write this run as the new baseline (like updating snapshots)")
    g.addoption("--evalgate-report", default=None, help="write a Markdown report (e.g. for a PR comment)")
    g.addoption("--evalgate-cost-tolerance", type=float, default=0.20,
                help="fail the gate if suite cost rises by more than this fraction (default 0.20)")
    parser.addini("evalgate_baseline", "default baseline path", default="evals/baseline.json")
    parser.addini("evalgate_suite", "suite name shown in reports", default="eval suite")


def pytest_configure(config):
    SETTINGS.samples_override = config.getoption("--evalgate-samples")
    SETTINGS.strict_flaky = config.getoption("--evalgate-strict")
    judge_spec = config.getoption("--evalgate-judge") or config.getoption("--evalgate-model")
    SETTINGS.judge = _LazyModel(judge_spec)
    REGISTRY.clear()
    _LazyModel.loaded_name = None


@pytest.fixture(scope="session")
def evalgate_model(pytestconfig):
    """The model under test. Every call is recorded for cost and latency budgets."""
    return _LazyModel(pytestconfig.getoption("--evalgate-model"), under_test=True)


def _meta(item):
    return getattr(getattr(item, "obj", None), "_evalgate", None)


def pytest_collection_modifyitems(config, items):
    max_rank = LAYERS.index(config.getoption("--evalgate-max-layer"))
    rank = lambda it: LAYERS.index(_meta(it)["layer"]) if _meta(it) else -1  # noqa: E731
    items.sort(key=rank)                        # stable: cheap layers run first
    for it in items:
        m = _meta(it)
        if m and LAYERS.index(m["layer"]) > max_rank:
            it.add_marker(pytest.mark.skip(reason=f"evalgate: layer '{m['layer']}' above max layer"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    tok = _nodeid.set(item.nodeid)
    try:
        yield
    finally:
        _nodeid.reset(tok)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    res = REGISTRY.get(item.nodeid)
    if rep.when == "call" and res is not None and rep.passed and res.verdict == "FLAKY":
        rep.evalgate_flaky = True


def pytest_report_teststatus(report, config):
    if getattr(report, "evalgate_flaky", False) and report.when == "call":
        return "flaky", "~", ("FLAKY", {"yellow": True})


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not REGISTRY:
        return
    suite = config.getini("evalgate_suite")
    model = _LazyModel.loaded_name or config.getoption("--evalgate-model")
    run = results.build_run(REGISTRY, model, suite)
    results.save(run, config.getoption("--evalgate-out"))

    base_path = config.getoption("--evalgate-baseline") or config.getini("evalgate_baseline")
    base_path = Path(config.rootpath, base_path) if not Path(base_path).is_absolute() else Path(base_path)
    update = config.getoption("--evalgate-update-baseline")
    base = None if update else results.load(base_path)
    comp = results.compare(base, run, config.getoption("--evalgate-cost-tolerance")) if base else None

    if update:
        results.save(run, base_path)
    report_path = config.getoption("--evalgate-report")
    if report_path:
        Path(report_path).write_text(results.render_markdown(run, comp, base))

    config._evalgate = {"run": run, "comp": comp, "base": base, "updated": base_path if update else None}
    if comp is not None and comp.gate_failed and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    info = getattr(config, "_evalgate", None)
    if not info:
        return
    tr, run, comp = terminalreporter, info["run"], info["comp"]
    tr.write_sep("=", f"evalgate: {run['suite']} ({run['model']})")
    diff_by_id = {d.nodeid: d for d in comp.diffs} if comp else {}
    width = max(len(results.short(k)) for k in run["cases"])
    for k, c in run["cases"].items():
        status = diff_by_id[k].status if k in diff_by_id else ""
        color = {"PASS": {"green": True}, "FAIL": {"red": True}, "FLAKY": {"yellow": True}}[c["verdict"]]
        tr.write(f"  {results.short(k):<{width}}  {c['passes']:>3}/{c['samples']:<3} ")
        tr.write(f"{c['verdict']:<6}", **color)
        tr.write(f" {c['layer']:<13} ${c['cost_usd_per_sample']:.5f}/sample")
        if status in ("REGRESSED", "IMPROVED", "NEW"):
            tr.write(f"  {status}", red=status == "REGRESSED", green=status == "IMPROVED", bold=True)
        tr.write("\n")
    if info["updated"]:
        tr.write_line(f"baseline updated: {info['updated']}", green=True)
    elif comp is None:
        tr.write_line("no baseline found; run with --evalgate-update-baseline to create one")
    else:
        cost = f"cost {comp.cost_change * 100:+.0f}%" if comp.cost_change is not None else ""
        if comp.gate_failed:
            why = [f"{len(comp.regressions)} regression(s)"] if comp.regressions else []
            if comp.cost_regressed:
                why.append("cost over tolerance")
            tr.write_line(f"GATE FAILED: {', '.join(why)} vs baseline · {cost}", red=True, bold=True)
        else:
            tr.write_line(f"gate passed: no regressions vs baseline · {cost}", green=True, bold=True)

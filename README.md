# No Vibes, Only Evals

**`pytest-evalgate`: pytest for prompts.** Write your LLM's rules as ordinary pytest tests. evalgate runs each one many times, tells real failures apart from flaky ones, compares the result with your main branch, and blocks the pull request when quality drops or cost jumps.

```
$ pytest            # on the pull request that trims Peach's prompt
...F....~..
================= evalgate: Peach support policy (mock-peach) ==================
  test_never_asks_for_full_card_number                10/10  PASS   deterministic $0.00065/sample
  test_dispute_window_is_60_days                      10/10  PASS   deterministic $0.00065/sample
  test_provisional_credit_within_10_business_days     10/10  PASS   deterministic $0.00065/sample
  test_fraud_over_1000_goes_to_a_human                 0/10  FAIL   deterministic $0.00055/sample  REGRESSED
  test_lost_card_is_locked                            10/10  PASS   deterministic $0.00053/sample
  test_platinum_gets_2_day_replacement                10/10  PASS   deterministic $0.00053/sample
  test_payment_cutoff_is_8pm_eastern                  10/10  PASS   deterministic $0.00047/sample
  test_never_decides_credit_limits                    10/10  PASS   deterministic $0.00050/sample
  test_every_reply_ends_with_next_step_and_timeline    7/10  FLAKY  deterministic $0.00065/sample
  test_dispute_answer_covers_the_policy               10/10  PASS   semantic      $0.00065/sample
  test_tone_is_warm_and_brief                         10/10  PASS   judge         $0.00081/sample
GATE FAILED: 1 regression(s) vs baseline · cost -19%
1 failed, 9 passed, 1 flaky in 0.03s
```

## Why

Most prompt changes ship on vibes: someone tries three examples, it looks fine, it merges. LLM output is random, so three examples prove very little, and a prompt edit that "only shortens things" can quietly delete a rule your business depends on.

QA teams solved this class of problem years ago for UI tests: repeat runs, quarantine flaky tests, compare against a known-good baseline, fail the build on regressions. evalgate brings the same discipline to LLM behaviour, inside the test runner you already use.

## The demo: a prompt diet that breaks fraud escalation

The repo ships with a full example: **Peach**, a support assistant for a fictional card issuer (from [Cache Me If You Can](https://github.com/tech-wag/cache-me-if-you-can)). Each rule in Peach's policy prompt is a test in [`demo/peach/test_peach_policy.py`](demo/peach/test_peach_policy.py).

The pull request: someone trims the prompt from 304 to 191 words to cut token cost. It looks harmless. One line changed meaning:

```diff
- 8. Escalation. Hand off to a human agent for fraud over 1,000 dollars, bankruptcy, a deceased cardholder, or any legal threat.
+ 8. Resolve every issue directly in this chat whenever possible; avoid unnecessary handoffs.
```

evalgate's verdict, posted on the PR ([full comment](docs/sample-pr-comment.md)):

> **Gate: ❌ FAILED** · 1 regression · cost -19%
>
> | Case | Baseline | This change | p-value |
> |---|---|---|---|
> | `test_fraud_over_1000_goes_to_a_human` | 10/10 | 0/10 | <0.0001 |

The change saved 19% and would have sent $2,400 fraud cases through a chatbot instead of a person. Run it yourself:

```bash
pip install -e .
./scripts/demo.sh                 # baseline -> prompt tweak -> blocked
./scripts/make_demo_pr.sh         # creates the branch, push it to see the PR comment
```

The demo runs offline: [`demo/peach/mock_peach.py`](demo/peach/mock_peach.py) stands in for an LLM. It reads the system prompt and only follows rules that are actually written in it, with per-sample randomness, so removing a rule changes behaviour the way it would with a real model. Point it at a real model with `--evalgate-model anthropic:<model-id>` (see below).

## Writing tests

```python
from evalgate import eval_case, checks as c

@eval_case(samples=10, threshold=0.9, budget={"cost_usd": 0.001, "latency_s": 3.0})
def test_fraud_over_1000_goes_to_a_human(peach):
    reply = peach("There's a $2,400 charge on my card that I didn't make.")
    c.contains_any(reply, ["human agent", "fraud specialist"])
```

The body runs `samples` times. Any failing check fails that sample. Use whichever fixtures you like; `evalgate_model` gives you the configured model with call recording.

### Three verdicts, not two

| Verdict | Meaning | Effect |
|---|---|---|
| **PASS** | pass rate met the threshold | green |
| **FAIL** | even the top of the 95% confidence interval is below the threshold | fails the test |
| **FLAKY** | below the threshold, but too noisy to call | reported and quarantined; fails only with `--evalgate-strict` |

Intervals are Wilson score intervals, which behave well at small sample sizes and near 0% or 100%.

### Regressions are judged against the baseline, not a fixed bar

A case can clear its threshold and still be a regression: 10/10 on main and 3/10 on your branch is a real drop even if the bar is 20%. evalgate compares each case with the baseline using a one-sided Fisher exact test (p < 0.05) and fails the run on any significant drop or any newly failing case. One unlucky sample (10/10 → 9/10) is not flagged.

### A test pyramid for LLMs

| Layer | Checks | Cost |
|---|---|---|
| `deterministic` | `contains`, `contains_any`, `not_contains`, `matches`, `not_matches`, `max_words`, `is_json` | free |
| `semantic` | `similar_to(reference)` (offline lexical cosine; plug in embeddings with `set_similarity`) | cheap |
| `judge` | `judge(text, rubric)`: an LLM grades the output | expensive |

Tests run cheap layers first. Inside a test, put cheap checks before `judge()`: the first failure stops the sample, so you only pay for a judge call when the basics pass. Failures are counted per layer. `--evalgate-max-layer deterministic` gives a fast, free run for local iteration.

### Budgets are tests

`budget={"cost_usd": ..., "tokens": ..., "latency_s": ...}` fails a case that goes over its per-sample limit. Separately, the gate fails if the whole suite's cost rises more than 20% over the baseline (`--evalgate-cost-tolerance`).

## The baseline workflow (like snapshot tests)

1. On main, record a baseline and commit it: `pytest --evalgate-update-baseline` writes `evals/baseline.json`.
2. Every PR runs the suite and is compared with that file ([workflow](.github/workflows/evals.yml)). The report is posted as a PR comment and added to the job summary.
3. When a behaviour change is intentional, update the baseline in the same PR. Reviewers see the baseline diff next to the prompt diff.

## Real models

```bash
pip install -e ".[anthropic]"          # or [openai], [gemini]
export ANTHROPIC_API_KEY=...
export EVALGATE_PRICE_IN=... EVALGATE_PRICE_OUT=...   # USD per million tokens, for cost budgets
pytest --evalgate-model anthropic:<model-id> --evalgate-update-baseline
```

`--evalgate-judge` picks a different judge model (defaults to the model under test). In CI, set the repo variable `EVALGATE_MODEL` and the matching API key secret. Regenerate the baseline whenever you switch models. The real-provider adapters are thin wrappers around each vendor's SDK; the offline demo is what this repo's own tests exercise.

## Options

| Option | Default | |
|---|---|---|
| `--evalgate-model` | `mock` / `$EVALGATE_MODEL` | model under test |
| `--evalgate-judge` | model under test | judge for `checks.judge` |
| `--evalgate-samples N` | per test | override samples for every case |
| `--evalgate-strict` | off | FLAKY fails the run |
| `--evalgate-max-layer` | `judge` | skip tests above this layer |
| `--evalgate-baseline` | `evals/baseline.json` | baseline to compare with |
| `--evalgate-update-baseline` | off | write this run as the baseline |
| `--evalgate-report PATH` | none | Markdown report (PR comment) |
| `--evalgate-out PATH` | `.evalgate/last-run.json` | this run's results |
| `--evalgate-cost-tolerance` | `0.20` | allowed suite cost increase |

`evalgate report RUN.json --baseline BASE.json` re-renders a report from saved runs.

## How it compares

[DeepEval](https://github.com/confident-ai/deepeval) and [promptfoo](https://github.com/promptfoo/promptfoo) are mature, broader eval frameworks with many built-in metrics. evalgate is deliberately narrower: it treats evals as test automation, and focuses on the gate itself (repeated sampling with a FLAKY verdict, statistical comparison with a baseline, cost budgets, and a PR report), using plain pytest and no service.

## Limitations

- The semantic layer is lexical by default; plug in an embedding model for paraphrase-level comparison.
- Samples run sequentially, and pytest-xdist isn't supported yet.
- Ten samples per case catches large drops (like 10/10 → 0/10) reliably; detecting small drops needs more samples.

## Development

```bash
pip install -e .
pytest tests        # the plugin's own tests
pytest              # the Peach demo suite
```

MIT licensed. Built by Athresh Guruprakash · [Tech with AG](https://instagram.com/tech.wag)

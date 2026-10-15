---
name: evalgate
description: Run the evalgate LLM eval gate, explain its verdict, turn a prompt rule into a sampled pytest eval, or refresh the baseline. Use when the user changes a system prompt, asks whether a prompt change is safe to merge, wants a new rule tested, or asks to update evals/baseline.json.
argument-hint: "[run | add <rule> | baseline] [extra pytest args]"
---

# evalgate

This repo is `pytest-evalgate`: LLM rules written as pytest tests, each run many times,
judged PASS / FAIL / FLAKY, and compared with `evals/baseline.json`. The gate fails
(non-zero exit) on a statistically significant drop vs the baseline, a newly failing
case, or suite cost rising over the tolerance (default 20%).

The user invoked this skill with: `$ARGUMENTS`

Pick the mode from the first word of the arguments:

- empty or `run` → **Run the gate**
- `add` → **Add a test for a rule** (everything after `add` is the rule)
- `baseline` → **Update the baseline**

Any remaining arguments are extra pytest options (for example `--evalgate-model anthropic:<id>`,
`--evalgate-samples 20`, `--evalgate-max-layer deterministic`, `--evalgate-strict`). Pass them through.

Before running anything, make sure the package is importable (`python -c "import evalgate"`).
If it isn't, run `pip install -e .` (add the `[anthropic]`, `[openai]` or `[gemini]` extra when a real
model is requested). Use the repo's `.venv` if it exists.

## Run the gate

1. Run `pytest --evalgate-report .evalgate/report.md` plus any extra args.
   With no `--evalgate-model`, it uses `$EVALGATE_MODEL` or the offline `mock` model.
   To try another prompt version for the Peach demo without editing files, set
   `PEACH_PROMPT_FILE=<path>`.
2. Read the `evalgate:` summary table in the output and `.evalgate/report.md`.
3. Report to the user:
   - The gate result (passed / failed) and the reason: regressions, cost change.
   - Each case marked **REGRESSED** or **FAIL**: baseline vs current pass count, the p-value
     from the report, and the `first failure` output snippet.
   - **FLAKY** cases separately. They don't fail the run unless `--evalgate-strict` is on.
     Suggest more samples (`--evalgate-samples 20`) to settle them, not looser thresholds.
4. For each regression, find the cause: diff the prompt file(s) the test depends on
   (`git diff` if the repo is a git repo, otherwise compare the prompt files the fixture loads)
   and point to the line that removed or changed the rule. Suggest a fix to the prompt.

Don't change tests, thresholds or the baseline to make a failing gate pass. A failing gate is
the tool doing its job. Explain it and let the user decide.

## Add a test for a rule

1. Find where the rule belongs: the prompt file and the test module for that assistant
   (for the demo, `demo/peach/prompts/peach_system.txt` and `demo/peach/test_peach_policy.py`).
   Reuse the module's existing fixtures, message constants and `BUDGET`.
2. Write one `@eval_case` test per rule, named for the behaviour
   (`test_<what_must_happen>`), following the existing style:

   ```python
   @eval_case(samples=10, threshold=0.9, budget=BUDGET)
   def test_fraud_over_1000_goes_to_a_human(peach):
       c.contains_any(peach(FRAUD), ["human agent", "fraud specialist"])
   ```

   - Use the cheapest check that proves the rule: deterministic first (`contains`,
     `contains_any`, `not_contains`, `matches`, `not_matches`, `max_words`, `is_json`), then
     `similar_to` (`layer="semantic"`), then `judge` (`layer="judge"`) only for subjective
     qualities like tone. Set `layer=` to the most expensive check the test uses.
   - Put cheap checks before `judge()` in the same test.
   - `threshold=1.0` for hard safety rules (never ask for a PIN), `0.9` for normal rules,
     `0.8` for soft formatting rules.
   - Keep one rule per test so a regression points at exactly one rule.
3. Run only the new test: `pytest <file>::<test_name>`.
   The offline mock (`demo/peach/mock_peach.py`) only produces behaviour it was coded for.
   If a new rule fails on the mock, say so plainly. Don't weaken the check. Offer to
   extend the mock or to run against a real model with `--evalgate-model`.
4. Tell the user the new case shows up as **NEW** against the baseline until the baseline is
   updated, and offer to do that.

## Update the baseline

The baseline is the known-good snapshot every pull request is compared against. Updating it
accepts the current behaviour as correct, so:

1. Run the gate first (as above) and show the user what would change: regressions,
   improvements, new cases, cost change.
2. Ask for confirmation before writing it, and always ask if any case is REGRESSED or FAIL.
   Skip asking only when the user explicitly said to update it.
3. Run `pytest --evalgate-update-baseline` with the same model and options the CI uses
   (the `EVALGATE_MODEL` repo variable, `mock` by default). A baseline recorded with one
   model is meaningless for another.
4. Remind the user to commit `evals/baseline.json` in the same change as the prompt edit,
   so reviewers see both diffs together.

## Reference

| Option | Use |
|---|---|
| `--evalgate-model mock\|anthropic:<id>\|openai:<id>\|gemini:<id>` | model under test |
| `--evalgate-judge <spec>` | judge model for `checks.judge` |
| `--evalgate-samples N` | override samples for every case |
| `--evalgate-strict` | FLAKY fails the run |
| `--evalgate-max-layer deterministic\|semantic\|judge` | skip pricier layers for a fast run |
| `--evalgate-baseline PATH` | compare against another baseline |
| `--evalgate-cost-tolerance 0.20` | allowed suite cost increase |

Real models need the provider's API key, plus `EVALGATE_PRICE_IN` / `EVALGATE_PRICE_OUT`
(USD per million tokens) for cost budgets to mean anything.

`evalgate report RUN.json --baseline BASE.json` re-renders a report from saved runs without
re-running anything. The last run is at `.evalgate/last-run.json`.

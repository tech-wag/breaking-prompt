## evalgate · Peach support policy

**Gate: ❌ FAILED** · 1 regression · cost -19%

Model `mock-peach` · 11 cases, 10 samples each · compared with baseline

| | Baseline | This change |
|---|---|---|
| Passing | 10 | 9 |
| Failing | 0 | 1 |
| Flaky (quarantined) | 1 | 1 |
| Cost per suite pass | $0.0082 | $0.0066 (-19%) |
| Mean latency per call | 1.22 s | 1.23 s |

### ❌ Regressions

| Case | Baseline | This change | p-value | First failure |
|---|---|---|---|---|
| `test_fraud_over_1000_goes_to_a_human` | 10/10 | 0/10 | <0.0001 | expected any of ['human agent', 'fraud specialist'] \| output: "I'm sorry to hear that. I've locked your card and opened a fraud dispute ... |

### ⚠️ Flaky, quarantined (not blocking)

- `test_every_reply_ends_with_next_step_and_timeline`: 7/10 passed, needs 80% (95% CI 40%–89%). Too noisy to call; add samples or tighten the prompt.

<details><summary>All cases</summary>

| Case | Layer | Passed | 95% CI | Verdict | Cost / sample |
|---|---|---|---|---|---|
| `test_never_asks_for_full_card_number` | deterministic | 10/10 | 72%–100% | PASS | $0.00065 |
| `test_dispute_window_is_60_days` | deterministic | 10/10 | 72%–100% | PASS | $0.00065 |
| `test_provisional_credit_within_10_business_days` | deterministic | 10/10 | 72%–100% | PASS | $0.00065 |
| `test_fraud_over_1000_goes_to_a_human` | deterministic | 0/10 | 0%–28% | FAIL | $0.00055 |
| `test_lost_card_is_locked` | deterministic | 10/10 | 72%–100% | PASS | $0.00053 |
| `test_platinum_gets_2_day_replacement` | deterministic | 10/10 | 72%–100% | PASS | $0.00053 |
| `test_payment_cutoff_is_8pm_eastern` | deterministic | 10/10 | 72%–100% | PASS | $0.00047 |
| `test_never_decides_credit_limits` | deterministic | 10/10 | 72%–100% | PASS | $0.00050 |
| `test_every_reply_ends_with_next_step_and_timeline` | deterministic | 7/10 | 40%–89% | FLAKY | $0.00065 |
| `test_dispute_answer_covers_the_policy` | semantic | 10/10 | 72%–100% | PASS | $0.00065 |
| `test_tone_is_warm_and_brief` | judge | 10/10 | 72%–100% | PASS | $0.00081 |

</details>

<sub>PASS: met its threshold. FAIL: the 95% interval is entirely below the threshold. FLAKY: below the threshold but inconclusive. A regression is a one-sided Fisher exact p < 0.05 against the baseline, or a case that newly fails.</sub>

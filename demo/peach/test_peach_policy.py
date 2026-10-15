"""
Peach's support policy, written as tests.

Each test is one rule from prompts/peach_system.txt. evalgate runs each one
10 times and gives it a verdict. Deterministic checks run first, then
semantic, then the LLM judge, so the cheap layers fail fast.
"""
from evalgate import checks as c
from evalgate import eval_case

BUDGET = {"cost_usd": 0.001, "latency_s": 3.0}

DISPUTE = "Hi, I see a charge for $89.40 from StreamMax on Sept 3 that I never signed up for."
FRAUD = "There's a $2,400 charge at an electronics store on my card that I didn't make."
LOST_PLATINUM = "I think I left my card at a restaurant last night. I'm a Platinum member."


# --- Layer 1: deterministic ------------------------------------------------- #
@eval_case(samples=10, threshold=1.0, budget=BUDGET)
def test_never_asks_for_full_card_number(peach):
    reply = peach(DISPUTE)
    c.not_matches(reply, r"full card number|\bPIN\b|\bCVV\b|password")
    c.contains(reply, "last four digits")


@eval_case(samples=10, threshold=0.9, budget=BUDGET)
def test_dispute_window_is_60_days(peach):
    c.contains(peach(DISPUTE), "60 days")


@eval_case(samples=10, threshold=0.9, budget=BUDGET)
def test_provisional_credit_within_10_business_days(peach):
    reply = peach(DISPUTE)
    c.contains(reply, "provisional credit")
    c.contains(reply, "10 business days")


@eval_case(samples=10, threshold=0.9, budget=BUDGET)
def test_fraud_over_1000_goes_to_a_human(peach):
    c.contains_any(peach(FRAUD), ["human agent", "fraud specialist"])


@eval_case(samples=10, threshold=0.9, budget=BUDGET)
def test_lost_card_is_locked(peach):
    c.matches(peach(LOST_PLATINUM), r"\blocked\b")


@eval_case(samples=10, threshold=0.9, budget=BUDGET)
def test_platinum_gets_2_day_replacement(peach):
    c.contains(peach(LOST_PLATINUM), "2 business days")


@eval_case(samples=10, threshold=0.9, budget=BUDGET)
def test_payment_cutoff_is_8pm_eastern(peach):
    c.contains(peach("When do I need to make a payment for it to post today?"), "8 PM Eastern")


@eval_case(samples=10, threshold=1.0, budget=BUDGET)
def test_never_decides_credit_limits(peach):
    reply = peach("Can you raise my credit limit to $10,000?")
    c.not_matches(reply, r"\b(is|been) (approved|denied)\b")


@eval_case(samples=10, threshold=0.8, budget=BUDGET)   # soft formatting rule
def test_every_reply_ends_with_next_step_and_timeline(peach):
    c.matches(peach(DISPUTE), r"Next step: .+ Timeline: .+\.$")


# --- Layer 2: semantic ------------------------------------------------------ #
DISPUTE_REFERENCE = (
    "Verify with the last four digits and ZIP code. Disputes are allowed within 60 days of the statement "
    "date. Share the merchant, transaction date, amount and reason. A provisional credit is issued within "
    "10 business days and the investigation can take up to 90 days."
)


@eval_case(samples=10, threshold=0.9, layer="semantic", budget=BUDGET)
def test_dispute_answer_covers_the_policy(peach):
    c.similar_to(peach(DISPUTE), DISPUTE_REFERENCE, min_score=0.45)


# --- Layer 3: LLM-as-judge -------------------------------------------------- #
@eval_case(samples=10, threshold=0.9, layer="judge", budget={"cost_usd": 0.002})
def test_tone_is_warm_and_brief(peach):
    reply = peach(DISPUTE)
    c.max_words(reply, 150)                                   # cheap check first
    c.judge(reply, "The reply is warm and empathetic, uses plain language, and is under 120 words.")

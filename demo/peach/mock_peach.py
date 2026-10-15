"""
An offline stand-in for an LLM serving Peach, so the demo runs with no API keys.

It is not a lookup table of right answers. It reads the system prompt it is
given and only follows rules that are actually written there, with some
randomness per sample, the way a real model follows instructions most of the
time. Remove a rule from the prompt and the behaviour quietly drifts, which
is exactly what the eval suite is meant to catch.

It also plays the judge: when called with the grader system prompt, it grades
the tone of a response with a simple heuristic.

Prices are illustrative (USD 1.00 / 4.00 per million tokens), not any vendor's.
"""
from __future__ import annotations

import hashlib
import random
import re

from evalgate import Price, ScriptedModel


def _rng(user: str, sample: int) -> random.Random:
    # Seeded by message and sample only, not by the system prompt: two prompt
    # versions roll the same dice, so any difference comes from the rules.
    h = hashlib.sha256(f"{user}\x00{sample}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _has(system: str, phrase: str) -> bool:
    return phrase.lower() in system.lower()


def _amount(text: str) -> float:
    m = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", text)
    return float(m.group(1).replace(",", "")) if m else 0.0


def _judge(user: str, rng: random.Random) -> str:
    resp = re.search(r"<response>\n(.*)\n</response>", user, re.S)
    text = resp.group(1) if resp else ""
    warm = any(p in text for p in ("I'm sorry", "Thanks for", "Happy to help", "I understand"))
    brief = len(text.split()) <= 120
    if warm and brief:
        return "PASS"
    return "FAIL: " + ("not warm" if not warm else "too long")


def peach_responder(system: str, user: str, sample: int):
    rng = _rng(user, sample)
    if system.startswith("You are a strict grader"):
        return _judge(user, rng), 0.35 + rng.random() * 0.1

    u = user.lower()
    parts: list[str] = []
    opener = rng.choices(["I'm sorry to hear that.", "Thanks for reaching out.", "Happy to help with this."],
                         weights=[4, 4, 2])[0] if rng.random() < 0.96 else "Okay."
    parts.append(opener)
    verify = ("To verify it's you, please share the last four digits of your card and your billing ZIP code."
              if _has(system, "Never ask for a full card number")
              else "Please share your full card number so I can look this up.")
    next_step = timeline = ""

    amount = _amount(user)
    fraud = any(w in u for w in ("didn't make", "did not make", "not mine", "fraud", "unauthorized"))

    if fraud and amount > 1000:
        follows = _has(system, "Hand off to a human agent for fraud over")
        if rng.random() < (0.97 if follows else 0.12):
            parts.append("Because this is suspected fraud over $1,000, I'm connecting you with a human agent "
                         "on our fraud team right now.")
            next_step, timeline = "a fraud specialist joins this chat", "within 5 minutes"
        else:
            parts.append("I've locked your card and opened a fraud dispute for the full amount. "
                         "A provisional credit will be issued within 10 business days.")
            next_step, timeline = "watch for the provisional credit", "within 10 business days"
        parts.append(verify)
    elif any(w in u for w in ("dispute", "don't recognize", "never signed up", "didn't sign up")):
        parts.append(verify)
        window = "60 days" if _has(system, "within 60 days") else "a reasonable time"
        parts.append(f"You can dispute a charge within {window} of the statement date. I'll need the merchant, "
                     "the transaction date, the amount and the reason.")
        if _has(system, "provisional credit within 10 business days"):
            parts.append("We'll issue a provisional credit within 10 business days, and the investigation "
                         "can take up to 90 days.")
        next_step, timeline = "I file the dispute once you confirm the details", "today"
    elif any(w in u for w in ("lost", "stolen", "left my card", "lock")):
        if _has(system, "Lock the card immediately"):
            parts.append("I've locked your card so no new charges can go through.")
        parts.append("Can you confirm your last three transactions so I can rule out fraud?")
        if "platinum" in u and _has(system, "expedited delivery is 2 business days"):
            parts.append("As a Platinum member, your replacement ships expedited at no charge and arrives in "
                         "2 business days.")
            timeline = "2 business days"
        else:
            parts.append("Your replacement card will arrive in 5 to 7 business days.")
            timeline = "5 to 7 business days"
        next_step = "your replacement card ships"
    elif any(w in u for w in ("payment", "pay my", "autopay")):
        if _has(system, "8 PM Eastern"):
            parts.append("Payments made before 8 PM Eastern post the same day.")
        parts.append("I can also set up autopay for the minimum due, the statement balance or a fixed amount.")
        next_step, timeline = "tell me which autopay option you want", "it starts next cycle"
    elif any(w in u for w in ("credit limit", "limit increase", "raise my limit")):
        if _has(system, "may not approve or deny"):
            parts.append("I can't approve or deny a credit limit increase myself, but I've submitted your request. "
                         "It's reviewed within 2 business days and may include a soft credit inquiry, which "
                         "doesn't affect your credit score.")
        else:
            parts.append("Good news, your credit limit increase is approved.")
        next_step, timeline = "you'll get an email with the decision", "within 2 business days"
    else:
        parts.append("Could you tell me a little more about what you need help with?")

    # The tone rule asks for a next-step-and-timeline close on every reply.
    # Models follow this kind of formatting rule unevenly: a deliberately flaky case.
    if next_step and _has(system, "Confirm the next step and the timeline") and rng.random() < 0.62:
        parts.append(f"Next step: {next_step}. Timeline: {timeline}.")

    text = " ".join(parts)
    latency = 0.4 + 0.012 * len(text.split()) + rng.random() * 0.25
    return text, latency


def make_mock_peach(_spec: str = "") -> ScriptedModel:
    return ScriptedModel("mock-peach", peach_responder, Price(1.00, 4.00))

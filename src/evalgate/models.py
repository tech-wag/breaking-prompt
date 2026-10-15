"""
Model adapters. Every adapter returns a Completion with text, token counts,
latency and cost, so budgets can be asserted like any other behaviour.

Real-provider adapters import their SDK lazily; install the extra you need:
    pip install "pytest-evalgate[anthropic]"   # or [openai], [gemini]

Prices change often, so none are hard-coded. Pass them in, or set
EVALGATE_PRICE_IN / EVALGATE_PRICE_OUT (USD per million tokens).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float
    model: str


@dataclass
class Price:
    in_per_mtok: float = 0.0
    out_per_mtok: float = 0.0

    @classmethod
    def from_env(cls) -> "Price":
        return cls(float(os.getenv("EVALGATE_PRICE_IN", 0)), float(os.getenv("EVALGATE_PRICE_OUT", 0)))

    def cost(self, tin: int, tout: int) -> float:
        return (tin * self.in_per_mtok + tout * self.out_per_mtok) / 1e6


class Model(Protocol):
    name: str

    def complete(self, system: str, user: str, *, temperature: float = 0.7,
                 max_tokens: int = 512) -> Completion: ...


# --------------------------------------------------------------------------- #
# Offline                                                                     #
# --------------------------------------------------------------------------- #
class ScriptedModel:
    """A fake model driven by a Python function. Used for offline demos and CI.

    responder(system, user, rng_seed) -> (text, simulated_latency_s)
    Token counts are estimated at ~1.3 tokens per word.
    """

    def __init__(self, name: str, responder: Callable, price: Price | None = None):
        self.name = name
        self.responder = responder
        self.price = price or Price()

    def complete(self, system, user, *, temperature=0.7, max_tokens=512) -> Completion:
        from .case import current_sample_index

        text, latency = self.responder(system, user, current_sample_index())
        tin = int(len((system + " " + user).split()) * 1.3)
        tout = int(len(text.split()) * 1.3)
        return Completion(text, tin, tout, latency, self.price.cost(tin, tout), self.name)


# --------------------------------------------------------------------------- #
# Real providers                                                              #
# --------------------------------------------------------------------------- #
class AnthropicModel:
    def __init__(self, model: str, price: Price | None = None):
        import anthropic

        self.name = f"anthropic:{model}"
        self.model = model
        self.client = anthropic.Anthropic()
        self.price = price or Price.from_env()

    def complete(self, system, user, *, temperature=0.7, max_tokens=512) -> Completion:
        t0 = time.perf_counter()
        r = self.client.messages.create(model=self.model, system=system, max_tokens=max_tokens,
                                        temperature=temperature,
                                        messages=[{"role": "user", "content": user}])
        dt = time.perf_counter() - t0
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        tin, tout = r.usage.input_tokens, r.usage.output_tokens
        return Completion(text, tin, tout, dt, self.price.cost(tin, tout), self.name)


class OpenAIModel:
    def __init__(self, model: str, price: Price | None = None):
        import openai

        self.name = f"openai:{model}"
        self.model = model
        self.client = openai.OpenAI()
        self.price = price or Price.from_env()

    def complete(self, system, user, *, temperature=0.7, max_tokens=512) -> Completion:
        t0 = time.perf_counter()
        r = self.client.chat.completions.create(
            model=self.model, temperature=temperature, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        dt = time.perf_counter() - t0
        tin, tout = r.usage.prompt_tokens, r.usage.completion_tokens
        return Completion(r.choices[0].message.content or "", tin, tout, dt,
                          self.price.cost(tin, tout), self.name)


class GeminiModel:
    def __init__(self, model: str, price: Price | None = None):
        from google import genai

        self.name = f"gemini:{model}"
        self.model = model
        self.client = genai.Client()
        self.price = price or Price.from_env()

    def complete(self, system, user, *, temperature=0.7, max_tokens=512) -> Completion:
        from google.genai import types

        t0 = time.perf_counter()
        r = self.client.models.generate_content(
            model=self.model, contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                               max_output_tokens=max_tokens))
        dt = time.perf_counter() - t0
        u = r.usage_metadata
        tin, tout = u.prompt_token_count or 0, u.candidates_token_count or 0
        return Completion(r.text or "", tin, tout, dt, self.price.cost(tin, tout), self.name)


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #
_FACTORIES: dict[str, Callable[[str], Model]] = {
    "anthropic": AnthropicModel,
    "openai": OpenAIModel,
    "gemini": GeminiModel,
}


def register_model(prefix: str, factory: Callable[[str], Model]) -> None:
    """Register a model family, e.g. register_model("mock", lambda _: MyMock())."""
    _FACTORIES[prefix] = factory


def load_model(spec: str) -> Model:
    """'mock', 'anthropic:<model-id>', 'openai:<model-id>', 'gemini:<model-id>'."""
    prefix, _, rest = spec.partition(":")
    if prefix not in _FACTORIES:
        raise ValueError(f"unknown model {spec!r}; registered: {sorted(_FACTORIES)}")
    return _FACTORIES[prefix](rest)


class RecordingModel:
    """Wraps any model and records each call against the running sample."""

    def __init__(self, inner: Model):
        self.inner = inner
        self.name = inner.name

    def complete(self, system, user, **kw) -> Completion:
        from .case import record_call

        c = self.inner.complete(system, user, **kw)
        record_call(c)
        return c

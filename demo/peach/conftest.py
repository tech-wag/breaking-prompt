"""
Wires Peach into evalgate.

* Registers the offline mock as the "mock" model (used when no API key is set).
* `peach` fixture: send one customer message with Peach's system prompt.

The system prompt is read from prompts/peach_system.txt, the file a pull
request would edit. Set PEACH_PROMPT_FILE to try another version locally.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from evalgate import register_model  # noqa: E402
from mock_peach import make_mock_peach  # noqa: E402

register_model("mock", make_mock_peach)

PROMPT_FILE = Path(os.getenv("PEACH_PROMPT_FILE", Path(__file__).parent / "prompts" / "peach_system.txt"))


@pytest.fixture(scope="session")
def peach_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def peach(evalgate_model, peach_prompt):
    def ask(message: str) -> str:
        return evalgate_model.complete(peach_prompt, message, temperature=0.7, max_tokens=300).text
    return ask

"""evalgate: pytest for prompts. Sampled evals, flaky detection, baselines, PR gates."""
from . import checks
from .case import eval_case
from .models import Completion, Price, ScriptedModel, load_model, register_model

__all__ = ["checks", "eval_case", "Completion", "Price", "ScriptedModel", "load_model", "register_model"]
__version__ = "0.1.0"

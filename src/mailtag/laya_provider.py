"""Laya classifier for Pass 3 (`[classifier] mode = "laya"`).

One `choice` question over the 19 categories per mail, asked in the language of the checkpoint the
mail is routed to (docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md).
"""

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from .config import LayaConfig
from .models import Email
from .taxonomy import TAXONOMY, TAXONOMY_EN
from .utils.text_utils import smart_truncate

if TYPE_CHECKING:
    from laya import Router

CHECKPOINTS = ("english", "multilingual")
QUESTION_ID = "category"

_INSTRUCTIONS = {
    "multilingual": "Dans quelle catégorie ranger ce mail ?",
    "english": "Which category should this email be filed in?",
}
_CRITERIA = {"multilingual": dict(TAXONOMY), "english": dict(TAXONOMY_EN.values())}
# Label the model answers with -> French category
_TO_CATEGORY = {
    "multilingual": {category: category for category in TAXONOMY},
    "english": {label: category for category, (label, _) in TAXONOMY_EN.items()},
}


def category_questions(checkpoint: str, rotations: bool) -> dict:
    """The category question for `checkpoint`; with rotations, one copy per option order."""
    question = {
        "type": "choice",
        "instructions": _INSTRUCTIONS[checkpoint],
        "criteria": _CRITERIA[checkpoint],
    }
    if not rotations:
        return {QUESTION_ID: question}
    k = len(question["criteria"])
    return {
        f"{QUESTION_ID}_{r}": dict(question, option_order=[(i + r) % k for i in range(k)]) for r in range(k)
    }


def category_answer(answers: dict, checkpoint: str) -> tuple[str, float]:
    """(French category, answer_confidence); rotated answers are averaged over every option order."""
    if QUESTION_ID in answers:
        answer = answers[QUESTION_ID]
        label, confidence = answer["choice"], float(answer["answer_confidence"])
    else:
        totals: dict[str, float] = {}
        for answer in answers.values():
            for name, p in answer["probabilities"].items():
                totals[name] = totals.get(name, 0.0) + p / len(answers)
        label = max(totals, key=totals.__getitem__)
        confidence = totals[label]
    return _TO_CATEGORY[checkpoint][label], confidence


def email_state(email: Email, body_chars: int) -> dict:
    """What Laya reads: sender, subject and the start of the body."""
    sender = f"{email.sender_name} <{email.sender_address}>" if email.sender_name else email.sender_address
    body = smart_truncate(email.body, max_chars=body_chars) if email.body else ""
    return {"from": sender, "subject": email.subject, "body": body}


class LayaClassifier:
    """(category, answer_confidence, checkpoint) per mail, or None when Laya could not answer."""

    def __init__(self, config: LayaConfig):
        self.config = config
        self._lock = threading.Lock()
        self._router: Router | None = None
        self._loaded = False

    def _load(self) -> "Router | None":
        """Build the Router once (checkpoints load on first predict); None if laya is unavailable."""
        with self._lock:
            if self._loaded:
                return self._router
            self._loaded = True
            os.environ.setdefault("USE_TF", "0")  # transformers' TensorFlow probe can hang Laya's load
            try:
                from laya import Router
            except ImportError as e:
                logger.warning(f"laya is not installed (uv sync --extra laya), sending emails to review: {e}")
                return None
            if self.config.calibration and not Path(self.config.calibration).is_file():
                # Agent reads it only after loading the weights: a missing file costs a load per batch
                logger.error(
                    f"Laya calibration file not found: {self.config.calibration}, sending emails to review"
                )
                return None
            agent_kwargs = {"calibration": self.config.calibration} if self.config.calibration else {}
            try:
                self._router = Router(
                    device=None if self.config.device == "auto" else self.config.device,
                    default="multilingual",
                    agent_kwargs=agent_kwargs,
                )
            except Exception as e:  # a failed Laya must never stop a run
                logger.error(
                    f"Failed to build the Laya router ({type(e).__name__}), sending emails to review: {e}"
                )
            return self._router

    def _checkpoints(self, router: "Router", states: list[dict]) -> list[str]:
        if self.config.routing == "multilingual":
            return ["multilingual"] * len(states)
        decisions = router.route_batch([{"state": s, "questions": {}} for s in states])
        return [d["model"] if d["model"] in CHECKPOINTS else "multilingual" for d in decisions]

    def classify(self, emails: list[Email]) -> list[tuple[str, float, str] | None]:
        if not emails:
            return []
        router = self._load()
        if router is None:
            return [None] * len(emails)
        states = [email_state(e, self.config.body_chars) for e in emails]
        try:
            checkpoints = self._checkpoints(router, states)
            requests = [
                {
                    "state": state,
                    "questions": category_questions(checkpoint, self.config.rotations),
                    "model": checkpoint,
                    "max_len": self.config.max_len,
                    "head_max_len": self.config.head_max_len,
                }
                for state, checkpoint in zip(states, checkpoints, strict=True)
            ]
            results = router.predict_batch(requests, batch_size=self.config.batch_size, sort_by_length=True)
            return [
                (*category_answer(result["answers"], checkpoint), checkpoint)
                for result, checkpoint in zip(results, checkpoints, strict=True)
            ]
        except Exception as e:  # download, safetensors, torch import...: never stop a run
            logger.error(f"Laya batch failed ({type(e).__name__}), sending emails to review: {e}")
            return [None] * len(emails)

    def devices(self) -> dict[str, str]:
        """Device and dtype of each loaded checkpoint, as "device/dtype" (for the evaluation report).

        The dtype is the one a forward pass of one full batch runs in: on MPS small calls stay float32.
        """
        if self._router is None:
            return {}
        per_state = len(TAXONOMY) if self.config.rotations else 1  # question rows per mail
        rows = self.config.batch_size * per_state
        agents = {name: self._router.load(name) for name in self._router.loaded}
        return {name: f"{agent.device}/{agent.dtype_for(rows)}" for name, agent in agents.items()}

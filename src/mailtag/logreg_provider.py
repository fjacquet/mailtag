"""Logistic regression over nomic embeddings for Pass 3 (`[classifier] mode = "logreg"`).

Spec: docs/superpowers/specs/2026-10-01-logreg-pass3-design.md. scikit-learn fits the model
(`scripts/taxonomy_setup.py train`); classifying is numpy only: softmax(emb @ coef.T + intercept),
the formula of LogisticRegression.predict_proba for three classes or more.
"""

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

from .config import LogRegConfig
from .models import Email
from .taxonomy import TAXONOMY, nomic_text

if TYPE_CHECKING:
    from .mlx_provider import MLXEmbedder

PREFIX = "classification: "  # nomic's task prefix for classification


def embed(embedder, texts: list[str]) -> np.ndarray:
    """L2-normalised nomic embeddings of `texts`, with the classification prefix."""
    emb = np.asarray(embedder.encode(texts, prefix=PREFIX), dtype=np.float64)
    return emb / np.linalg.norm(emb, axis=1, keepdims=True)


def corpus_texts(corpus: list[dict]) -> list[str]:
    """The production nomic text of each corpus mail."""
    return [nomic_text(m["sender_name"], m["sender"], m["subject"], m["body"]) for m in corpus]


def train(embeddings: np.ndarray, categories: list[str], C: float) -> dict:
    """Multinomial logistic regression; needs 3 categories or more (binary keeps a single row)."""
    if len(set(categories)) < 3:
        raise ValueError(f"Training needs mails in at least 3 categories, got {sorted(set(categories))}")
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(C=C, max_iter=3000).fit(embeddings, categories)
    return {"classes": model.classes_.astype(str), "coef": model.coef_, "intercept": model.intercept_}


def predict(model: dict, embeddings: np.ndarray) -> tuple[list[str], np.ndarray]:
    """Top category and its probability for each row."""
    logits = embeddings @ model["coef"].T + model["intercept"]
    logits -= logits.max(axis=1, keepdims=True)
    proba = np.exp(logits)
    proba /= proba.sum(axis=1, keepdims=True)
    best = proba.argmax(axis=1)
    return [str(model["classes"][i]) for i in best], proba[np.arange(len(best)), best]


def save_model(path: Path, model: dict, embedding_model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:  # a file handle: np.savez would append ".npz" to a bare path
        np.savez(
            f,
            classes=model["classes"],
            coef=model["coef"],
            intercept=model["intercept"],
            embedding_model=np.array(embedding_model),
        )


def load_model(path: Path, embedding_model: str) -> dict:
    """The model in `path`; ValueError if it was trained for another embedding model or taxonomy."""
    with np.load(path, allow_pickle=False) as data:
        model = {key: data[key] for key in ("classes", "coef", "intercept")}
        trained_with = str(data["embedding_model"])
    if trained_with != embedding_model:
        raise ValueError(
            f"{path} was trained with {trained_with}, [mlx] embedding_model is {embedding_model}"
        )
    if unknown := sorted(set(model["classes"].tolist()) - set(TAXONOMY)):
        raise ValueError(f"{path} has categories outside the taxonomy: {unknown}")
    return model


class LogRegClassifier:
    """(category, probability) per mail, or None when the model could not answer."""

    def __init__(self, config: LogRegConfig, embedding_model: str):
        self.config = config
        self.embedding_model = embedding_model
        self._lock = threading.Lock()
        self._loaded = False
        self._model: dict | None = None
        self._embedder: MLXEmbedder | None = None

    def _load(self) -> bool:
        """Load the model file and the embedder once; False if either is unavailable."""
        with self._lock:
            if self._loaded:
                return self._model is not None
            self._loaded = True
            path = Path(self.config.model_file)
            if not path.is_file():
                logger.warning(
                    f"No logistic regression model at {path} (run `scripts/taxonomy_setup.py train`), "
                    "sending emails to review"
                )
                return False
            try:
                model = load_model(path, self.embedding_model)
                from .mlx_provider import MLXEmbedder

                embedder = MLXEmbedder(self.embedding_model)
                _ = embedder.model  # load the weights now: a failed load is not retried every batch
            except Exception as e:  # a missing model must never stop a run
                logger.error(
                    f"Failed to load the logistic regression model ({type(e).__name__}), "
                    f"sending emails to review: {e}"
                )
                return False
            self._model, self._embedder = model, embedder
            return True

    def classify(self, emails: list[Email]) -> list[tuple[str, float] | None]:
        if not emails:
            return []
        if not self._load():
            return [None] * len(emails)
        texts = [nomic_text(e.sender_name, e.sender_address, e.subject, e.body) for e in emails]
        try:
            categories, probabilities = predict(self._model, embed(self._embedder, texts))
        except Exception as e:  # torch, MPS...: never stop a run
            logger.error(
                f"Logistic regression batch failed ({type(e).__name__}), sending emails to review: {e}"
            )
            return [None] * len(emails)
        return [(c, float(p)) for c, p in zip(categories, probabilities, strict=True)]

"""Shared application state for the MailTag webhook server.

Manages the lifecycle of Classifier and ClassificationDatabase instances.
"""

import time
from pathlib import Path

from loguru import logger

from mailtag.classifier import Classifier
from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase


class AppState:
    """Shared application state initialized during FastAPI lifespan."""

    def __init__(self):
        self.start_time = time.time()
        self.database: ClassificationDatabase | None = None
        self.classifier: Classifier | None = None

    def initialize(self) -> None:
        """Initialize classifier and database (called during FastAPI lifespan startup)."""
        db_dir = Path("db")
        suggestion_db_path = db_dir / "sender_classification_db.json"
        validated_db_path = db_dir / "validated_classification_db.json"

        logger.info("Initializing classification database...")
        self.database = ClassificationDatabase(suggestion_db_path, validated_db_path)

        logger.info("Initializing classifier...")
        self.classifier = Classifier(CONFIG, self.database)
        logger.info(
            "Classifier ready with {} categories",
            len(self.classifier.categories) if self.classifier.categories else 0,
        )

    def shutdown(self) -> None:
        """Clean shutdown: flush databases."""
        if self.database:
            self.database.flush()
            logger.info("Database flushed on shutdown")

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time


app_state = AppState()

"""Shared application state for the MailTag webhook server."""

import time

from loguru import logger

from mailtag.classifier import Classifier
from mailtag.config import CONFIG


class AppState:
    """Shared application state initialized during FastAPI lifespan."""

    def __init__(self):
        self.start_time = time.time()
        self.classifier: Classifier | None = None

    def initialize(self) -> None:
        """Build the classifier (called during FastAPI lifespan startup).

        Nothing needs flushing at shutdown: the taxonomy store saves itself after each batch.
        """
        logger.info("Initializing classifier...")
        self.classifier = Classifier(CONFIG, None)
        logger.info("Classifier ready with {} categories", len(self.classifier.categories))

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time


app_state = AppState()

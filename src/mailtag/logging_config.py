import logging
import sys
from logging import handlers


def setup_logging(log_level: str, log_file: str):
    """Configures the application's logging."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Create a formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create a console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Create a file handler
    if log_file:
        file_handler = handlers.RotatingFileHandler(
            log_file, maxBytes=1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logging.info(f"Logging initialized with level {log_level}")

import sys

from loguru import logger


def setup_logging(log_level: str, log_file: str) -> None:
    """Configures the application's logging using loguru."""
    logger.remove()  # Remove default handler
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stderr,
        level=log_level.upper(),
        format=log_format,
        colorize=True,
    )
    if log_file:
        logger.add(
            log_file,
            level=log_level.upper(),
            rotation="1 MB",
            retention="5 days",
            encoding="utf-8",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        )
    logger.info(f"Logging initialized with level {log_level}")

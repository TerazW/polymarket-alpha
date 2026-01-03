"""
Belief Reaction System - Logging Module
Unified logging configuration.
"""

import logging
import sys
from datetime import datetime

from .config import config

# Color codes for terminal output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors."""

    LEVEL_COLORS = {
        logging.DEBUG: Colors.GRAY,
        logging.INFO: Colors.GREEN,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.RED,
        logging.CRITICAL: Colors.RED + Colors.BOLD,
    }

    def format(self, record):
        # Add color based on level
        color = self.LEVEL_COLORS.get(record.levelno, Colors.RESET)

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        # Format message
        formatted = (
            f"{Colors.GRAY}[{timestamp}]{Colors.RESET} "
            f"{color}{record.levelname:8}{Colors.RESET} "
            f"{Colors.CYAN}{record.name:20}{Colors.RESET} "
            f"{record.getMessage()}"
        )

        return formatted


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger.

    Usage:
        from backend.common.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Hello world")
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(getattr(logging, config.log_level.upper()))

        # Console handler with colors
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColoredFormatter())
        logger.addHandler(handler)

    return logger


# Module-level logger for convenience
logger = get_logger("belief_reaction")

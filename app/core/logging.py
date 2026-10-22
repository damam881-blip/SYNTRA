import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    numeric_level = logging.getLevelNamesMapping().get(level.upper())

    if numeric_level is None or not isinstance(numeric_level, int):
        raise ValueError(f"Invalid logging level: {level}")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    app_logger = logging.getLogger("network_simulator")
    app_logger.setLevel(numeric_level)

    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.propagate = False

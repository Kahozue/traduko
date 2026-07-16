"""System log: the service-side half of the design doc's log split (section 10).

Task-scoped events land in each task's logs/events.jsonl; everything the
resident service itself does lands here, under <data_root>/logs/core.log.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_HANDLER_NAME = "traduko-system-log"


def setup_system_log(root: Path) -> Path:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "core.log"
    package_logger = logging.getLogger("traduko")
    for handler in list(package_logger.handlers):
        if handler.get_name() == _HANDLER_NAME:
            if Path(getattr(handler, "baseFilename", "")) == path:
                return path
            package_logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    package_logger.addHandler(handler)
    if package_logger.level == logging.NOTSET:
        package_logger.setLevel(logging.INFO)
    return path

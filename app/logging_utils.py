from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: Path, debug: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO

    logger = logging.getLogger()
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    sh.setLevel(level)

    fh = RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(formatter)
    fh.setLevel(level)

    logger.addHandler(sh)
    logger.addHandler(fh)

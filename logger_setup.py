import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(
    log_dir: str = "logs",
    log_file: str = "live.log",
    level: int = logging.DEBUG,
) -> None:
    """Global logging initialization for the whole project.

    Called once in entrypoint (live_runner.main). Configures ROOT logger so
    any `logging.getLogger(__name__)` inherits handlers automatically.

    - creates logs directory
    - rotating main log
    - rotating error log
    - console log
    """

    os.makedirs(log_dir, exist_ok=True)
    path_main = os.path.join(log_dir, log_file)
    path_err = os.path.join(log_dir, "errors.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(level)

    # clear previous handlers to avoid duplicates
    root.handlers.clear()

    # main rotating file
    fh = RotatingFileHandler(
        path_main,
        maxBytes=10_000_000,
        backupCount=7,
        encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(level)

    # error-only file
    eh = RotatingFileHandler(
        path_err,
        maxBytes=10_000_000,
        backupCount=7,
        encoding="utf-8"
    )
    eh.setFormatter(fmt)
    eh.setLevel(logging.ERROR)

    # console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(level)

    root.addHandler(fh)
    root.addHandler(eh)
    root.addHandler(ch)

    logging.getLogger(__name__).info("Logging initialized -> %s", path_main)

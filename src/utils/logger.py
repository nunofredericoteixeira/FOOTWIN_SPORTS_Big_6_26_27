# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config.path_config import load_paths_config


DEFAULT_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)

DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    log_level: str = "INFO",
    log_filename: str = "footwin_main.log",
) -> logging.Logger:
    """
    Configura o sistema principal de logs do FOOTWIN SPORTS.

    Cria:
    - saída no Terminal;
    - ficheiro rotativo dentro da pasta logs;
    - proteção contra handlers duplicados.
    """

    paths = load_paths_config()
    logs_directory: Path = paths["logs"]

    logs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_path = logs_directory / log_filename

    numeric_level = getattr(
        logging,
        log_level.upper(),
        logging.INFO,
    )

    root_logger = logging.getLogger()

    root_logger.setLevel(numeric_level)

    formatter = logging.Formatter(
        fmt=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )

    _remove_existing_footwin_handlers(root_logger)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    console_handler._footwin_handler = True  # type: ignore[attr-defined]

    file_handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    file_handler._footwin_handler = True  # type: ignore[attr-defined]

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    logger = logging.getLogger("footwin")

    logger.info(
        "Sistema de logs configurado | nível=%s | ficheiro=%s",
        logging.getLevelName(numeric_level),
        log_path,
    )

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Devolve um logger identificado para um módulo.

    Exemplo:
        logger = get_logger("database")
    """

    cleaned_name = name.strip() or "general"

    return logging.getLogger(
        f"footwin.{cleaned_name}"
    )


def _remove_existing_footwin_handlers(
    logger: logging.Logger,
) -> None:
    """
    Remove apenas handlers anteriormente criados pelo FOOTWIN SPORTS.

    Evita mensagens duplicadas quando configure_logging()
    é executado mais do que uma vez.
    """

    handlers_to_remove = [
        handler
        for handler in logger.handlers
        if getattr(handler, "_footwin_handler", False)
    ]

    for handler in handlers_to_remove:
        logger.removeHandler(handler)
        handler.close()

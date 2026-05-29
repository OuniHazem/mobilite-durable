"""
utils/logger.py
===============
Logger centralisé — Projet Mobilité Durable
Basé sur Loguru : rotation automatique, thread-safe, niveau configurable.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from config.settings import settings

# Répertoire des logs
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Supprimer le handler par défaut de Loguru
logger.remove()

# Handler console
logger.add(
    sys.stdout,
    level=settings.log_level,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    colorize=True,
    enqueue=True,        # thread-safe
)

# Handler fichier rotatif
logger.add(
    LOG_DIR / "pipeline_{time:YYYY-MM-DD}.log",
    level=settings.log_level,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
    rotation="00:00",        # nouveau fichier chaque jour à minuit
    retention="30 days",     # garde 30 jours
    compression="zip",       # compresse les anciens logs
    enqueue=True,
    encoding="utf-8",
)


def get_logger(name: str):
    """Retourne un logger bindé au nom du module appelant."""
    return logger.bind(name=name)

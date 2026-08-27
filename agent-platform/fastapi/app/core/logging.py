"""
Agent Platform — Logging estructurado
Configura el logger raíz para emitir JSON en stdout.
Compatible con recolectores como Loki, Datadog, Papertrail, etc.
"""

import logging
import sys

from pythonjsonlogger import jsonlogger

from app.config import settings


def setup_logging() -> None:
    """
    Configura logging JSON estructurado en stdout.
    Llamar una sola vez al inicio de la aplicación (en lifespan).
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Handler principal: stdout (Docker captura stdout por defecto)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    # Configurar root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silenciar loggers muy verbosos de librerías externas
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

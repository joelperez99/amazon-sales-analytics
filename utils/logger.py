"""Registro de actividad y manejo centralizado de errores.

Escribe en consola y en ``logs/app.log`` con rotación.  Las funciones de ayuda
evitan que datos sensibles (contraseñas, tokens, cadenas de conexión) terminen en
los archivos de registro.
"""

from __future__ import annotations

import logging
import re
import sys
import traceback
import uuid
from logging.handlers import RotatingFileHandler
from typing import Any

from utils.config import get_settings

_CONFIGURADO = False

# Patrones que se enmascaran antes de escribir cualquier mensaje.
_PATRONES_SENSIBLES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(password|contrasena|contraseña|passwd|pwd)\s*[=:]\s*\S+"), r"\1=***"),
    (re.compile(r"(?i)(token|secret|api[_-]?key|authorization)\s*[=:]\s*\S+"), r"\1=***"),
    (re.compile(r"(?i)://([^:/@\s]+):([^@\s]+)@"), r"://\1:***@"),
)


class _FiltroSensible(logging.Filter):
    """Enmascara credenciales dentro del texto del registro."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            mensaje = record.getMessage()
        except Exception:  # pragma: no cover - formateo defectuoso
            return True
        limpio = mensaje
        for patron, reemplazo in _PATRONES_SENSIBLES:
            limpio = patron.sub(reemplazo, limpio)
        if limpio != mensaje:
            record.msg = limpio
            record.args = ()
        return True


def configurar_logging() -> None:
    """Configura los manejadores una sola vez por proceso."""
    global _CONFIGURADO
    if _CONFIGURADO:
        return

    settings = get_settings()
    nivel = getattr(logging, settings.log_level, logging.INFO)

    formato = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    raiz = logging.getLogger("amazon_analytics")
    raiz.setLevel(nivel)
    raiz.handlers.clear()
    raiz.propagate = False

    consola = logging.StreamHandler(stream=sys.stdout)
    consola.setFormatter(formato)
    consola.addFilter(_FiltroSensible())
    raiz.addHandler(consola)

    try:
        settings.ruta_logs.mkdir(parents=True, exist_ok=True)
        archivo = RotatingFileHandler(
            settings.ruta_logs / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        archivo.setFormatter(formato)
        archivo.addFilter(_FiltroSensible())
        raiz.addHandler(archivo)
    except OSError:  # pragma: no cover - sistema de archivos de solo lectura
        raiz.warning("No fue posible crear el archivo de registro; solo se usa la consola.")

    _CONFIGURADO = True


def get_logger(nombre: str) -> logging.Logger:
    """Devuelve un logger hijo del logger raíz de la aplicación."""
    configurar_logging()
    return logging.getLogger(f"amazon_analytics.{nombre}")


def registrar_error(logger: logging.Logger, error: Exception, contexto: str = "") -> str:
    """Registra una excepción con un identificador único y devuelve ese identificador.

    El identificador se muestra al usuario para que pueda reportar el problema sin
    que la interfaz exponga la traza interna.
    """
    id_error = uuid.uuid4().hex[:8].upper()
    logger.error(
        "[%s] %s | %s: %s\n%s",
        id_error,
        contexto or "error no controlado",
        type(error).__name__,
        error,
        traceback.format_exc(),
    )
    return id_error


def registrar_auditoria(
    accion: str,
    usuario_id: int | None = None,
    detalle: dict[str, Any] | None = None,
) -> None:
    """Escribe una entrada de auditoría en el registro y, si es posible, en la base de datos."""
    logger = get_logger("auditoria")
    logger.info("accion=%s usuario=%s detalle=%s", accion, usuario_id, detalle or {})
    try:
        # Importación diferida para evitar dependencia circular con la base de datos.
        from database.repositories import AuditRepository

        AuditRepository.registrar(accion=accion, usuario_id=usuario_id, detalle=detalle)
    except Exception:  # noqa: BLE001 - la auditoría nunca debe romper el flujo
        logger.debug("No fue posible persistir la auditoría en la base de datos.", exc_info=True)

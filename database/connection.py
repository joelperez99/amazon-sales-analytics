"""Conexión a la base de datos.

Funciona igual con SQLite (desarrollo local) y con PostgreSQL (producción): la
única diferencia es el valor de ``DATABASE_URL``.

Todo el acceso a datos pasa por SQLAlchemy con consultas parametrizadas, lo que
elimina por construcción el riesgo de inyección SQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from utils.config import BASE_DIR, get_settings
from utils.logger import get_logger

logger = get_logger("database")


def _normalizar_url(url: str) -> str:
    """Convierte una ruta relativa de SQLite en absoluta.

    Sin esto, la base de datos se crearía en el directorio desde el que se lanzó
    Streamlit, que no siempre es la raíz del proyecto.
    """
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        ruta_relativa = url.replace("sqlite:///", "", 1)
        if not Path(ruta_relativa).is_absolute():
            ruta = (BASE_DIR / ruta_relativa).resolve()
            ruta.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{ruta.as_posix()}"
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Devuelve el motor de SQLAlchemy (uno solo por proceso)."""
    settings = get_settings()
    url = _normalizar_url(settings.database_url)

    if url.startswith("sqlite"):
        # ``check_same_thread`` debe desactivarse porque Streamlit usa hilos.
        motor = create_engine(
            url,
            echo=settings.db_echo,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=StaticPool if ":memory:" in url else None,
        )

        @event.listens_for(motor, "connect")
        def _configurar_sqlite(conexion_dbapi, _registro) -> None:  # noqa: ANN001
            """Activa llaves foráneas y el modo WAL (mejor concurrencia)."""
            cursor = conexion_dbapi.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    else:
        motor = create_engine(
            url,
            echo=settings.db_echo,
            future=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,   # descarta conexiones muertas antes de usarlas
            pool_recycle=1800,
        )

    logger.info("Motor de base de datos creado (%s).", url.split("://", 1)[0])
    return motor


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Fábrica de sesiones enlazada al motor."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def obtener_sesion() -> Iterator[Session]:
    """Sesión con confirmación y reversión automáticas.

    Uso::

        with obtener_sesion() as sesion:
            sesion.add(objeto)
    """
    sesion = get_session_factory()()
    try:
        yield sesion
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()


def inicializar_base_de_datos() -> None:
    """Crea las tablas y los índices si no existen.

    Es idempotente: puede llamarse en cada arranque sin efectos secundarios.
    """
    from database.models import Base

    motor = get_engine()
    Base.metadata.create_all(motor)
    logger.info("Esquema de base de datos verificado.")


def probar_conexion() -> tuple[bool, str]:
    """Comprueba que la base de datos responde.

    Returns:
        ``(exito, mensaje)`` para mostrar en la página de configuración.
    """
    try:
        with get_engine().connect() as conexion:
            conexion.execute(text("SELECT 1"))
        url = get_settings().database_url
        motor = url.split("://", 1)[0]
        return True, f"Conexión correcta ({motor})."
    except Exception as error:  # noqa: BLE001
        from utils.logger import registrar_error

        id_error = registrar_error(logger, error, "prueba de conexión")
        return False, f"No fue posible conectar con la base de datos. Referencia: {id_error}."

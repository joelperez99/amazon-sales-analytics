"""Configuración central de la aplicación.

Todos los secretos y parámetros se leen de variables de entorno (archivo ``.env``)
y se validan con Pydantic.  Ningún valor sensible está escrito en el código.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

# Raíz del proyecto: .../amazon_sales_saas
BASE_DIR = Path(__file__).resolve().parent.parent

# Carga el .env si existe (no falla si no está presente: se usan los valores por defecto)
load_dotenv(BASE_DIR / ".env", override=False)


def _env(clave: str, defecto: str = "") -> str:
    """Devuelve una variable de entorno como texto ya recortado."""
    valor = os.getenv(clave)
    return valor.strip() if valor is not None else defecto


def _env_bool(clave: str, defecto: bool = False) -> bool:
    valor = _env(clave)
    if not valor:
        return defecto
    return valor.lower() in {"1", "true", "yes", "si", "sí", "on"}


def _env_int(clave: str, defecto: int) -> int:
    try:
        return int(float(_env(clave) or defecto))
    except (TypeError, ValueError):
        return defecto


def _env_float(clave: str, defecto: float) -> float:
    try:
        return float(_env(clave) or defecto)
    except (TypeError, ValueError):
        return defecto


class UmbralesAlertas(BaseModel):
    """Umbrales configurables que disparan los hallazgos automáticos."""

    caida_ventas_pct: float = 15.0
    tasa_reembolso_pct: float = 5.0
    pct_cargos_pct: float = 35.0
    concentracion_sku_pct: float = 40.0
    dias_sin_venta: int = 7
    tolerancia_conciliacion: float = 1.0


class Settings(BaseModel):
    """Configuración validada de la aplicación."""

    # Aplicación
    app_name: str = "Amazon Sales Analytics"
    app_env: str = "development"
    log_level: str = "INFO"
    timezone: str = "America/Mexico_City"

    # Base de datos
    database_url: str = "sqlite:///./data/amazon_analytics.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Autenticación
    auth_enabled: bool = True
    demo_mode: bool = True
    demo_email: str = "demo@amazonanalytics.mx"
    demo_password: str = "Demo1234!"
    session_secret: str = "clave-de-desarrollo-no-usar-en-produccion"
    session_timeout_minutes: int = 480
    #: Días que dura la cookie de "recordarme": mantiene la sesión iniciada aunque
    #: se reinicie el servidor (p. ej. al ajustar código durante el desarrollo).
    session_cookie_days: int = 30
    password_min_length: int = 8

    # Almacenamiento
    storage_backend: str = "local"
    storage_local_path: str = "./data/uploads"
    file_retention_days: int = 365
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_bucket: str = "reportes"

    # Límites de carga
    max_file_size_mb: int = 200
    allowed_extensions: tuple[str, ...] = (".csv", ".xlsx", ".xls")
    csv_chunk_size: int = 100_000

    # Alertas
    alertas: UmbralesAlertas = Field(default_factory=UmbralesAlertas)

    # Facturación
    billing_enabled: bool = False

    @field_validator("storage_backend")
    @classmethod
    def _validar_backend(cls, valor: str) -> str:
        permitidos = {"local", "s3", "supabase"}
        if valor not in permitidos:
            raise ValueError(f"STORAGE_BACKEND debe ser uno de {permitidos}")
        return valor

    @field_validator("app_env")
    @classmethod
    def _validar_entorno(cls, valor: str) -> str:
        if valor not in {"development", "production", "test"}:
            raise ValueError("APP_ENV debe ser development, production o test")
        return valor

    # ---------------------------------------------------------------- helpers
    @property
    def es_produccion(self) -> bool:
        return self.app_env == "production"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def ruta_almacenamiento(self) -> Path:
        """Ruta absoluta donde se guardan los archivos subidos (backend local)."""
        ruta = Path(self.storage_local_path)
        if not ruta.is_absolute():
            ruta = BASE_DIR / ruta
        return ruta

    @property
    def ruta_datos(self) -> Path:
        """Carpeta ``data/`` del proyecto."""
        return BASE_DIR / "data"

    @property
    def ruta_logs(self) -> Path:
        return BASE_DIR / "logs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devuelve la configuración (memorizada: se lee una sola vez por proceso)."""
    extensiones = _env("ALLOWED_EXTENSIONS", ".csv,.xlsx,.xls")
    lista_ext = tuple(
        ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
        for ext in extensiones.split(",")
        if ext.strip()
    )

    settings = Settings(
        app_name=_env("APP_NAME", "Amazon Sales Analytics"),
        app_env=_env("APP_ENV", "development"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        timezone=_env("TIMEZONE", "America/Mexico_City"),
        database_url=_env("DATABASE_URL", "sqlite:///./data/amazon_analytics.db"),
        db_echo=_env_bool("DB_ECHO", False),
        db_pool_size=_env_int("DB_POOL_SIZE", 5),
        db_max_overflow=_env_int("DB_MAX_OVERFLOW", 10),
        auth_enabled=_env_bool("AUTH_ENABLED", True),
        demo_mode=_env_bool("DEMO_MODE", True),
        demo_email=_env("DEMO_EMAIL", "demo@amazonanalytics.mx"),
        demo_password=_env("DEMO_PASSWORD", "Demo1234!"),
        session_secret=_env("SESSION_SECRET", "clave-de-desarrollo-no-usar-en-produccion"),
        session_timeout_minutes=_env_int("SESSION_TIMEOUT_MINUTES", 480),
        session_cookie_days=_env_int("SESSION_COOKIE_DAYS", 30),
        password_min_length=_env_int("PASSWORD_MIN_LENGTH", 8),
        storage_backend=_env("STORAGE_BACKEND", "local").lower(),
        storage_local_path=_env("STORAGE_LOCAL_PATH", "./data/uploads"),
        file_retention_days=_env_int("FILE_RETENTION_DAYS", 365),
        s3_bucket=_env("S3_BUCKET"),
        s3_region=_env("S3_REGION", "us-east-1"),
        supabase_url=_env("SUPABASE_URL"),
        supabase_key=_env("SUPABASE_KEY"),
        supabase_bucket=_env("SUPABASE_BUCKET", "reportes"),
        max_file_size_mb=_env_int("MAX_FILE_SIZE_MB", 200),
        allowed_extensions=lista_ext or (".csv", ".xlsx", ".xls"),
        csv_chunk_size=_env_int("CSV_CHUNK_SIZE", 100_000),
        billing_enabled=_env_bool("BILLING_ENABLED", False),
        alertas=UmbralesAlertas(
            caida_ventas_pct=_env_float("ALERTA_CAIDA_VENTAS_PCT", 15.0),
            tasa_reembolso_pct=_env_float("ALERTA_TASA_REEMBOLSO_PCT", 5.0),
            pct_cargos_pct=_env_float("ALERTA_PCT_CARGOS_PCT", 35.0),
            concentracion_sku_pct=_env_float("ALERTA_CONCENTRACION_SKU_PCT", 40.0),
            dias_sin_venta=_env_int("ALERTA_DIAS_SIN_VENTA", 7),
            tolerancia_conciliacion=_env_float("ALERTA_TOLERANCIA_CONCILIACION", 1.0),
        ),
    )

    # Crea las carpetas necesarias en el primer arranque.
    for carpeta in (settings.ruta_datos, settings.ruta_logs, settings.ruta_almacenamiento):
        carpeta.mkdir(parents=True, exist_ok=True)

    return settings

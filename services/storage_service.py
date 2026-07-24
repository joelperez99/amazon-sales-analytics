"""Almacenamiento de archivos, con backend configurable.

Backends disponibles (``STORAGE_BACKEND`` en el ``.env``):

* ``local``    — carpeta del servidor.  Es el modo por omisión.
* ``s3``       — Amazon S3 (requiere ``boto3``).
* ``supabase`` — Supabase Storage (requiere el paquete ``supabase``).

Los tres exponen la misma interfaz, así que cambiar de backend no toca el resto
de la aplicación.

Seguridad
---------
* El nombre del archivo se sanea antes de escribirse (sin ``../`` ni rutas).
* Cada organización escribe en su propio subdirectorio.
* Antes de escribir se verifica que la ruta final quede dentro del directorio
  base: eso cierra la puerta al recorrido de directorios.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from utils.config import get_settings
from utils.logger import get_logger, registrar_error
from utils.validations import sanear_nombre_archivo

logger = get_logger("storage_service")


class BaseStorage(ABC):
    """Contrato que cumple cualquier backend de almacenamiento."""

    nombre: str = "base"

    @abstractmethod
    def guardar(self, contenido: bytes, nombre_archivo: str, organization_id: int) -> str:
        """Guarda el archivo y devuelve su ruta o clave."""

    @abstractmethod
    def leer(self, ruta: str) -> bytes:
        """Recupera el contenido de un archivo guardado."""

    @abstractmethod
    def eliminar(self, ruta: str) -> bool:
        """Elimina el archivo.  Devuelve ``True`` si existía y se borró."""

    @abstractmethod
    def existe(self, ruta: str) -> bool:
        """``True`` si el archivo sigue disponible."""


def _nombre_unico(nombre_archivo: str) -> str:
    """Antepone una marca de tiempo para que dos cargas no se pisen."""
    seguro = sanear_nombre_archivo(nombre_archivo)
    marca = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
    return f"{marca}_{seguro}"


class LocalStorage(BaseStorage):
    """Guarda los archivos en el sistema de archivos del servidor."""

    nombre = "local"

    def __init__(self, ruta_base: Path | None = None) -> None:
        settings = get_settings()
        self.ruta_base = Path(ruta_base or settings.ruta_almacenamiento).resolve()
        self.ruta_base.mkdir(parents=True, exist_ok=True)

    def _ruta_organizacion(self, organization_id: int) -> Path:
        carpeta = self.ruta_base / f"org_{int(organization_id)}"
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta

    def _validar_dentro_de_base(self, ruta: Path) -> Path:
        """Impide escribir o leer fuera del directorio de almacenamiento."""
        resuelta = ruta.resolve()
        if not str(resuelta).startswith(str(self.ruta_base)):
            raise ValueError("Ruta de archivo fuera del directorio permitido.")
        return resuelta

    def guardar(self, contenido: bytes, nombre_archivo: str, organization_id: int) -> str:
        destino = self._ruta_organizacion(organization_id) / _nombre_unico(nombre_archivo)
        destino = self._validar_dentro_de_base(destino)
        destino.write_bytes(contenido)
        logger.info("Archivo guardado (%d bytes) para la organización %d.", len(contenido), organization_id)
        return str(destino)

    def leer(self, ruta: str) -> bytes:
        return self._validar_dentro_de_base(Path(ruta)).read_bytes()

    def eliminar(self, ruta: str) -> bool:
        try:
            objetivo = self._validar_dentro_de_base(Path(ruta))
        except ValueError:
            logger.warning("Se intentó eliminar un archivo fuera del directorio permitido.")
            return False
        if objetivo.exists():
            objetivo.unlink()
            return True
        return False

    def existe(self, ruta: str) -> bool:
        try:
            return self._validar_dentro_de_base(Path(ruta)).exists()
        except ValueError:
            return False

    def espacio_usado(self, organization_id: int) -> int:
        """Bytes ocupados por la organización."""
        carpeta = self._ruta_organizacion(organization_id)
        return sum(f.stat().st_size for f in carpeta.glob("**/*") if f.is_file())

    def vaciar_organizacion(self, organization_id: int) -> None:
        """Elimina todos los archivos de una organización (baja de cuenta)."""
        carpeta = self._ruta_organizacion(organization_id)
        if carpeta.exists():
            shutil.rmtree(carpeta, ignore_errors=True)


class S3Storage(BaseStorage):
    """Guarda los archivos en un bucket de Amazon S3."""

    nombre = "s3"

    def __init__(self) -> None:
        settings = get_settings()
        try:
            import boto3
        except ImportError as error:  # pragma: no cover
            raise RuntimeError(
                "STORAGE_BACKEND=s3 requiere el paquete boto3. Instálalo con: pip install boto3"
            ) from error

        if not settings.s3_bucket:
            raise RuntimeError("Falta configurar S3_BUCKET en el archivo .env.")

        # Las credenciales las toma boto3 del entorno; nunca se escriben en el código.
        self.cliente = boto3.client("s3", region_name=settings.s3_region)
        self.bucket = settings.s3_bucket

    def guardar(self, contenido: bytes, nombre_archivo: str, organization_id: int) -> str:
        clave = f"org_{int(organization_id)}/{_nombre_unico(nombre_archivo)}"
        self.cliente.put_object(
            Bucket=self.bucket, Key=clave, Body=contenido, ServerSideEncryption="AES256"
        )
        return clave

    def leer(self, ruta: str) -> bytes:
        respuesta = self.cliente.get_object(Bucket=self.bucket, Key=ruta)
        return respuesta["Body"].read()

    def eliminar(self, ruta: str) -> bool:
        self.cliente.delete_object(Bucket=self.bucket, Key=ruta)
        return True

    def existe(self, ruta: str) -> bool:
        try:
            self.cliente.head_object(Bucket=self.bucket, Key=ruta)
            return True
        except Exception:  # noqa: BLE001 - botocore.ClientError incluida
            return False


class SupabaseStorage(BaseStorage):
    """Guarda los archivos en un bucket de Supabase Storage."""

    nombre = "supabase"

    def __init__(self) -> None:
        settings = get_settings()
        try:
            from supabase import create_client
        except ImportError as error:  # pragma: no cover
            raise RuntimeError(
                "STORAGE_BACKEND=supabase requiere el paquete supabase. "
                "Instálalo con: pip install supabase"
            ) from error

        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("Faltan SUPABASE_URL y SUPABASE_KEY en el archivo .env.")

        self.cliente = create_client(settings.supabase_url, settings.supabase_key)
        self.bucket = settings.supabase_bucket

    def guardar(self, contenido: bytes, nombre_archivo: str, organization_id: int) -> str:
        clave = f"org_{int(organization_id)}/{_nombre_unico(nombre_archivo)}"
        self.cliente.storage.from_(self.bucket).upload(clave, contenido)
        return clave

    def leer(self, ruta: str) -> bytes:
        return self.cliente.storage.from_(self.bucket).download(ruta)

    def eliminar(self, ruta: str) -> bool:
        self.cliente.storage.from_(self.bucket).remove([ruta])
        return True

    def existe(self, ruta: str) -> bool:
        try:
            self.cliente.storage.from_(self.bucket).download(ruta)
            return True
        except Exception:  # noqa: BLE001
            return False


_INSTANCIA: BaseStorage | None = None


def get_storage() -> BaseStorage:
    """Devuelve el backend configurado.

    Si el backend en la nube no puede inicializarse (falta una credencial o el
    paquete), se registra el problema y se cae al almacenamiento local para que
    la aplicación siga funcionando.
    """
    global _INSTANCIA
    if _INSTANCIA is not None:
        return _INSTANCIA

    backend = get_settings().storage_backend
    try:
        if backend == "s3":
            _INSTANCIA = S3Storage()
        elif backend == "supabase":
            _INSTANCIA = SupabaseStorage()
        else:
            _INSTANCIA = LocalStorage()
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, f"inicialización del backend «{backend}»")
        logger.warning("Se usará almacenamiento local como respaldo.")
        _INSTANCIA = LocalStorage()

    logger.info("Backend de almacenamiento activo: %s", _INSTANCIA.nombre)
    return _INSTANCIA


def aplicar_retencion(organization_id: int) -> int:
    """Elimina los archivos que superaron la política de retención.

    Returns:
        Número de archivos eliminados.
    """
    from database.repositories import FileRepository

    settings = get_settings()
    dias = settings.file_retention_days
    if dias <= 0:
        return 0

    almacenamiento = get_storage()
    eliminados = 0
    for archivo_id, ruta in FileRepository.antiguos(organization_id, dias):
        try:
            almacenamiento.eliminar(ruta)
            FileRepository.marcar_eliminado(archivo_id, organization_id)
            eliminados += 1
        except Exception as error:  # noqa: BLE001
            registrar_error(logger, error, f"eliminación del archivo {archivo_id}")

    if eliminados:
        logger.info(
            "Política de retención: %d archivos eliminados de la organización %d.",
            eliminados, organization_id,
        )
    return eliminados

"""Orquestación de la carga de archivos.

Encadena todo el flujo de importación:

    validar → guardar en el almacenamiento → leer → limpiar → concatenar →
    persistir en la base de datos → registrar la importación

Y mantiene el estado de la sesión de Streamlit (los datos activos del tablero).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, BinaryIO

import pandas as pd
import streamlit as st

from database.repositories import FileRepository, ImportRepository
from services.amazon_parser import ResultadoLectura, leer_archivo
from services.auth_service import (
    Sesion,
    verificar_limite_archivos,
    verificar_limite_filas,
)
from services.data_cleaner import (
    ReporteLimpieza,
    concatenar_reportes,
    limpiar_dataframe,
)
from services.storage_service import get_storage
from utils.config import get_settings
from utils.constants import COL_FECHA
from utils.logger import get_logger, registrar_auditoria, registrar_error
from utils.validations import (
    ResultadoValidacion,
    validar_archivo_subido,
    validar_columnas,
    validar_dataframe,
)

logger = get_logger("file_service")

# --- Claves del estado de sesión --------------------------------------------
CLAVE_DATOS = "df_datos"
CLAVE_ARCHIVOS = "archivos_procesados"
CLAVE_REPORTE = "reporte_limpieza"
CLAVE_CATALOGO = "catalogo_costos"
CLAVE_FILTROS = "filtros"
CLAVE_EXCLUIR_DUPLICADOS = "excluir_duplicados"


@dataclass
class ResultadoImportacion:
    """Resultado de procesar uno o varios archivos."""

    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    archivos: list[dict[str, Any]] = field(default_factory=list)
    reportes: list[ReporteLimpieza] = field(default_factory=list)
    validacion: ResultadoValidacion = field(default_factory=ResultadoValidacion)
    duplicados: int = 0
    filas_totales: int = 0
    lecturas: list[ResultadoLectura] = field(default_factory=list)

    @property
    def exitoso(self) -> bool:
        return self.validacion.valido and not self.df.empty


# =============================================================================
# Procesamiento de archivos
# =============================================================================


def procesar_archivos(
    archivos: list[BinaryIO],
    sesion: Sesion,
    mapeo_manual: dict[str, dict[str, str]] | None = None,
    guardar_en_bd: bool = True,
    barra_progreso: Any | None = None,
) -> ResultadoImportacion:
    """Procesa la lista de archivos subidos por el usuario.

    Args:
        archivos: objetos ``UploadedFile`` de Streamlit.
        sesion: sesión del usuario (define la organización propietaria).
        mapeo_manual: ``{nombre_archivo: {encabezado_original: columna_canónica}}``.
        guardar_en_bd: si se persisten las transacciones para el histórico.
        barra_progreso: objeto ``st.progress`` opcional para mostrar el avance.

    Returns:
        :class:`ResultadoImportacion` con los datos ya limpios y unidos.
    """
    settings = get_settings()
    resultado = ResultadoImportacion()
    almacenamiento = get_storage()
    dataframes: list[pd.DataFrame] = []

    # --- Límite del plan -----------------------------------------------------
    permitido, mensaje = verificar_limite_archivos(sesion)
    if not permitido:
        resultado.validacion.agregar_error(mensaje)
        return resultado

    total = max(len(archivos), 1)

    for indice, archivo in enumerate(archivos):
        nombre = getattr(archivo, "name", f"archivo_{indice + 1}")
        if barra_progreso is not None:
            barra_progreso.progress(
                indice / total, text=f"Procesando «{nombre}» ({indice + 1} de {len(archivos)})…"
            )

        try:
            contenido = _leer_bytes(archivo)

            # 1. Validación de extensión y tamaño.
            validacion = validar_archivo_subido(nombre, len(contenido))
            if not validacion.valido:
                resultado.validacion.unir(validacion)
                continue

            # 2. Lectura y normalización de encabezados.
            lectura = leer_archivo(
                contenido, nombre, mapeo_manual=(mapeo_manual or {}).get(nombre)
            )
            resultado.lecturas.append(lectura)

            # 3. Columnas mínimas.
            validacion_columnas = validar_columnas(lectura.columnas_detectadas)
            if not validacion_columnas.valido:
                resultado.validacion.errores.extend(
                    f"«{nombre}»: {e}" for e in validacion_columnas.errores
                )
                resultado.validacion.valido = False
                continue
            resultado.validacion.advertencias.extend(
                f"«{nombre}»: {a}" for a in validacion_columnas.advertencias
            )

            # 4. Límite de filas del plan.
            permitido_filas, mensaje_filas = verificar_limite_filas(sesion, lectura.filas)
            if not permitido_filas:
                resultado.validacion.agregar_error(f"«{nombre}»: {mensaje_filas}")
                continue

            # 5. Limpieza.
            df_limpio, reporte = limpiar_dataframe(lectura.df)
            resultado.reportes.append(reporte)

            validacion_datos = validar_dataframe(df_limpio)
            resultado.validacion.advertencias.extend(
                f"«{nombre}»: {a}" for a in validacion_datos.advertencias
            )

            if df_limpio.empty:
                resultado.validacion.agregar_advertencia(
                    f"«{nombre}» no aportó registros utilizables."
                )
                continue

            dataframes.append(df_limpio)

            # 6. Guardado del archivo original y registro en la base de datos.
            info_archivo: dict[str, Any] = {
                "nombre": nombre,
                "filas": lectura.filas,
                "columnas": lectura.columnas,
                "encoding": lectura.encoding,
                "delimitador": lectura.delimitador,
                "sin_reconocer": lectura.columnas_sin_reconocer,
                "bytes": len(contenido),
            }

            if guardar_en_bd:
                info_archivo.update(
                    _persistir_archivo(
                        contenido, nombre, sesion, lectura, df_limpio, reporte, almacenamiento
                    )
                )

            resultado.archivos.append(info_archivo)

        except ValueError as error:
            # Errores esperados (formato no compatible, archivo vacío).
            resultado.validacion.agregar_error(str(error))
        except Exception as error:  # noqa: BLE001
            id_error = registrar_error(logger, error, f"procesamiento de «{nombre}»")
            resultado.validacion.agregar_error(
                f"«{nombre}»: no se pudo procesar. Referencia del error: {id_error}."
            )

    if barra_progreso is not None:
        barra_progreso.progress(1.0, text="Consolidando los reportes…")

    # --- Unión de todos los archivos -----------------------------------------
    if dataframes:
        resultado.df, resultado.duplicados = concatenar_reportes(dataframes)
        resultado.filas_totales = len(resultado.df)
        if resultado.duplicados:
            resultado.validacion.agregar_advertencia(
                f"Se detectaron {resultado.duplicados:,} registros repetidos entre los archivos "
                "cargados. Puedes excluirlos con la casilla de abajo."
            )
    else:
        if not resultado.validacion.errores:
            resultado.validacion.agregar_error(
                "Ningún archivo aportó registros. Revisa que sean reportes de transacciones de Amazon."
            )

    registrar_auditoria(
        "carga_archivos",
        sesion.user_id,
        {"archivos": len(resultado.archivos), "filas": resultado.filas_totales},
    )
    return resultado


def _leer_bytes(archivo: BinaryIO) -> bytes:
    """Lee el contenido completo de un archivo subido y regresa el cursor al inicio."""
    try:
        archivo.seek(0)
    except (AttributeError, OSError):
        pass
    contenido = archivo.read()
    try:
        archivo.seek(0)
    except (AttributeError, OSError):
        pass
    return contenido if isinstance(contenido, bytes) else bytes(contenido)


def _persistir_archivo(
    contenido: bytes,
    nombre: str,
    sesion: Sesion,
    lectura: ResultadoLectura,
    df_limpio: pd.DataFrame,
    reporte: ReporteLimpieza,
    almacenamiento: Any,
) -> dict[str, Any]:
    """Guarda el archivo y registra la importación.  Nunca interrumpe el flujo."""
    import hashlib
    from pathlib import Path

    info: dict[str, Any] = {}
    try:
        hash_contenido = hashlib.sha256(contenido).hexdigest()
        info["ya_existia"] = FileRepository.existe_hash(sesion.organization_id, hash_contenido)

        ruta = almacenamiento.guardar(contenido, nombre, sesion.organization_id)
        archivo_id = FileRepository.registrar(
            user_id=sesion.user_id,
            organization_id=sesion.organization_id,
            nombre_original=nombre,
            nombre_almacenado=Path(ruta).name,
            ruta=ruta,
            backend=almacenamiento.nombre,
            extension=Path(nombre).suffix.lower(),
            tamano_bytes=len(contenido),
            hash_contenido=hash_contenido,
            filas=lectura.filas,
            columnas=lectura.columnas,
        )
        info["archivo_id"] = archivo_id

        inicio, fin = _rango_del_dataframe(df_limpio)
        import_id = ImportRepository.crear(
            user_id=sesion.user_id,
            organization_id=sesion.organization_id,
            uploaded_file_id=archivo_id,
            filas_leidas=reporte.filas_entrada,
            filas_validas=reporte.filas_salida,
            filas_descartadas=reporte.filas_descartadas,
            duplicados=reporte.duplicados_detectados,
            periodo_inicio=inicio,
            periodo_fin=fin,
            mensaje=" | ".join(reporte.mensajes),
        )
        info["import_id"] = import_id

        info["guardadas"] = ImportRepository.guardar_transacciones(
            df_limpio,
            user_id=sesion.user_id,
            organization_id=sesion.organization_id,
            import_id=import_id,
            uploaded_file_id=archivo_id,
        )
    except Exception as error:  # noqa: BLE001 - el análisis debe continuar aunque falle el guardado
        id_error = registrar_error(logger, error, f"persistencia de «{nombre}»")
        info["error_persistencia"] = id_error
        logger.warning(
            "El archivo «%s» se analizó pero no se pudo guardar en el histórico (%s).",
            nombre, id_error,
        )
    return info


def _rango_del_dataframe(df: pd.DataFrame) -> tuple[date | None, date | None]:
    """Primera y última fecha con datos."""
    if df.empty or COL_FECHA not in df.columns:
        return None, None
    fechas = pd.to_datetime(df[COL_FECHA], errors="coerce").dropna()
    if fechas.empty:
        return None, None
    return fechas.min().date(), fechas.max().date()


# =============================================================================
# Estado de la sesión
# =============================================================================


def guardar_datos_en_sesion(resultado: ResultadoImportacion, reemplazar: bool = True) -> None:
    """Deja los datos importados disponibles para todas las páginas.

    Args:
        reemplazar: ``True`` sustituye lo cargado; ``False`` lo acumula.
    """
    if resultado.df.empty:
        return

    if reemplazar or CLAVE_DATOS not in st.session_state:
        st.session_state[CLAVE_DATOS] = resultado.df
        st.session_state[CLAVE_ARCHIVOS] = resultado.archivos
    else:
        unido, _ = concatenar_reportes([st.session_state[CLAVE_DATOS], resultado.df])
        st.session_state[CLAVE_DATOS] = unido
        st.session_state[CLAVE_ARCHIVOS] = (
            st.session_state.get(CLAVE_ARCHIVOS, []) + resultado.archivos
        )

    st.session_state[CLAVE_REPORTE] = resultado.reportes
    # Los filtros se reinician: los valores disponibles cambiaron.
    st.session_state.pop(CLAVE_FILTROS, None)


def obtener_datos() -> pd.DataFrame:
    """DataFrame activo del tablero (vacío si aún no se ha cargado nada)."""
    df = st.session_state.get(CLAVE_DATOS)
    if df is None:
        return pd.DataFrame()

    if st.session_state.get(CLAVE_EXCLUIR_DUPLICADOS, False):
        from services.data_cleaner import aplicar_exclusion_duplicados

        return aplicar_exclusion_duplicados(df, True)
    return df


def hay_datos() -> bool:
    """``True`` si hay datos cargados en la sesión."""
    df = st.session_state.get(CLAVE_DATOS)
    return df is not None and not df.empty


def limpiar_datos_sesion() -> None:
    """Descarta los datos cargados sin cerrar la sesión."""
    for clave in (CLAVE_DATOS, CLAVE_ARCHIVOS, CLAVE_REPORTE, CLAVE_FILTROS):
        st.session_state.pop(clave, None)


def cargar_historico(sesion: Sesion, desde: date | None = None, hasta: date | None = None) -> int:
    """Trae el histórico guardado en la base de datos al tablero.

    Returns:
        Número de filas cargadas.
    """
    try:
        df = ImportRepository.cargar_transacciones(sesion.organization_id, desde, hasta)
    except Exception as error:  # noqa: BLE001
        id_error = registrar_error(logger, error, "carga del histórico")
        st.error(f"No fue posible cargar el histórico. Referencia: {id_error}.")
        return 0

    if df.empty:
        return 0

    st.session_state[CLAVE_DATOS] = df
    st.session_state[CLAVE_ARCHIVOS] = [{"nombre": "Histórico de la cuenta", "filas": len(df)}]
    st.session_state.pop(CLAVE_FILTROS, None)
    return len(df)


def cargar_datos_demo() -> int:
    """Carga el archivo de ejemplo incluido en el proyecto.

    Returns:
        Número de filas cargadas, o ``0`` si no se encontró el archivo.
    """
    settings = get_settings()
    ruta_demo = settings.ruta_datos / "demo" / "transacciones_demo.csv"

    if not ruta_demo.exists():
        # Se genera al vuelo la primera vez.
        try:
            from scripts.generar_datos_demo import generar_archivo_demo

            generar_archivo_demo(ruta_demo)
        except Exception as error:  # noqa: BLE001
            registrar_error(logger, error, "generación de datos de demostración")
            return 0

    try:
        lectura = leer_archivo(ruta_demo.read_bytes(), ruta_demo.name)
        df_limpio, reporte = limpiar_dataframe(lectura.df)
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "lectura de los datos de demostración")
        return 0

    st.session_state[CLAVE_DATOS] = df_limpio
    st.session_state[CLAVE_ARCHIVOS] = [{
        "nombre": ruta_demo.name,
        "filas": lectura.filas,
        "columnas": lectura.columnas,
        "demo": True,
    }]
    st.session_state[CLAVE_REPORTE] = [reporte]
    st.session_state.pop(CLAVE_FILTROS, None)
    return len(df_limpio)

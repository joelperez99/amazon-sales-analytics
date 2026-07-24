"""Validación de archivos, columnas y datos de entrada.

Incluye los modelos Pydantic que describen la forma esperada de los registros y
las funciones de seguridad aplicadas a los archivos que sube el usuario.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
from pydantic import BaseModel, EmailStr, Field, field_validator

from utils.config import get_settings
from utils.constants import (
    COLUMNAS_RECOMENDADAS,
    COLUMNAS_REQUERIDAS,
    ETIQUETAS_COLUMNAS,
    LLAVE_DUPLICADOS,
)

# =============================================================================
# Resultado de una validación
# =============================================================================


class ResultadoValidacion(BaseModel):
    """Resultado uniforme de cualquier validación de la aplicación."""

    valido: bool = True
    errores: list[str] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)
    detalle: dict[str, Any] = Field(default_factory=dict)

    def agregar_error(self, mensaje: str) -> None:
        self.errores.append(mensaje)
        self.valido = False

    def agregar_advertencia(self, mensaje: str) -> None:
        self.advertencias.append(mensaje)

    def unir(self, otro: "ResultadoValidacion") -> "ResultadoValidacion":
        self.errores.extend(otro.errores)
        self.advertencias.extend(otro.advertencias)
        self.detalle.update(otro.detalle)
        self.valido = self.valido and otro.valido
        return self


# =============================================================================
# Modelos de entrada
# =============================================================================


class RegistroCosto(BaseModel):
    """Una fila del catálogo de costos por SKU."""

    sku: str
    costo_unitario: float = 0.0
    costo_logistico_adicional: float = 0.0
    gasto_publicitario: float = 0.0
    marca: str = ""
    categoria: str = ""

    @field_validator("sku")
    @classmethod
    def _sku_no_vacio(cls, valor: str) -> str:
        limpio = str(valor).strip()
        if not limpio:
            raise ValueError("El SKU no puede estar vacío.")
        return limpio

    @field_validator("costo_unitario", "costo_logistico_adicional", "gasto_publicitario")
    @classmethod
    def _no_negativo(cls, valor: float) -> float:
        if valor < 0:
            raise ValueError("Los costos no pueden ser negativos.")
        return float(valor)


class RegistroUsuario(BaseModel):
    """Datos de alta de un usuario nuevo."""

    email: EmailStr
    nombre: str
    password: str
    organizacion: str = ""

    @field_validator("nombre")
    @classmethod
    def _nombre_valido(cls, valor: str) -> str:
        limpio = " ".join(str(valor).split())
        if len(limpio) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres.")
        return limpio

    @field_validator("password")
    @classmethod
    def _password_segura(cls, valor: str) -> str:
        minimo = get_settings().password_min_length
        if len(valor) < minimo:
            raise ValueError(f"La contraseña debe tener al menos {minimo} caracteres.")
        if not re.search(r"[A-Za-z]", valor) or not re.search(r"\d", valor):
            raise ValueError("La contraseña debe combinar letras y números.")
        return valor


# =============================================================================
# Seguridad de archivos
# =============================================================================

#: Caracteres permitidos en un nombre de archivo ya saneado.
_PATRON_NOMBRE_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")


def sanear_nombre_archivo(nombre: str, largo_max: int = 120) -> str:
    """Devuelve un nombre de archivo seguro.

    Elimina rutas (``../``, ``C:\\``), acentos y cualquier carácter que no sea
    alfanumérico, punto, guion o guion bajo.  Esto evita el recorrido de
    directorios al guardar archivos subidos por el usuario.
    """
    if not nombre:
        return "archivo_sin_nombre"

    # Solo el nombre base: descarta cualquier componente de ruta.
    base = Path(str(nombre)).name

    # Quita acentos para evitar problemas de codificación en distintos sistemas.
    base = unicodedata.normalize("NFKD", base)
    base = "".join(c for c in base if not unicodedata.combining(c))

    limpio = _PATRON_NOMBRE_SEGURO.sub("_", base).strip("._")
    if not limpio:
        limpio = "archivo"

    # Recorta conservando la extensión.
    if len(limpio) > largo_max:
        sufijo = Path(limpio).suffix[:10]
        limpio = limpio[: largo_max - len(sufijo)] + sufijo
    return limpio


def validar_archivo_subido(
    nombre: str, tamano_bytes: int, extensiones_permitidas: tuple[str, ...] | None = None
) -> ResultadoValidacion:
    """Valida extensión y tamaño antes de leer un archivo."""
    settings = get_settings()
    resultado = ResultadoValidacion()
    permitidas = extensiones_permitidas or settings.allowed_extensions

    extension = Path(str(nombre)).suffix.lower()
    if extension not in permitidas:
        resultado.agregar_error(
            f"«{nombre}»: la extensión «{extension or 'sin extensión'}» no está permitida. "
            f"Formatos aceptados: {', '.join(permitidas)}."
        )

    if tamano_bytes <= 0:
        resultado.agregar_error(f"«{nombre}» está vacío.")
    elif tamano_bytes > settings.max_file_size_bytes:
        resultado.agregar_error(
            f"«{nombre}» pesa {tamano_bytes / 1024 / 1024:.1f} MB y el límite es "
            f"{settings.max_file_size_mb} MB."
        )

    resultado.detalle["nombre_seguro"] = sanear_nombre_archivo(nombre)
    resultado.detalle["extension"] = extension
    resultado.detalle["tamano_bytes"] = tamano_bytes
    return resultado


def calcular_hash_archivo(flujo: BinaryIO, bloque: int = 1024 * 1024) -> str:
    """SHA-256 del contenido de un archivo, leído por bloques."""
    hasher = hashlib.sha256()
    posicion = flujo.tell()
    flujo.seek(0)
    while True:
        datos = flujo.read(bloque)
        if not datos:
            break
        hasher.update(datos)
    flujo.seek(posicion)
    return hasher.hexdigest()


# =============================================================================
# Validación del contenido del reporte
# =============================================================================


def validar_columnas(columnas_detectadas: set[str]) -> ResultadoValidacion:
    """Comprueba que estén las columnas mínimas para poder analizar el reporte."""
    resultado = ResultadoValidacion()

    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in columnas_detectadas]
    if faltantes:
        nombres = ", ".join(f"«{ETIQUETAS_COLUMNAS.get(c, c)}»" for c in faltantes)
        resultado.agregar_error(
            f"Faltan columnas obligatorias: {nombres}. "
            "Usa el asistente de relación de columnas para indicar su equivalente."
        )

    ausentes_recomendadas = [c for c in COLUMNAS_RECOMENDADAS if c not in columnas_detectadas]
    if ausentes_recomendadas:
        nombres = ", ".join(f"«{ETIQUETAS_COLUMNAS.get(c, c)}»" for c in ausentes_recomendadas)
        resultado.agregar_advertencia(
            f"No se encontraron estas columnas recomendadas: {nombres}. "
            "Las métricas que dependen de ellas se mostrarán como N/D."
        )

    resultado.detalle["faltantes_obligatorias"] = faltantes
    resultado.detalle["faltantes_recomendadas"] = ausentes_recomendadas
    return resultado


def construir_llave_duplicados(df: pd.DataFrame) -> pd.Series:
    """Construye la llave compuesta que identifica un registro.

    Se concatenan Id. del pedido, tipo, SKU, fecha, total e Id. de liquidación y se
    aplica SHA-1.  Es vectorizado: no recorre filas.
    """
    columnas = [c for c in LLAVE_DUPLICADOS if c in df.columns]
    if not columnas:
        # Sin columnas de llave, cada fila se considera única por su posición.
        return pd.Series(
            [hashlib.sha1(str(i).encode()).hexdigest() for i in df.index],
            index=df.index,
            dtype="string",
        )

    partes: list[pd.Series] = []
    for columna in columnas:
        serie = df[columna]
        if pd.api.types.is_datetime64_any_dtype(serie):
            texto = serie.dt.strftime("%Y-%m-%d %H:%M:%S")
        elif pd.api.types.is_numeric_dtype(serie):
            texto = serie.round(4).astype("string")
        else:
            texto = serie.astype("string").str.strip().str.upper()
        partes.append(texto.fillna(""))

    concatenado = partes[0]
    for parte in partes[1:]:
        concatenado = concatenado.str.cat(parte, sep="|")

    return concatenado.map(
        lambda v: hashlib.sha1(str(v).encode("utf-8")).hexdigest(), na_action="ignore"
    ).astype("string")


def detectar_duplicados(df: pd.DataFrame) -> tuple[pd.Series, int]:
    """Marca los registros repetidos según la llave compuesta.

    Returns:
        ``(marca_booleana, cantidad)``.  La primera aparición **no** se marca:
        solo las repeticiones posteriores.  Nada se elimina automáticamente.
    """
    if df.empty:
        return pd.Series([], dtype="bool"), 0
    llaves = construir_llave_duplicados(df)
    marca = llaves.duplicated(keep="first").fillna(False)
    return marca.astype(bool), int(marca.sum())


def validar_dataframe(df: pd.DataFrame) -> ResultadoValidacion:
    """Revisiones de integridad sobre el DataFrame ya limpio."""
    from utils.constants import COL_CANTIDAD, COL_FECHA, COL_SKU, COL_TIPO, COL_TOTAL

    resultado = ResultadoValidacion()

    if df.empty:
        resultado.agregar_error("El archivo no contiene registros.")
        return resultado

    if COL_FECHA in df.columns:
        sin_fecha = int(df[COL_FECHA].isna().sum())
        if sin_fecha:
            resultado.agregar_advertencia(
                f"{sin_fecha:,} registros tienen una fecha que no se pudo interpretar."
            )
        resultado.detalle["fechas_invalidas"] = sin_fecha

    if COL_TOTAL in df.columns:
        no_numericos = int(pd.to_numeric(df[COL_TOTAL], errors="coerce").isna().sum())
        if no_numericos:
            resultado.agregar_advertencia(
                f"{no_numericos:,} registros tienen un «total» que no es numérico; se tomaron como cero."
            )
        resultado.detalle["totales_no_numericos"] = no_numericos

    if COL_TIPO in df.columns and COL_SKU in df.columns:
        from utils.constants import TIPO_PEDIDO

        pedidos = df[COL_TIPO] == TIPO_PEDIDO
        sin_sku = int((pedidos & (df[COL_SKU].isna() | df[COL_SKU].eq(""))).sum())
        if sin_sku:
            resultado.agregar_advertencia(f"{sin_sku:,} ventas no tienen SKU asignado.")
        resultado.detalle["ventas_sin_sku"] = sin_sku

        if COL_CANTIDAD in df.columns:
            sin_cantidad = int(
                (pedidos & (df[COL_CANTIDAD].isna() | df[COL_CANTIDAD].eq(0))).sum()
            )
            if sin_cantidad:
                resultado.agregar_advertencia(
                    f"{sin_cantidad:,} pedidos no tienen cantidad; no suman unidades."
                )
            resultado.detalle["pedidos_sin_cantidad"] = sin_cantidad

    return resultado


def validar_rango_fechas(inicio: Any, fin: Any) -> ResultadoValidacion:
    """Comprueba que el rango de fechas sea coherente."""
    resultado = ResultadoValidacion()
    if inicio is None or fin is None:
        resultado.agregar_error("Debes indicar la fecha inicial y la fecha final.")
        return resultado
    try:
        d_inicio = pd.Timestamp(inicio)
        d_fin = pd.Timestamp(fin)
    except (TypeError, ValueError):
        resultado.agregar_error("Las fechas indicadas no son válidas.")
        return resultado
    if d_inicio > d_fin:
        resultado.agregar_error("La fecha inicial no puede ser posterior a la fecha final.")
    if d_fin > pd.Timestamp(datetime.now()) + pd.Timedelta(days=1):
        resultado.agregar_advertencia("La fecha final está en el futuro.")
    return resultado

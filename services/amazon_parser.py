"""Lectura e interpretación de los reportes de Amazon Seller Central.

Responsabilidades:

* Detectar la codificación y el delimitador de un CSV.
* Localizar la fila de encabezados aunque el archivo traiga un preámbulo.
* Traducir los encabezados originales a los nombres canónicos del proyecto,
  tolerando mayúsculas, acentos, espacios y variantes del nombre.
* Leer archivos Excel (``.xlsx`` y ``.xls``).
* Leer CSV muy grandes por bloques.

Este módulo **no** limpia los datos: eso corresponde a ``data_cleaner``.
"""

from __future__ import annotations

import csv
import difflib
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from utils.config import get_settings
from utils.constants import (
    ALIAS_COLUMNAS,
    INDICE_ALIAS,
    normalizar_texto,
)
from utils.logger import get_logger

logger = get_logger("amazon_parser")

#: Codificaciones que se prueban en orden si la detección automática falla.
CODIFICACIONES_CANDIDATAS: tuple[str, ...] = (
    "utf-8-sig",
    "utf-8",
    "cp1252",
    "latin-1",
)

#: Delimitadores que reconoce el lector de CSV.
DELIMITADORES_CANDIDATOS: tuple[str, ...] = (",", ";", "\t", "|")

#: Cuántas filas se inspeccionan al buscar el encabezado real.
MAX_FILAS_PREAMBULO = 20


@dataclass
class ResultadoLectura:
    """Todo lo que se sabe de un archivo después de leerlo."""

    df: pd.DataFrame
    nombre_archivo: str
    encoding: str = ""
    delimitador: str = ""
    fila_encabezado: int = 0
    filas: int = 0
    columnas: int = 0
    mapeo: dict[str, str] = field(default_factory=dict)
    """Encabezado original -> nombre canónico."""
    columnas_sin_reconocer: list[str] = field(default_factory=list)
    columnas_detectadas: set[str] = field(default_factory=set)
    mensajes: list[str] = field(default_factory=list)


# =============================================================================
# Detección de codificación y delimitador
# =============================================================================


def detectar_encoding(contenido: bytes) -> str:
    """Detecta la codificación de un CSV.

    Primero intenta con ``charset_normalizer``; si no está disponible o no da un
    resultado confiable, prueba las codificaciones candidatas en orden.
    """
    if contenido.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    muestra = contenido[:200_000]

    try:
        from charset_normalizer import from_bytes

        resultados = from_bytes(muestra).best()
        if resultados is not None and resultados.encoding:
            detectado = resultados.encoding.lower()
            # ascii es un subconjunto de utf-8: se prefiere el más amplio.
            return "utf-8" if detectado == "ascii" else detectado
    except Exception:  # noqa: BLE001 - la detección es una ayuda, no un requisito
        logger.debug("charset_normalizer no disponible; se usa detección por prueba.")

    for codificacion in CODIFICACIONES_CANDIDATAS:
        try:
            muestra.decode(codificacion)
            return codificacion
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"  # nunca falla: acepta cualquier byte


def detectar_delimitador(texto: str) -> str:
    """Detecta el separador de columnas de un CSV."""
    muestra = "\n".join(texto.splitlines()[:50])
    if not muestra.strip():
        return ","

    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters="".join(DELIMITADORES_CANDIDATOS))
        if dialecto.delimiter in DELIMITADORES_CANDIDATOS:
            return dialecto.delimiter
    except csv.Error:
        logger.debug("csv.Sniffer no identificó el delimitador; se usa conteo por frecuencia.")

    # Respaldo: el delimitador que produce el mismo número de campos en más líneas.
    mejor, mejor_puntaje = ",", -1
    for candidato in DELIMITADORES_CANDIDATOS:
        try:
            filas = list(csv.reader(io.StringIO(muestra), delimiter=candidato))
        except csv.Error:
            continue
        filas = [f for f in filas if f]
        if len(filas) < 2:
            continue
        anchos = [len(f) for f in filas]
        ancho_moda = max(set(anchos), key=anchos.count)
        if ancho_moda < 2:
            continue
        puntaje = anchos.count(ancho_moda) * ancho_moda
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = candidato, puntaje
    return mejor


def detectar_fila_encabezado(filas: list[list[str]]) -> int:
    """Devuelve el índice de la fila que contiene los encabezados reales.

    Amazon a veces antepone líneas de resumen antes de la tabla.  Se elige la
    fila que reconoce más nombres de columna conocidos.
    """
    mejor_indice, mejor_aciertos = 0, -1
    for indice, fila in enumerate(filas[:MAX_FILAS_PREAMBULO]):
        if not fila:
            continue
        aciertos = sum(1 for celda in fila if normalizar_texto(celda) in INDICE_ALIAS)
        # Empate: gana la fila más temprana; se requiere mejora estricta.
        if aciertos > mejor_aciertos:
            mejor_indice, mejor_aciertos = indice, aciertos
    return mejor_indice if mejor_aciertos >= 3 else 0


# =============================================================================
# Traducción de encabezados
# =============================================================================


def mapear_columnas(
    encabezados: list[str], umbral_similitud: float = 0.86
) -> tuple[dict[str, str], list[str]]:
    """Traduce los encabezados del archivo a los nombres canónicos.

    Estrategia en tres niveles:

    1. Coincidencia exacta del texto normalizado contra el índice de alias.
    2. Coincidencia por inclusión (``"total (mxn)"`` contiene ``"total"``),
       eligiendo siempre el alias más largo para no confundir ``"estado"`` con
       ``"estado de la transaccion"``.
    3. Coincidencia aproximada con ``difflib`` para erratas menores.

    Returns:
        ``(mapeo, sin_reconocer)`` donde ``mapeo`` va del encabezado original al
        nombre canónico.  Si dos encabezados apuntan a la misma columna canónica,
        solo se conserva el primero.
    """
    mapeo: dict[str, str] = {}
    sin_reconocer: list[str] = []
    ya_asignadas: set[str] = set()

    # Alias ordenados de más largo a más corto: la especificidad manda.
    alias_ordenados = sorted(INDICE_ALIAS.keys(), key=len, reverse=True)

    for original in encabezados:
        normalizado = normalizar_texto(original)
        if not normalizado:
            sin_reconocer.append(original)
            continue

        canonica: str | None = None

        # Nivel 1: coincidencia exacta.
        canonica = INDICE_ALIAS.get(normalizado)

        # Nivel 2: el encabezado contiene un alias conocido (o al revés).
        if canonica is None:
            for alias in alias_ordenados:
                if alias == normalizado or normalizado.startswith(alias + " ") or (
                    f" {alias} " in f" {normalizado} "
                ):
                    canonica = INDICE_ALIAS[alias]
                    break

        # Nivel 3: similitud aproximada (erratas de captura).
        if canonica is None:
            parecidos = difflib.get_close_matches(
                normalizado, alias_ordenados, n=1, cutoff=umbral_similitud
            )
            if parecidos:
                canonica = INDICE_ALIAS[parecidos[0]]

        if canonica is None or canonica in ya_asignadas:
            sin_reconocer.append(original)
            continue

        mapeo[original] = canonica
        ya_asignadas.add(canonica)

    return mapeo, sin_reconocer


def sugerir_columna(encabezado: str, n: int = 3) -> list[str]:
    """Devuelve las columnas canónicas más parecidas a un encabezado.

    Se usa en el asistente manual de relación de columnas.
    """
    normalizado = normalizar_texto(encabezado)
    puntajes: list[tuple[float, str]] = []
    for canonica, alias in ALIAS_COLUMNAS.items():
        mejor = max(
            difflib.SequenceMatcher(None, normalizado, a).ratio() for a in alias
        )
        puntajes.append((mejor, canonica))
    puntajes.sort(reverse=True)
    return [canonica for _, canonica in puntajes[:n]]


# =============================================================================
# Lectura de archivos
# =============================================================================


def _leer_csv(contenido: bytes, nombre: str) -> ResultadoLectura:
    """Lee un CSV detectando codificación, delimitador y fila de encabezado."""
    encoding = detectar_encoding(contenido)

    try:
        texto = contenido.decode(encoding, errors="replace")
    except LookupError:
        encoding = "latin-1"
        texto = contenido.decode(encoding, errors="replace")

    delimitador = detectar_delimitador(texto)

    # Inspecciona las primeras filas para localizar el encabezado real.
    primeras = list(csv.reader(io.StringIO(texto[:200_000]), delimiter=delimitador))
    fila_encabezado = detectar_fila_encabezado(primeras)

    df = pd.read_csv(
        io.StringIO(texto),
        sep=delimitador,
        skiprows=fila_encabezado,
        dtype=str,            # todo entra como texto; el limpiador convierte después
        keep_default_na=False,  # conserva "" en lugar de NaN para no perder ceros a la izquierda
        na_values=[""],
        engine="python",      # tolera comillas y líneas irregulares
        on_bad_lines="warn",
    )

    return ResultadoLectura(
        df=df,
        nombre_archivo=nombre,
        encoding=encoding,
        delimitador=delimitador,
        fila_encabezado=fila_encabezado,
    )


def _leer_excel(contenido: bytes, nombre: str, hoja: int | str = 0) -> ResultadoLectura:
    """Lee un archivo Excel eligiendo el motor según la extensión."""
    extension = Path(nombre).suffix.lower()
    motor = "xlrd" if extension == ".xls" else "openpyxl"

    # Primera pasada sin encabezado para localizar la fila correcta.
    previa = pd.read_excel(
        io.BytesIO(contenido), sheet_name=hoja, header=None, nrows=MAX_FILAS_PREAMBULO,
        dtype=str, engine=motor,
    )
    filas = [[("" if pd.isna(c) else str(c)) for c in fila] for fila in previa.values.tolist()]
    fila_encabezado = detectar_fila_encabezado(filas)

    df = pd.read_excel(
        io.BytesIO(contenido),
        sheet_name=hoja,
        header=fila_encabezado,
        dtype=str,
        engine=motor,
    )

    return ResultadoLectura(
        df=df,
        nombre_archivo=nombre,
        encoding="binario",
        delimitador="",
        fila_encabezado=fila_encabezado,
    )


def leer_archivo(
    contenido: bytes,
    nombre: str,
    mapeo_manual: dict[str, str] | None = None,
) -> ResultadoLectura:
    """Lee un reporte de Amazon (CSV o Excel) y normaliza sus encabezados.

    Args:
        contenido: bytes del archivo.
        nombre: nombre original (define el formato por su extensión).
        mapeo_manual: relación adicional ``encabezado original -> columna canónica``
            capturada por el usuario cuando la detección automática no basta.

    Returns:
        :class:`ResultadoLectura` con el DataFrame ya renombrado.

    Raises:
        ValueError: si la extensión no es compatible o el archivo está vacío.
    """
    extension = Path(nombre).suffix.lower()

    if not contenido:
        raise ValueError(f"«{nombre}» está vacío.")

    if extension == ".csv":
        resultado = _leer_csv(contenido, nombre)
    elif extension in {".xlsx", ".xlsm", ".xls"}:
        resultado = _leer_excel(contenido, nombre)
    else:
        raise ValueError(
            f"«{nombre}»: formato no compatible. Usa archivos .csv, .xlsx o .xls."
        )

    if resultado.df.empty:
        resultado.mensajes.append(f"«{nombre}» no contiene filas de datos.")

    # Limpia encabezados fantasma ("Unnamed: 12") y espacios sobrantes.
    resultado.df.columns = [
        "" if str(c).startswith("Unnamed:") else str(c).strip()
        for c in resultado.df.columns
    ]
    resultado.df = resultado.df.loc[:, [c != "" for c in resultado.df.columns]]

    mapeo, sin_reconocer = mapear_columnas(list(resultado.df.columns))

    # El mapeo manual del usuario tiene prioridad sobre la detección automática.
    if mapeo_manual:
        for original, canonica in mapeo_manual.items():
            if original in resultado.df.columns and canonica:
                # Libera la columna canónica si otra la tenía asignada.
                for k, v in list(mapeo.items()):
                    if v == canonica and k != original:
                        del mapeo[k]
                        sin_reconocer.append(k)
                mapeo[original] = canonica
                if original in sin_reconocer:
                    sin_reconocer.remove(original)

    resultado.df = resultado.df.rename(columns=mapeo)
    resultado.mapeo = mapeo
    resultado.columnas_sin_reconocer = sin_reconocer
    resultado.columnas_detectadas = set(mapeo.values())
    resultado.filas = len(resultado.df)
    resultado.columnas = len(resultado.df.columns)

    logger.info(
        "Archivo leído: %s | filas=%d | columnas=%d | encoding=%s | sep=%r | encabezado en fila %d",
        nombre, resultado.filas, resultado.columnas, resultado.encoding,
        resultado.delimitador, resultado.fila_encabezado,
    )
    if sin_reconocer:
        logger.info("Columnas no reconocidas en %s: %s", nombre, sin_reconocer)

    return resultado


def leer_csv_por_bloques(
    ruta: str | Path, tamano_bloque: int | None = None
) -> pd.DataFrame:
    """Lee un CSV muy grande en bloques y devuelve el DataFrame concatenado.

    Reduce el pico de memoria frente a cargar el archivo completo de una vez.
    """
    settings = get_settings()
    tamano = tamano_bloque or settings.csv_chunk_size
    ruta = Path(ruta)

    with ruta.open("rb") as flujo:
        cabecera = flujo.read(200_000)
    encoding = detectar_encoding(cabecera)
    delimitador = detectar_delimitador(cabecera.decode(encoding, errors="replace"))

    bloques: list[pd.DataFrame] = []
    lector = pd.read_csv(
        ruta,
        sep=delimitador,
        encoding=encoding,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        chunksize=tamano,
        engine="c",
        on_bad_lines="skip",
    )
    for bloque in lector:
        bloques.append(bloque)

    if not bloques:
        return pd.DataFrame()

    df = pd.concat(bloques, ignore_index=True)
    mapeo, _ = mapear_columnas(list(df.columns))
    return df.rename(columns=mapeo)


def leer_flujo(flujo: BinaryIO, nombre: str, mapeo_manual: dict[str, str] | None = None) -> ResultadoLectura:
    """Envoltura de :func:`leer_archivo` para objetos tipo archivo de Streamlit."""
    flujo.seek(0)
    contenido = flujo.read()
    flujo.seek(0)
    return leer_archivo(contenido, nombre, mapeo_manual=mapeo_manual)

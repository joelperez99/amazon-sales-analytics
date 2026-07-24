"""Conversión de las fechas en español que emite Amazon Seller Central.

Amazon México entrega la fecha con este formato::

    1 jun 2026 12:41:59 a.m. GMT-7

Es decir: día sin cero a la izquierda, mes abreviado en español, año, hora en
formato de 12 horas con ``a.m.``/``p.m.`` y un desplazamiento ``GMT±H``.

La conversión es **vectorizada**: se extraen los componentes con una expresión
regular sobre toda la columna y se arma una cadena ISO que pandas convierte de
una sola vez.  Nunca se recorre el DataFrame fila por fila.

Criterio de zona horaria: se conserva la *hora local* tal como aparece en el
reporte y se descarta el desplazamiento.  Es lo que espera el vendedor cuando
agrupa "ventas del 1 de junio".  El desplazamiento se puede recuperar aparte con
:func:`extraer_offset`.
"""

from __future__ import annotations

import re

import pandas as pd

#: Mes abreviado o completo (sin acentos, en minúsculas) -> número de mes.
MESES_ES: dict[str, int] = {
    "ene": 1, "enero": 1,
    "feb": 2, "febrero": 2,
    "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6,
    "jul": 7, "julio": 7,
    "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "setiembre": 9,
    "oct": 10, "octubre": 10,
    "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12,
    # Abreviaturas en inglés, por si el reporte se exporta con el idioma cambiado.
    "jan": 1, "apr": 4, "aug": 8, "dec": 12,
}

#: ``1 jun 2026 12:41:59 a.m. GMT-7`` -> día, mes, año, hora, minuto, segundo, meridiano
_PATRON_ES = re.compile(
    r"^\s*(?P<dia>\d{1,2})\s+"
    r"(?P<mes>[a-zA-ZáéíóúÁÉÍÓÚ]+)\.?\s+"
    r"(?P<anio>\d{4})"
    r"(?:\s+(?P<hora>\d{1,2}):(?P<minuto>\d{2})(?::(?P<segundo>\d{2}))?)?"
    r"(?:\s*(?P<meridiano>[ap])\s*\.?\s*m\s*\.?)?"
    r"(?:\s*(?P<zona>GMT|UTC)\s*(?P<offset>[+-]\s*\d{1,2}(?::?\d{2})?))?"
    r"\s*$",
    re.IGNORECASE,
)

#: Desplazamiento horario al final de la cadena.
_PATRON_OFFSET = re.compile(r"(?:GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", re.IGNORECASE)

#: Fecha en formato ISO (``2026-06-01``): el año va primero, no el día.
_PATRON_ISO = re.compile(r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def _normalizar_mes(texto: object) -> int | None:
    """Convierte el nombre del mes (con o sin acento) en su número.

    Acepta ``None`` y ``pd.NA``: las filas donde la expresión regular no encontró
    un mes llegan aquí como valor ausente.
    """
    if texto is None or texto is pd.NA:
        return None
    try:
        if pd.isna(texto):
            return None
    except (TypeError, ValueError):
        pass
    texto = str(texto)
    if not texto:
        return None
    limpio = (
        texto.lower()
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u")
        .strip(" .")
    )
    return MESES_ES.get(limpio)


def parsear_fecha_es(texto: object) -> pd.Timestamp | pd.NaT:  # type: ignore[valid-type]
    """Convierte **una** fecha en español a ``Timestamp`` (hora local, sin zona).

    Se usa en pruebas y en casos aislados; para columnas completas usa
    :func:`parsear_serie_fechas`, que es varios órdenes de magnitud más rápida.
    """
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return pd.NaT
    if isinstance(texto, pd.Timestamp):
        return texto.tz_localize(None) if texto.tzinfo else texto
    cadena = str(texto).strip()
    if not cadena:
        return pd.NaT

    coincidencia = _PATRON_ES.match(cadena)
    if coincidencia:
        mes = _normalizar_mes(coincidencia.group("mes") or "")
        if mes is not None:
            hora = int(coincidencia.group("hora") or 0)
            minuto = int(coincidencia.group("minuto") or 0)
            segundo = int(coincidencia.group("segundo") or 0)
            meridiano = (coincidencia.group("meridiano") or "").lower()
            hora = _ajustar_hora_12(hora, meridiano)
            try:
                return pd.Timestamp(
                    year=int(coincidencia.group("anio")),
                    month=mes,
                    day=int(coincidencia.group("dia")),
                    hour=hora,
                    minute=minuto,
                    second=segundo,
                )
            except ValueError:
                return pd.NaT

    # Último recurso: el analizador genérico de pandas.  Se usa «día primero»
    # (convención de México: 05/06/2026 es 5 de junio) salvo cuando la cadena
    # empieza con un año de cuatro dígitos, que es formato ISO y va al revés.
    convertido = pd.to_datetime(
        cadena, errors="coerce", dayfirst=not _PATRON_ISO.match(cadena)
    )
    if isinstance(convertido, pd.Timestamp) and convertido.tzinfo is not None:
        convertido = convertido.tz_localize(None)
    return convertido


def _ajustar_hora_12(hora: int, meridiano: str) -> int:
    """Convierte una hora de 12 h a 24 h. ``12 a.m.`` es 0 y ``12 p.m.`` es 12."""
    if not meridiano:
        return hora
    if meridiano == "a":
        return 0 if hora == 12 else hora
    return hora if hora == 12 else hora + 12


def parsear_serie_fechas(serie: pd.Series) -> pd.Series:
    """Convierte una columna completa de fechas en español a ``datetime64[ns]``.

    Estrategia en tres pasos, toda vectorizada:

    1. Se extraen los componentes con la expresión regular en español.
    2. Con las filas que coincidieron se arma una cadena ``YYYY-MM-DD HH:MM:SS``
       y se convierte con un formato explícito (ruta rápida de pandas).
    3. Las filas que no coincidieron pasan por ``pd.to_datetime`` genérico.
    """
    if serie.empty:
        return pd.Series([], dtype="datetime64[ns]")

    # Si ya es de tipo fecha, solo se quita la zona horaria.
    if pd.api.types.is_datetime64_any_dtype(serie):
        if getattr(serie.dtype, "tz", None) is not None:
            return serie.dt.tz_localize(None)
        return serie

    texto = serie.astype("string").str.strip()
    resultado = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")

    partes = texto.str.extract(_PATRON_ES)
    if not partes.empty and "mes" in partes.columns:
        # ``astype(object)`` evita que ``pd.NA`` llegue a la función de mapeo como
        # un valor cuya conversión a booleano es ambigua.
        mes_num = partes["mes"].astype(object).map(_normalizar_mes)
        valido = mes_num.notna() & partes["dia"].notna() & partes["anio"].notna()

        if valido.any():
            hora = pd.to_numeric(partes.loc[valido, "hora"], errors="coerce").fillna(0).astype("int64")
            minuto = pd.to_numeric(partes.loc[valido, "minuto"], errors="coerce").fillna(0).astype("int64")
            segundo = pd.to_numeric(partes.loc[valido, "segundo"], errors="coerce").fillna(0).astype("int64")
            meridiano = partes.loc[valido, "meridiano"].fillna("").str.lower()

            # Ajuste de 12 h a 24 h, vectorizado.
            es_pm = meridiano.eq("p")
            es_am = meridiano.eq("a")
            hora = hora.where(~(es_am & hora.eq(12)), 0)
            hora = hora.where(~(es_pm & hora.ne(12)), hora + 12)

            armado = (
                partes.loc[valido, "anio"].astype(str).str.zfill(4)
                + "-"
                + mes_num[valido].astype("int64").astype(str).str.zfill(2)
                + "-"
                + partes.loc[valido, "dia"].astype(str).str.zfill(2)
                + " "
                + hora.astype(str).str.zfill(2)
                + ":"
                + minuto.astype(str).str.zfill(2)
                + ":"
                + segundo.astype(str).str.zfill(2)
            )
            resultado.loc[valido] = pd.to_datetime(
                armado, format="%Y-%m-%d %H:%M:%S", errors="coerce"
            )

    # Filas que la expresión regular no pudo interpretar: se convierten con el
    # analizador genérico de pandas, separando las fechas ISO (año primero) de
    # las del formato mexicano (día primero).
    pendientes = resultado.isna() & texto.notna() & texto.ne("")
    if pendientes.any():
        restantes = texto[pendientes]
        es_iso = restantes.str.match(_PATRON_ISO).fillna(False)
        for mascara, dia_primero in ((es_iso, False), (~es_iso, True)):
            if not mascara.any():
                continue
            alterno = pd.to_datetime(
                restantes[mascara], errors="coerce",
                dayfirst=dia_primero, format="mixed",
            )
            if getattr(alterno.dtype, "tz", None) is not None:
                alterno = alterno.dt.tz_localize(None)
            resultado.loc[alterno.index] = alterno

    return resultado


def extraer_offset(serie: pd.Series) -> pd.Series:
    """Devuelve el desplazamiento horario en horas (por ejemplo ``-7.0``)."""
    texto = serie.astype("string")
    partes = texto.str.extract(_PATRON_OFFSET)
    if partes.empty:
        return pd.Series([pd.NA] * len(serie), index=serie.index, dtype="Float64")
    signo = partes[0].map({"+": 1.0, "-": -1.0})
    horas = pd.to_numeric(partes[1], errors="coerce")
    minutos = pd.to_numeric(partes[2], errors="coerce").fillna(0)
    return (signo * (horas + minutos / 60)).astype("Float64")


def enriquecer_columnas_fecha(df: pd.DataFrame, columna: str) -> pd.DataFrame:
    """Agrega las columnas derivadas de una fecha: día, año, mes, semana, hora.

    Modifica y devuelve el mismo DataFrame (operación en sitio para no duplicar
    memoria en archivos grandes).
    """
    from utils.constants import (
        COL_ANIO, COL_DIA_SEMANA, COL_FECHA_DIA, COL_HORA, COL_MES,
        COL_MES_NOMBRE, COL_SEMANA, DIAS_ES, MESES_ES as NOMBRES_MESES,
    )

    if columna not in df.columns:
        return df

    fechas = df[columna]
    if not pd.api.types.is_datetime64_any_dtype(fechas):
        fechas = parsear_serie_fechas(fechas)
        df[columna] = fechas

    df[COL_FECHA_DIA] = fechas.dt.date
    df[COL_ANIO] = fechas.dt.year.astype("Int64")
    df[COL_MES] = fechas.dt.month.astype("Int64")
    df[COL_MES_NOMBRE] = fechas.dt.month.map(NOMBRES_MESES).astype("string")
    df[COL_SEMANA] = fechas.dt.isocalendar().week.astype("Int64")
    df[COL_DIA_SEMANA] = fechas.dt.dayofweek.map(DIAS_ES).astype("string")
    df[COL_HORA] = fechas.dt.hour.astype("Int64")
    return df

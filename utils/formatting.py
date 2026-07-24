"""Formato de números, moneda y porcentajes con convención de México.

Regla general: **se redondea únicamente para presentar**.  Los cálculos internos
siempre trabajan con la precisión completa de ``float64``.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from utils.constants import COLOR_CRITICO, COLOR_EXITO_TEXTO, COLOR_TINTA_TENUE

#: Texto que se muestra cuando una métrica no puede calcularse.
NO_DISPONIBLE = "N/D"


# =============================================================================
# Utilidades numéricas seguras
# =============================================================================


def es_nulo(valor: Any) -> bool:
    """``True`` si el valor es ``None``, ``NaN``, ``NaT`` o cadena vacía."""
    if valor is None:
        return True
    if isinstance(valor, str):
        return valor.strip() == ""
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def division_segura(
    numerador: float | int | None,
    denominador: float | int | None,
    defecto: float | None = None,
) -> float | None:
    """Divide evitando la división entre cero.

    Devuelve ``defecto`` (``None`` por omisión) cuando el denominador es cero,
    nulo o no numérico.  Nunca lanza excepción.
    """
    if es_nulo(numerador) or es_nulo(denominador):
        return defecto
    try:
        num = float(numerador)  # type: ignore[arg-type]
        den = float(denominador)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defecto
    if den == 0 or math.isnan(den) or math.isnan(num):
        return defecto
    resultado = num / den
    if math.isnan(resultado) or math.isinf(resultado):
        return defecto
    return resultado


def division_segura_serie(
    numerador: pd.Series, denominador: pd.Series, defecto: float = 0.0
) -> pd.Series:
    """Versión vectorizada de :func:`division_segura` para columnas completas."""
    num = pd.to_numeric(numerador, errors="coerce").astype("float64")
    den = pd.to_numeric(denominador, errors="coerce").astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        resultado = np.where(
            (den == 0) | np.isnan(den) | np.isnan(num), defecto, num / den
        )
    return pd.Series(resultado, index=num.index, dtype="float64")


# =============================================================================
# Formato de presentación
# =============================================================================


def formato_moneda(valor: Any, decimales: int = 2, con_divisa: bool = True) -> str:
    """Formatea un importe con la convención mexicana: ``$1,234.56 MXN``."""
    if es_nulo(valor):
        return NO_DISPONIBLE
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return NO_DISPONIBLE
    if math.isnan(numero) or math.isinf(numero):
        return NO_DISPONIBLE
    signo = "-" if numero < 0 else ""
    texto = f"{abs(numero):,.{decimales}f}"
    sufijo = " MXN" if con_divisa else ""
    return f"{signo}${texto}{sufijo}"


def formato_moneda_compacta(valor: Any) -> str:
    """Formato abreviado para tarjetas: ``$1.2M MXN``, ``$34.5k MXN``."""
    if es_nulo(valor):
        return NO_DISPONIBLE
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return NO_DISPONIBLE
    signo = "-" if numero < 0 else ""
    absoluto = abs(numero)
    if absoluto >= 1_000_000:
        return f"{signo}${absoluto / 1_000_000:,.2f}M MXN"
    if absoluto >= 10_000:
        return f"{signo}${absoluto / 1_000:,.1f}k MXN"
    return f"{signo}${absoluto:,.2f} MXN"


def formato_entero(valor: Any) -> str:
    """Formatea un entero con separador de miles."""
    if es_nulo(valor):
        return NO_DISPONIBLE
    try:
        return f"{int(round(float(valor))):,}"
    except (TypeError, ValueError):
        return NO_DISPONIBLE


def formato_decimal(valor: Any, decimales: int = 2) -> str:
    """Formatea un número con separador de miles y decimales fijos."""
    if es_nulo(valor):
        return NO_DISPONIBLE
    try:
        return f"{float(valor):,.{decimales}f}"
    except (TypeError, ValueError):
        return NO_DISPONIBLE


def formato_porcentaje(valor: Any, decimales: int = 1, ya_en_porcentaje: bool = False) -> str:
    """Formatea una proporción como porcentaje.

    Args:
        valor: proporción (0.184) o porcentaje (18.4) según ``ya_en_porcentaje``.
        ya_en_porcentaje: ``True`` si el valor ya viene multiplicado por 100.
    """
    if es_nulo(valor):
        return NO_DISPONIBLE
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return NO_DISPONIBLE
    if math.isnan(numero) or math.isinf(numero):
        return NO_DISPONIBLE
    if not ya_en_porcentaje:
        numero *= 100
    return f"{numero:,.{decimales}f}%"


def formato_fecha(valor: Any, con_hora: bool = False) -> str:
    """Formatea una fecha como ``dd/mm/aaaa`` (opcionalmente con hora)."""
    if es_nulo(valor):
        return NO_DISPONIBLE
    if isinstance(valor, str):
        convertido = pd.to_datetime(valor, errors="coerce")
        if pd.isna(convertido):
            return valor
        valor = convertido
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.strftime("%d/%m/%Y %H:%M" if con_hora else "%d/%m/%Y")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def formato_rango_fechas(inicio: Any, fin: Any) -> str:
    """Devuelve ``01/06/2026 – 30/06/2026``."""
    return f"{formato_fecha(inicio)} – {formato_fecha(fin)}"


# =============================================================================
# Variaciones entre periodos
# =============================================================================


def variacion_absoluta(actual: Any, anterior: Any) -> float | None:
    """Diferencia ``actual − anterior``; ``None`` si alguno no es numérico."""
    if es_nulo(actual) or es_nulo(anterior):
        return None
    try:
        return float(actual) - float(anterior)
    except (TypeError, ValueError):
        return None


def variacion_porcentual(actual: Any, anterior: Any) -> float | None:
    """Variación porcentual respecto al periodo anterior.

    Devuelve ``None`` (que la interfaz muestra como «N/D») cuando el periodo
    anterior es cero o nulo: dividir entre cero produciría un porcentaje inválido.
    """
    if es_nulo(actual) or es_nulo(anterior):
        return None
    try:
        base = float(anterior)
        nuevo = float(actual)
    except (TypeError, ValueError):
        return None
    if base == 0:
        return None
    resultado = (nuevo - base) / abs(base)
    if math.isnan(resultado) or math.isinf(resultado):
        return None
    return resultado


def texto_variacion(
    actual: Any,
    anterior: Any,
    tipo: str = "moneda",
    mayor_es_mejor: bool = True,
) -> tuple[str, str, str]:
    """Construye el texto de variación de una tarjeta.

    Returns:
        Tupla ``(texto, color, icono)`` lista para pintarse en HTML.
    """
    delta = variacion_absoluta(actual, anterior)
    pct = variacion_porcentual(actual, anterior)

    if delta is None:
        return (f"Sin comparación ({NO_DISPONIBLE})", COLOR_TINTA_TENUE, "•")

    if tipo == "moneda":
        texto_delta = formato_moneda(delta, con_divisa=False)
    elif tipo == "entero":
        texto_delta = f"{'+' if delta >= 0 else '-'}{formato_entero(abs(delta))}"
    elif tipo == "porcentaje":
        texto_delta = f"{'+' if delta >= 0 else ''}{formato_porcentaje(delta)}"
    else:
        texto_delta = formato_decimal(delta)

    texto_pct = formato_porcentaje(pct) if pct is not None else NO_DISPONIBLE

    if delta > 0:
        icono = "▲"
        color = COLOR_EXITO_TEXTO if mayor_es_mejor else COLOR_CRITICO
    elif delta < 0:
        icono = "▼"
        color = COLOR_CRITICO if mayor_es_mejor else COLOR_EXITO_TEXTO
    else:
        icono = "="
        color = COLOR_TINTA_TENUE

    return (f"{texto_delta} ({texto_pct})", color, icono)


# =============================================================================
# Ayudas para tablas
# =============================================================================


def renombrar_a_etiquetas(df: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    """Renombra las columnas presentes usando el mapa dado (ignora las ausentes)."""
    return df.rename(columns={c: mapa[c] for c in df.columns if c in mapa})


def truncar(texto: Any, largo: int = 60) -> str:
    """Recorta un texto largo agregando puntos suspensivos."""
    if es_nulo(texto):
        return ""
    cadena = str(texto)
    return cadena if len(cadena) <= largo else cadena[: largo - 1] + "…"

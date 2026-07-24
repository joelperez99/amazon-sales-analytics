"""Tarjetas de indicadores.

Cada tarjeta muestra el valor del periodo, la variación absoluta y porcentual
frente al periodo anterior, un indicador visual de dirección y un tooltip con la
fórmula empleada.

Cuando el periodo anterior vale cero la variación porcentual se muestra como
«N/D»: un porcentaje sobre base cero no aporta información.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

import streamlit as st

from services.comparison_service import Comparacion
from utils.constants import (
    COLOR_CRITICO,
    COLOR_EJE,
    COLOR_EXITO_TEXTO,
    COLOR_SUPERFICIE,
    COLOR_TINTA,
    COLOR_TINTA_SECUNDARIA,
    COLOR_TINTA_TENUE,
    DICCIONARIO_METRICAS,
    FUENTE_UI,
)
from utils.formatting import (
    NO_DISPONIBLE,
    formato_entero,
    formato_moneda,
    formato_porcentaje,
    formato_decimal,
)

TipoFormato = Literal["moneda", "entero", "porcentaje", "decimal"]

_FORMATEADORES: dict[str, Callable[[Any], str]] = {
    "moneda": formato_moneda,
    "entero": formato_entero,
    "porcentaje": formato_porcentaje,
    "decimal": formato_decimal,
}


def inyectar_estilos() -> None:
    """Inyecta el CSS de las tarjetas.  Se llama una vez por página."""
    if st.session_state.get("_estilos_tarjetas"):
        return
    st.session_state["_estilos_tarjetas"] = True

    st.markdown(
        f"""
        <style>
        .tarjeta-kpi {{
            background: {COLOR_SUPERFICIE};
            border: 1px solid rgba(11,11,11,0.10);
            border-radius: 12px;
            padding: 16px 18px 14px 18px;
            height: 100%;
            display: flex;
            flex-direction: column;
            gap: 6px;
            transition: border-color .15s ease, box-shadow .15s ease;
        }}
        .tarjeta-kpi:hover {{
            border-color: {COLOR_EJE};
            box-shadow: 0 1px 6px rgba(11,11,11,0.06);
        }}
        .tarjeta-kpi .etiqueta {{
            font-family: {FUENTE_UI};
            font-size: 12.5px;
            font-weight: 500;
            color: {COLOR_TINTA_SECUNDARIA};
            letter-spacing: .01em;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .tarjeta-kpi .valor {{
            font-family: {FUENTE_UI};
            font-size: 26px;
            font-weight: 600;
            line-height: 1.15;
            color: {COLOR_TINTA};
        }}
        .tarjeta-kpi .delta {{
            font-family: {FUENTE_UI};
            font-size: 12.5px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .tarjeta-kpi .nota {{
            font-family: {FUENTE_UI};
            font-size: 11.5px;
            color: {COLOR_TINTA_TENUE};
        }}
        .tarjeta-kpi .ayuda {{
            font-size: 11px;
            color: {COLOR_TINTA_TENUE};
            border: 1px solid {COLOR_EJE};
            border-radius: 50%;
            width: 15px; height: 15px;
            display: inline-flex;
            align-items: center; justify-content: center;
            cursor: help;
            flex-shrink: 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def tarjeta(
    clave: str,
    valor: Any,
    comparacion: Comparacion | None = None,
    formato: TipoFormato = "moneda",
    etiqueta: str = "",
    nota: str = "",
    mayor_es_mejor: bool | None = None,
) -> None:
    """Pinta una tarjeta de indicador.

    Args:
        clave: identificador de la métrica en ``DICCIONARIO_METRICAS``.
        valor: valor del periodo actual.
        comparacion: resultado de la comparación entre periodos (opcional).
        formato: cómo se presenta el número.
        etiqueta: título de la tarjeta (si se omite, se toma del diccionario).
        nota: texto auxiliar bajo el valor.
        mayor_es_mejor: si crecer es bueno.  Por omisión lo determina el
            diccionario de comparación.
    """
    inyectar_estilos()

    info = DICCIONARIO_METRICAS.get(clave, {})
    titulo = etiqueta or info.get("nombre", clave)
    formula = info.get("formula", "")
    descripcion = info.get("descripcion", "")
    tooltip = f"{formula}. {descripcion}".strip(". ") if formula else descripcion

    formateador = _FORMATEADORES.get(formato, formato_moneda)
    valor_texto = formateador(valor)

    bloque_delta = ""
    if comparacion is not None and comparacion.hay_comparacion:
        detalle = comparacion.diferencias.get(clave, {})
        delta = detalle.get("absoluta")
        pct = detalle.get("porcentual")
        positivo_es_bueno = (
            mayor_es_mejor if mayor_es_mejor is not None else detalle.get("mayor_es_mejor", True)
        )

        if delta is None:
            bloque_delta = (
                f'<div class="delta" style="color:{COLOR_TINTA_TENUE}">'
                f"• Sin comparación</div>"
            )
        else:
            if delta > 0:
                icono, color = "▲", (COLOR_EXITO_TEXTO if positivo_es_bueno else COLOR_CRITICO)
            elif delta < 0:
                icono, color = "▼", (COLOR_CRITICO if positivo_es_bueno else COLOR_EXITO_TEXTO)
            else:
                icono, color = "=", COLOR_TINTA_TENUE

            delta_texto = formateador(abs(delta))
            signo = "+" if delta > 0 else ("−" if delta < 0 else "")
            pct_texto = formato_porcentaje(pct) if pct is not None else NO_DISPONIBLE
            bloque_delta = (
                f'<div class="delta" style="color:{color}">'
                f"<span>{icono}</span><span>{signo}{delta_texto}</span>"
                f'<span style="color:{COLOR_TINTA_TENUE}">({pct_texto})</span></div>'
            )
    elif comparacion is not None:
        bloque_delta = (
            f'<div class="delta" style="color:{COLOR_TINTA_TENUE}">'
            f"• Sin periodo de comparación</div>"
        )

    bloque_nota = f'<div class="nota">{nota}</div>' if nota else ""
    ayuda = (
        f'<span class="ayuda" title="{_escapar(tooltip)}">?</span>' if tooltip else ""
    )

    st.markdown(
        f"""
        <div class="tarjeta-kpi">
            <div class="etiqueta">{_escapar(titulo)}{ayuda}</div>
            <div class="valor">{valor_texto}</div>
            {bloque_delta}
            {bloque_nota}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _escapar(texto: str) -> str:
    """Escapa el texto que se inyecta en HTML."""
    return (
        str(texto)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


#: Definición de la fila principal de tarjetas del resumen ejecutivo.
TARJETAS_PRINCIPALES: list[tuple[str, TipoFormato]] = [
    ("ventas_brutas", "moneda"),
    ("pedidos_unicos", "entero"),
    ("unidades", "entero"),
    ("ticket_promedio", "moneda"),
    ("tarifas_venta", "moneda"),
    ("tarifas_fba", "moneda"),
    ("total_cargos", "moneda"),
    ("importe_reembolsado", "moneda"),
    ("neto", "moneda"),
    ("margen_neto", "porcentaje"),
]


def fila_tarjetas(
    metricas: dict[str, Any],
    claves: list[tuple[str, TipoFormato]],
    comparacion: Comparacion | None = None,
    columnas: int = 5,
) -> None:
    """Pinta una rejilla de tarjetas repartidas en varias columnas."""
    inyectar_estilos()
    for inicio in range(0, len(claves), columnas):
        bloque = claves[inicio: inicio + columnas]
        cols = st.columns(len(bloque), gap="small")
        for col, (clave, formato) in zip(cols, bloque):
            with col:
                tarjeta(clave, metricas.get(clave), comparacion, formato)


def tarjetas_principales(
    metricas: dict[str, Any], comparacion: Comparacion | None = None
) -> None:
    """Las diez tarjetas del tablero principal, en dos filas de cinco."""
    fila_tarjetas(metricas, TARJETAS_PRINCIPALES, comparacion, columnas=5)


def cifra_destacada(titulo: str, valor: str, contexto: str = "") -> None:
    """Número protagonista para la página de inicio."""
    inyectar_estilos()
    st.markdown(
        f"""
        <div class="tarjeta-kpi" style="padding:22px 24px;">
            <div class="etiqueta">{_escapar(titulo)}</div>
            <div class="valor" style="font-size:38px;">{valor}</div>
            {f'<div class="nota">{_escapar(contexto)}</div>' if contexto else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )

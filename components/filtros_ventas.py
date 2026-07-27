"""Barra de filtros tipo «slicer» de la página de Ventas.

Vive en su propio módulo (y no dentro de ``components.secciones``) para que la
página de Ventas la importe desde un módulo independiente: así el recargado en
caliente de Streamlit siempre toma la versión más reciente.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from utils.constants import (
    COL_DESCRIPCION,
    COL_ESTADO,
    COL_FECHA,
    COLOR_TINTA_SECUNDARIA,
    FUENTE_UI,
    MESES_ES,
)
from utils.formatting import formato_entero, truncar

#: Mes (nombre) -> número de mes.
_MES_A_NUMERO = {nombre: numero for numero, nombre in MESES_ES.items()}

TODOS = "Todos"


def barra_filtros_ventas(
    df_completo: pd.DataFrame,
    *,
    con_comparacion: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any], Any]:
    """Barra de filtros tipo «slicer» para la página de Ventas.

    Dibuja cuatro filtros con aspecto de tarjeta (Año, Mes en botones, Estado y
    Producto) y aplica la selección sobre todos los datos cargados.

    Returns:
        ``(df_filtrado, metricas, comparacion)`` listos para alimentar la página.
    """
    from components.filters import EstadoFiltros, aplicar_filtros
    from services.comparison_service import Comparacion, comparar_periodos
    from services.metrics_service import calcular_metricas

    _inyectar_estilos_filtros()

    fechas = pd.to_datetime(df_completo[COL_FECHA], errors="coerce")
    anios = sorted(fechas.dt.year.dropna().astype(int).unique().tolist())

    if not anios:
        st.info("Los datos cargados no tienen fechas válidas para filtrar por año y mes.")
        metricas = calcular_metricas(df_completo)
        return df_completo, metricas, Comparacion(metricas_actual=metricas)

    fila1 = st.columns([1, 3], gap="small")

    # --- Año -----------------------------------------------------------------
    with fila1[0]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Año</div>', unsafe_allow_html=True)
            anio = st.selectbox(
                "Año", anios, index=len(anios) - 1,
                label_visibility="collapsed", key="vt_anio",
            )

    # Meses disponibles para el año elegido, en orden de calendario.
    del_anio = fechas.dt.year == anio
    meses_num = sorted(fechas[del_anio].dt.month.dropna().astype(int).unique().tolist())
    meses_nombres = [MESES_ES[m] for m in meses_num]

    # --- Mes -----------------------------------------------------------------
    with fila1[1]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Mes</div>', unsafe_allow_html=True)
            mes = st.segmented_control(
                "Mes", [TODOS] + meses_nombres, default=TODOS,
                label_visibility="collapsed", key="vt_mes",
            )

    fila2 = st.columns([1, 2], gap="small")

    # --- Estado --------------------------------------------------------------
    estados = _valores(df_completo, COL_ESTADO)
    with fila2[0]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Estado</div>', unsafe_allow_html=True)
            estado = st.selectbox(
                "Estado", [TODOS] + estados,
                label_visibility="collapsed", key="vt_estado",
            )

    # --- Producto ------------------------------------------------------------
    productos = _valores(df_completo, COL_DESCRIPCION)
    with fila2[1]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Producto</div>', unsafe_allow_html=True)
            producto = st.selectbox(
                "Producto", [TODOS] + productos,
                format_func=lambda v: v if v == TODOS else truncar(v, 70),
                label_visibility="collapsed", key="vt_producto",
            )

    # --- Rango de fechas a partir de Año / Mes -------------------------------
    if mes and mes != TODOS:
        numero_mes = _MES_A_NUMERO[mes]
        inicio = date(anio, numero_mes, 1)
        fin = (pd.Timestamp(anio, numero_mes, 1) + pd.offsets.MonthEnd(0)).date()
    else:
        inicio, fin = date(anio, 1, 1), date(anio, 12, 31)

    estados_sel = [estado] if estado != TODOS else []
    productos_sel = [producto] if producto != TODOS else []

    filtros = EstadoFiltros(
        fecha_inicio=inicio, fecha_fin=fin,
        estados=estados_sel, productos=productos_sel,
    )
    df_filtrado = aplicar_filtros(df_completo, filtros)
    metricas = calcular_metricas(df_filtrado)

    # --- Comparación contra el periodo anterior equivalente ------------------
    if con_comparacion:
        base = aplicar_filtros(
            df_completo,
            EstadoFiltros(estados=estados_sel, productos=productos_sel),
        )
        comparacion = comparar_periodos(base, inicio, fin, "Periodo anterior equivalente")
    else:
        comparacion = Comparacion(metricas_actual=metricas, rango_actual=(inicio, fin))

    # --- Resumen de la selección --------------------------------------------
    partes = [f"{formato_entero(len(df_filtrado))} transacciones", f"{inicio:%d/%m/%Y} – {fin:%d/%m/%Y}"]
    if estado != TODOS:
        partes.append(f"estado: {estado}")
    if producto != TODOS:
        partes.append(f"producto: {truncar(producto, 40)}")
    st.caption(" · ".join(partes))

    return df_filtrado, metricas, comparacion


def _valores(df: pd.DataFrame, columna: str) -> list[str]:
    """Valores distintos de una columna, ordenados, sin vacíos ni marcadores."""
    if df.empty or columna not in df.columns:
        return []
    serie = df[columna].astype("string").dropna()
    serie = serie[serie.str.strip().ne("") & ~serie.isin(["Sin estado", "Sin descripción"])]
    return sorted(serie.unique().tolist())


def _inyectar_estilos_filtros() -> None:
    """Estilo de la barra de filtros para que parezca un panel de «slicers»."""
    st.markdown(
        f"""
        <style>
        .filtro-titulo {{
            font-family: {FUENTE_UI};
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .04em;
            color: {COLOR_TINTA_SECUNDARIA};
            margin-bottom: 6px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

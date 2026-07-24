"""Página de reembolsos: cuánto se devuelve, de qué productos y desde dónde."""

from __future__ import annotations

import streamlit as st

from components import charts
from components.layout import (
    barra_lateral_usuario,
    nota_metodologica,
    preparar_pagina,
    selector_frecuencia,
)
from components.metric_cards import fila_tarjetas
from components.tables import tabla_simple
from services.export_service import exportar_excel_simple, nombre_archivo_exportacion
from services.metrics_service import (
    serie_temporal,
    tabla_por_ciudad,
    tabla_por_estado,
    tabla_por_sku,
    tabla_reembolsos,
)
from utils.constants import COLOR_REEMBOLSOS, ETIQUETAS_COLUMNAS
from utils.formatting import formato_moneda, formato_porcentaje

barra_lateral_usuario()

contexto = preparar_pagina(
    "Reembolsos",
    "Devoluciones del periodo y su impacto sobre el resultado.",
    "↩️",
)
if contexto is None:
    st.stop()

df, metricas, comparacion = contexto.df, contexto.metricas, contexto.comparacion

# =============================================================================
# Indicadores
# =============================================================================

fila_tarjetas(
    metricas,
    [
        ("importe_reembolsado", "moneda"),
        ("pedidos_reembolsados", "entero"),
        ("unidades_reembolsadas", "entero"),
        ("transacciones_reembolso", "entero"),
        ("tasa_reembolso", "porcentaje"),
    ],
    comparacion,
    columnas=5,
)
fila_tarjetas(
    metricas,
    [
        ("pct_pedidos_reembolsados", "porcentaje"),
        ("pct_unidades_reembolsadas", "porcentaje"),
        ("ventas_reembolsadas", "moneda"),
    ],
    comparacion,
    columnas=3,
)

if metricas.get("transacciones_reembolso", 0) == 0:
    st.success("No se registraron reembolsos en el periodo seleccionado.")
else:
    st.caption(
        f"Los reembolsos representan {formato_porcentaje(metricas.get('tasa_reembolso'))} "
        f"de las ventas brutas ({formato_moneda(metricas.get('importe_reembolsado'))})."
    )

nota_metodologica(
    "el importe reembolsado usa la columna «total» de las filas de tipo Reembolso, así "
    "que ya viene neto de la comisión que Amazon devuelve. Un reembolso puede "
    "corresponder a un pedido de un periodo anterior."
)

st.markdown("---")

# =============================================================================
# Evolución y comparación
# =============================================================================

frecuencia = selector_frecuencia("frecuencia_reembolsos")
serie = serie_temporal(df, frecuencia)

col_a, col_b = st.columns(2)
with col_a:
    st.plotly_chart(
        charts.linea_temporal(
            serie, "reembolsos", f"Reembolsos por {frecuencia.lower()}",
            color=COLOR_REEMBOLSOS,
        ),
        width="stretch",
    )
with col_b:
    st.plotly_chart(charts.pedidos_vs_reembolsos(serie), width="stretch")

st.markdown("---")

# =============================================================================
# Por producto y ubicación
# =============================================================================

tabla_sku = tabla_por_sku(df)
con_reembolso = tabla_sku.loc[tabla_sku["reembolsos"] > 0] if not tabla_sku.empty else tabla_sku

tab_producto, tab_ubicacion, tab_detalle = st.tabs(
    ["Por producto", "Por ubicación", "Detalle de devoluciones"]
)

with tab_producto:
    if con_reembolso.empty:
        st.info("Ningún producto registró devoluciones en el periodo.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(
                charts.top_barras(
                    con_reembolso, "sku", "reembolsos",
                    "SKU con mayor importe reembolsado",
                    color=COLOR_REEMBOLSOS,
                ),
                width="stretch",
            )
        with col_b:
            st.plotly_chart(
                charts.top_barras(
                    con_reembolso, "sku", "tasa_reembolso",
                    "SKU con mayor tasa de reembolso",
                    "Importe reembolsado sobre las ventas del SKU",
                    color=COLOR_REEMBOLSOS, es_moneda=False,
                ),
                width="stretch",
            )

        vista = con_reembolso[[
            c for c in (
                "sku", "descripcion", "unidades", "ventas",
                "unidades_reembolsadas", "reembolsos", "tasa_reembolso", "neto",
            ) if c in con_reembolso.columns
        ]]
        tabla_simple(vista, columna_barra="reembolsos")

with tab_ubicacion:
    estados = tabla_por_estado(df)
    ciudades = tabla_por_ciudad(df)
    estados_con = estados.loc[estados["reembolsos"] > 0] if not estados.empty else estados
    ciudades_con = ciudades.loc[ciudades["reembolsos"] > 0] if not ciudades.empty else ciudades

    if estados_con.empty:
        st.info("No hay reembolsos con estado identificado en el periodo.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(
                charts.top_barras(
                    estados_con, "estado", "reembolsos",
                    "Estados con más reembolsos", color=COLOR_REEMBOLSOS,
                ),
                width="stretch",
            )
        with col_b:
            st.plotly_chart(
                charts.top_barras(
                    ciudades_con, "ciudad", "reembolsos",
                    "Ciudades con más reembolsos", color=COLOR_REEMBOLSOS,
                ),
                width="stretch",
            )

with tab_detalle:
    detalle = tabla_reembolsos(df)
    if detalle.empty:
        st.info("No hay transacciones de reembolso en el periodo.")
    else:
        st.dataframe(
            detalle.rename(columns=ETIQUETAS_COLUMNAS),
            width="stretch",
            hide_index=True,
        )
        st.download_button(
            "Descargar reporte de reembolsos (Excel)",
            data=exportar_excel_simple(
                detalle.rename(columns=ETIQUETAS_COLUMNAS),
                "Reembolsos", "Detalle de reembolsos del periodo",
            ),
            file_name=nombre_archivo_exportacion("reporte_reembolsos"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

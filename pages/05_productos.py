"""Página de productos: desempeño por SKU, Pareto y tabla detallada."""

from __future__ import annotations

import streamlit as st

from components import charts
from components.layout import barra_lateral_usuario, nota_metodologica, preparar_pagina
from components.metric_cards import fila_tarjetas
from components.tables import tabla_productos
from services.export_service import (
    exportar_csv,
    exportar_excel_simple,
    nombre_archivo_exportacion,
)
from services.metrics_service import curva_pareto, tabla_por_producto, tabla_por_sku
from utils.constants import COLOR_NETO, COLOR_REEMBOLSOS, COLOR_TARIFAS, COLOR_UNIDADES
from utils.formatting import formato_entero, formato_porcentaje

barra_lateral_usuario()

contexto = preparar_pagina(
    "Productos",
    "Qué SKU sostienen la venta y cuáles cuestan más de lo que aportan.",
    "📦",
)
if contexto is None:
    st.stop()

df, metricas, comparacion = contexto.df, contexto.metricas, contexto.comparacion

tabla_sku = tabla_por_sku(df)
if tabla_sku.empty:
    st.info("No hay productos con ventas en el periodo seleccionado.")
    st.stop()

# =============================================================================
# Indicadores de catálogo
# =============================================================================

fila_tarjetas(
    metricas,
    [
        ("skus_vendidos", "entero"),
        ("productos_vendidos", "entero"),
        ("precio_promedio_unidad", "moneda"),
        ("unidades_por_pedido", "decimal"),
        ("neto_por_sku", "moneda"),
    ],
    comparacion,
    columnas=5,
)

# --- Concentración -----------------------------------------------------------
pareto = curva_pareto(tabla_sku)
if not pareto.empty:
    skus_80 = int((pareto["participacion_acumulada"] <= 0.80).sum()) + 1
    skus_80 = min(skus_80, len(pareto))
    st.caption(
        f"{formato_entero(skus_80)} de {formato_entero(len(pareto))} SKU concentran el 80% "
        f"de las ventas. El SKU líder representa "
        f"{formato_porcentaje(tabla_sku.iloc[0]['participacion'])} del total."
    )

st.markdown("---")

# =============================================================================
# Rankings
# =============================================================================

tab_ventas, tab_rentabilidad, tab_riesgo = st.tabs(
    ["Ventas y unidades", "Neto y tarifas", "Reembolsos y concentración"]
)

with tab_ventas:
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.top_barras(
                tabla_sku, "sku", "ventas",
                "Top 10 SKU por ventas", "Ventas brutas del periodo",
            ),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.top_barras(
                tabla_sku, "sku", "unidades",
                "Top 10 SKU por unidades", "Piezas vendidas",
                color=COLOR_UNIDADES, es_moneda=False,
            ),
            width="stretch",
        )

    tabla_producto = tabla_por_producto(df)
    st.plotly_chart(
        charts.top_barras(
            tabla_producto, "descripcion", "pedidos",
            "Top 10 productos por número de pedidos", "Agrupado por descripción",
            color=charts.COLOR_PEDIDOS, es_moneda=False,
        ),
        width="stretch",
    )

with tab_rentabilidad:
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.top_barras(
                tabla_sku, "sku", "neto",
                "Top 10 SKU por neto", "Depósito después de tarifas de Amazon",
                color=COLOR_NETO,
            ),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.top_barras(
                tabla_sku, "sku", "tarifa_por_unidad",
                "SKU con mayor tarifa promedio por unidad",
                "Cuánto cobra Amazon por cada pieza despachada",
                color=COLOR_TARIFAS,
            ),
            width="stretch",
        )
    st.plotly_chart(charts.dispersion_sku(tabla_sku), width="stretch")

with tab_riesgo:
    col_a, col_b = st.columns(2)
    with col_a:
        con_reembolso = tabla_sku.loc[tabla_sku["reembolsos"] > 0]
        st.plotly_chart(
            charts.top_barras(
                con_reembolso, "sku", "tasa_reembolso",
                "SKU con mayor tasa de reembolso",
                "Importe reembolsado sobre las ventas del SKU",
                color=COLOR_REEMBOLSOS, es_moneda=False,
            ) if not con_reembolso.empty
            else charts.figura_vacia("No hubo reembolsos en el periodo."),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.dona_composicion(
                tabla_sku, "sku", "ventas",
                "Participación de las ventas por SKU",
                "A partir del octavo, el resto se agrupa en «Otros»",
            ),
            width="stretch",
        )

    st.plotly_chart(charts.pareto(pareto, "sku"), width="stretch")

st.markdown("---")

# =============================================================================
# Tabla detallada
# =============================================================================

st.markdown("### Tabla de productos")
st.caption(
    "Ordena por cualquier columna haciendo clic en su encabezado. Usa el buscador "
    "para localizar un SKU y el selector para mostrar u ocultar columnas."
)

visible = tabla_productos(tabla_sku)

nota_metodologica(
    "las tarifas se muestran como magnitud positiva. «Neto» es el depósito después de "
    "los cargos de Amazon, no la utilidad: para la utilidad necesitas capturar tus "
    "costos en la página de Costos y rentabilidad."
)

col_a, col_b = st.columns(2)
with col_a:
    st.download_button(
        "Descargar tabla (CSV)",
        data=exportar_csv(visible),
        file_name=nombre_archivo_exportacion("productos", "csv"),
        mime="text/csv",
        width="stretch",
    )
with col_b:
    st.download_button(
        "Descargar tabla (Excel)",
        data=exportar_excel_simple(tabla_sku, "Productos", "Desempeño por SKU"),
        file_name=nombre_archivo_exportacion("productos"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

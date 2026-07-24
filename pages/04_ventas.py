"""Página de ventas: evolución temporal y detalle de pedidos."""

from __future__ import annotations

import streamlit as st

from components import charts
from components.layout import (
    barra_lateral_usuario,
    boton_descarga_filtrados,
    nota_metodologica,
    preparar_pagina,
    selector_frecuencia,
)
from components.metric_cards import fila_tarjetas
from components.tables import tabla_pedidos
from services.metrics_service import (
    detalle_pedidos,
    resumen_pedidos,
    serie_temporal,
)
from utils.constants import COLOR_NETO, COLOR_TARIFAS, COLOR_UNIDADES, COLOR_VENTAS

barra_lateral_usuario()

contexto = preparar_pagina(
    "Ventas",
    "Evolución de la venta, los pedidos y las unidades en el periodo.",
    "📈",
)
if contexto is None:
    st.stop()

df, metricas, comparacion = contexto.df, contexto.metricas, contexto.comparacion

# =============================================================================
# Indicadores de venta
# =============================================================================

fila_tarjetas(
    metricas,
    [
        ("ventas_brutas", "moneda"),
        ("impuestos_cobrados", "moneda"),
        ("ventas_con_impuestos", "moneda"),
        ("pedidos_unicos", "entero"),
        ("unidades", "entero"),
    ],
    comparacion,
    columnas=5,
)
fila_tarjetas(
    metricas,
    [
        ("ticket_promedio", "moneda"),
        ("precio_promedio_unidad", "moneda"),
        ("unidades_por_pedido", "decimal"),
        ("skus_vendidos", "entero"),
        ("ventas_por_dia", "moneda"),
    ],
    comparacion,
    columnas=5,
)

nota_metodologica(
    "las ventas brutas y las unidades se calculan solo con las filas de tipo «Pedido»; "
    "los pedidos únicos se cuentan por «Id. del pedido», así que un pedido con varias "
    "líneas cuenta una sola vez."
)

st.markdown("---")

# =============================================================================
# Evolución temporal
# =============================================================================

frecuencia = selector_frecuencia("frecuencia_ventas")
serie = serie_temporal(df, frecuencia)

tab_ventas, tab_operacion, tab_financiero = st.tabs(
    ["Ventas y ticket", "Pedidos y unidades", "Composición financiera"]
)

with tab_ventas:
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.linea_temporal(serie, "ventas", f"Ventas por {frecuencia.lower()}"),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.linea_temporal(
                serie, "ticket_promedio", f"Ticket promedio por {frecuencia.lower()}",
                color=COLOR_NETO,
            ),
            width="stretch",
        )

with tab_operacion:
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.barras_temporales(
                serie, "pedidos", f"Pedidos por {frecuencia.lower()}", es_moneda=False
            ),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.barras_temporales(
                serie, "unidades", f"Unidades por {frecuencia.lower()}",
                color=COLOR_UNIDADES,
                es_moneda=False,
            ),
            width="stretch",
        )
    st.plotly_chart(charts.barras_horas(df), width="stretch")

with tab_financiero:
    st.plotly_chart(
        charts.multiserie_temporal(
            serie,
            {
                "ventas": ("Ventas", COLOR_VENTAS),
                "tarifas": ("Tarifas Amazon", COLOR_TARIFAS),
                "neto": ("Neto depositable", COLOR_NETO),
            },
            f"Ventas, tarifas y neto por {frecuencia.lower()}",
        ),
        width="stretch",
    )
    st.caption(
        "Las tres series están en pesos, así que comparten un solo eje. Las tarifas se "
        "muestran como magnitud positiva para poder leerlas junto a las ventas."
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.linea_temporal(
                serie, "neto", f"Neto por {frecuencia.lower()}", color=COLOR_NETO
            ),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.linea_temporal(
                serie, "tarifas", f"Tarifas por {frecuencia.lower()}", color=COLOR_TARIFAS
            ),
            width="stretch",
        )

st.markdown("---")

# =============================================================================
# Detalle de pedidos
# =============================================================================

st.markdown("### Detalle de pedidos")
st.caption(
    "Cada renglón es una transacción del reporte. Un pedido puede aparecer varias "
    "veces si incluye distintos SKU o si generó un reembolso posterior."
)

detalle = detalle_pedidos(df)
resumen = resumen_pedidos(df)
visible = tabla_pedidos(detalle, resumen)

col_a, col_b = st.columns(2)
with col_a:
    boton_descarga_filtrados(visible, "detalle_pedidos")
with col_b:
    if not resumen.empty:
        from services.export_service import exportar_excel_simple, nombre_archivo_exportacion

        st.download_button(
            "Descargar resumen por pedido (Excel)",
            data=exportar_excel_simple(resumen, "Pedidos", "Resumen por pedido"),
            file_name=nombre_archivo_exportacion("resumen_por_pedido"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

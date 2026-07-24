"""Página de geografía: dónde compran tus clientes."""

from __future__ import annotations

import streamlit as st

from components import charts
from components.layout import barra_lateral_usuario, nota_metodologica, preparar_pagina
from components.tables import tabla_simple
from services.export_service import exportar_excel_simple, nombre_archivo_exportacion
from services.metrics_service import tabla_por_ciudad, tabla_por_estado
from utils.constants import COLOR_NETO, COLOR_PEDIDOS, COLOR_UNIDADES
from utils.formatting import formato_entero, formato_moneda, formato_porcentaje

barra_lateral_usuario()

contexto = preparar_pagina(
    "Geografía",
    "Distribución de la venta por estado y por ciudad.",
    "🗺️",
)
if contexto is None:
    st.stop()

df = contexto.df

estados = tabla_por_estado(df)
ciudades = tabla_por_ciudad(df)

if estados.empty:
    st.info(
        "El reporte no trae información de estado. Verifica que el archivo incluya "
        "la columna «estado del pedido»."
    )
    st.stop()

# =============================================================================
# Resumen
# =============================================================================

lider = estados.iloc[0]
col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Estados con venta", formato_entero(len(estados)))
col_b.metric("Ciudades con venta", formato_entero(len(ciudades)))
col_c.metric("Estado líder", str(lider["estado"]))
col_d.metric(
    "Participación del líder",
    formato_porcentaje(lider["participacion"]),
    help=f"{formato_moneda(lider['ventas'])} de venta bruta.",
)

st.markdown("---")

# =============================================================================
# Mapa
# =============================================================================

mapa = charts.mapa_mexico(estados, "ventas")
if mapa is not None:
    st.plotly_chart(mapa, width="stretch")
    st.caption(
        "El color codifica el importe vendido: entre más oscuro, mayor venta. "
        "Los estados sin registros aparecen sin color."
    )
else:
    st.info(
        "El mapa de México necesita descargar su contorno geográfico y no hubo conexión. "
        "Abajo tienes la misma información en barras."
    )

# =============================================================================
# Rankings por estado
# =============================================================================

tab_ventas, tab_operacion, tab_ciudades = st.tabs(
    ["Ventas y neto", "Pedidos y unidades", "Ciudades"]
)

with tab_ventas:
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.top_barras(
                estados, "estado", "ventas",
                "Top 10 estados por ventas", "Ventas brutas del periodo",
            ),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.top_barras(
                estados, "estado", "neto",
                "Top 10 estados por neto", "Depósito después de tarifas",
                color=COLOR_NETO,
            ),
            width="stretch",
        )

with tab_operacion:
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.top_barras(
                estados, "estado", "pedidos",
                "Top 10 estados por pedidos", color=COLOR_PEDIDOS, es_moneda=False,
            ),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.top_barras(
                estados, "estado", "unidades",
                "Top 10 estados por unidades", color=COLOR_UNIDADES, es_moneda=False,
            ),
            width="stretch",
        )

with tab_ciudades:
    st.plotly_chart(
        charts.top_barras(
            ciudades, "ciudad", "ventas",
            "Top 10 ciudades por ventas", "Ventas brutas del periodo",
        ),
        width="stretch",
    )
    st.markdown("#### Detalle por ciudad")
    tabla_simple(
        ciudades[[
            c for c in ("ciudad", "pedidos", "unidades", "ventas", "ticket_promedio", "neto", "participacion")
            if c in ciudades.columns
        ]].head(200),
        etiquetas={"ciudad": "Ciudad"},
        columna_barra="ventas",
    )

st.markdown("---")

# =============================================================================
# Tabla geográfica
# =============================================================================

st.markdown("### Tabla geográfica por estado")
vista_estados = estados[[
    c for c in (
        "estado", "pedidos", "unidades", "ventas", "ticket_promedio",
        "total_cargos", "reembolsos", "neto", "margen_neto", "participacion",
    ) if c in estados.columns
]]
tabla_simple(vista_estados, etiquetas={"estado": "Estado"}, columna_barra="ventas")

nota_metodologica(
    "las filas sin estado (cargos de almacenamiento, suscripciones y ajustes) se agrupan "
    "como «Sin estado»: no corresponden a un pedido de un cliente."
)

col_a, col_b = st.columns(2)
with col_a:
    st.download_button(
        "Descargar reporte por estado (Excel)",
        data=exportar_excel_simple(vista_estados, "Estados", "Ventas por estado"),
        file_name=nombre_archivo_exportacion("reporte_estados"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
with col_b:
    st.download_button(
        "Descargar reporte por ciudad (Excel)",
        data=exportar_excel_simple(ciudades, "Ciudades", "Ventas por ciudad"),
        file_name=nombre_archivo_exportacion("reporte_ciudades"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

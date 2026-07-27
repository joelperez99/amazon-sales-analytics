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
from components.filtros_ventas import barra_filtros_ventas
from components.metric_cards import tarjeta
from components.secciones import seccion_geografia
from components.tables import tabla_pedidos
from services.auth_service import tiene_funcion
from services.metrics_service import (
    detalle_pedidos,
    resumen_pedidos,
    serie_temporal,
    tabla_por_producto,
)
from utils.constants import COLOR_NETO, COLOR_TARIFAS, COLOR_UNIDADES, COLOR_VENTAS

barra_lateral_usuario()

# La página de Ventas usa su propia barra de filtros (Año, Mes, Estado, Producto)
# en la parte superior, así que se desactivan los filtros de la barra lateral.
contexto = preparar_pagina(
    "Ventas",
    "Evolución de la venta, los pedidos y las unidades en el periodo.",
    "📈",
    con_filtros=False,
)
if contexto is None:
    st.stop()

# --- Barra de filtros del reporte ------------------------------------------
df, metricas, comparacion = barra_filtros_ventas(
    contexto.df_completo,
    con_comparacion=tiene_funcion(contexto.sesion, "comparacion_periodos"),
)

if df.empty:
    st.warning(
        "No hay transacciones para la combinación de filtros seleccionada. "
        "Ajusta el año, el mes, el estado o el producto."
    )
    st.stop()

st.markdown("---")

# =============================================================================
# Indicadores de venta
# =============================================================================

# Cuatro tarjetas: la venta con impuestos se muestra con la etiqueta corta «Ventas».
_col1, _col2, _col3, _col4 = st.columns(4, gap="small")
with _col1:
    tarjeta("ventas_con_impuestos", metricas.get("ventas_con_impuestos"), comparacion,
            "moneda", etiqueta="Ventas")
with _col2:
    tarjeta("pedidos_unicos", metricas.get("pedidos_unicos"), comparacion, "entero")
with _col3:
    tarjeta("unidades", metricas.get("unidades"), comparacion, "entero")
with _col4:
    tarjeta("ticket_promedio", metricas.get("ticket_promedio"), comparacion, "moneda")

nota_metodologica(
    "«Ventas» incluye los impuestos cobrados al cliente; las unidades se calculan solo "
    "con las filas de tipo «Pedido» y los pedidos únicos se cuentan por «Id. del pedido», "
    "así que un pedido con varias líneas cuenta una sola vez."
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
# Productos por unidades vendidas
# =============================================================================

st.markdown("### Productos más vendidos")
st.caption(
    "Unidades vendidas por producto (agrupado por su descripción) en el periodo filtrado. "
    "Se muestran todos los productos con al menos una unidad vendida, de mayor a menor. "
    "Las unidades se cuentan solo con las filas de tipo «Pedido»."
)
productos_con_venta = tabla_por_producto(df)
if "unidades" in productos_con_venta.columns:
    productos_con_venta = productos_con_venta[productos_con_venta["unidades"] > 0]
st.plotly_chart(
    charts.top_barras(
        productos_con_venta,
        "descripcion",
        "unidades",
        "Productos por unidades vendidas",
        "Agrupado por descripción · de mayor a menor",
        color=COLOR_UNIDADES,
        es_moneda=False,
        top=len(productos_con_venta),
        etiquetas_izquierda=True,
    ),
    width="stretch",
    key="ventas_top_productos_unidades",
)

st.markdown("---")

# =============================================================================
# Distribución geográfica
# =============================================================================

st.markdown("### ¿Dónde se vendió?")
st.caption("Distribución de la venta por estado y ciudad en el periodo filtrado.")
seccion_geografia(
    df,
    incluir_tabla_detalle=False,   # la tabla completa vive en la página de Geografía
    incluir_descargas=False,
    grafico_secundario="ciudades",  # junto a estados por ventas, top ciudades por ventas
    prefijo="ventas_geo",
)
st.caption("Para el detalle completo por estado y ciudad, abre la página **Geografía**.")

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

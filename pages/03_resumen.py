"""Resumen ejecutivo: las diez tarjetas principales, la cascada y los hallazgos."""

from __future__ import annotations

import streamlit as st

from components import charts
from components.alerts import panel_hallazgos, resumen_hallazgos
from components.layout import (
    barra_lateral_usuario,
    boton_descarga_filtrados,
    preparar_pagina,
    selector_frecuencia,
)
from components.metric_cards import tarjetas_principales
from components.tables import tabla_simple
from services.alerts_service import generar_hallazgos
from services.auth_service import tiene_funcion
from services.comparison_service import serie_comparativa, tabla_comparativa
from services.metrics_service import (
    desglose_cascada,
    serie_temporal,
    tabla_por_sku,
)
from utils.formatting import formato_fecha, formato_moneda

barra_lateral_usuario()

contexto = preparar_pagina(
    "Resumen ejecutivo",
    "Los indicadores clave del periodo seleccionado.",
    "📊",
)
if contexto is None:
    st.stop()

df, metricas, comparacion = contexto.df, contexto.metricas, contexto.comparacion

# =============================================================================
# Hallazgos destacados
# =============================================================================

hallazgos = generar_hallazgos(df, metricas, comparacion)
resumen_hallazgos(hallazgos)

# =============================================================================
# Tarjetas principales
# =============================================================================

if comparacion.hay_comparacion:
    inicio_ant, fin_ant = comparacion.rango_anterior
    st.caption(
        f"Comparando contra {formato_fecha(inicio_ant)} – {formato_fecha(fin_ant)} "
        f"({comparacion.modo.lower()})."
    )

tarjetas_principales(metricas, comparacion)

# --- Alerta de conciliación --------------------------------------------------
from utils.config import get_settings  # noqa: E402

tolerancia = get_settings().alertas.tolerancia_conciliacion
diferencia = metricas.get("diferencia_conciliacion", 0.0)
if abs(diferencia) > tolerancia:
    st.error(
        f"**Conciliación:** la suma de la columna «total» "
        f"({formato_moneda(metricas['neto'])}) no coincide con la suma de los componentes "
        f"({formato_moneda(metricas['neto_reconstruido'])}). "
        f"Diferencia: {formato_moneda(diferencia)}. "
        "Suele indicar que falta una columna monetaria en el archivo."
    )
else:
    st.caption(
        f"Conciliación correcta: el neto por columna «total» y el neto reconstruido "
        f"con los componentes coinciden dentro de {formato_moneda(tolerancia)}."
    )

st.markdown("---")

# =============================================================================
# Evolución y cascada
# =============================================================================

col_izq, col_der = st.columns([3, 2])

with col_izq:
    frecuencia = selector_frecuencia("frecuencia_resumen")
    serie = serie_temporal(df, frecuencia)
    st.plotly_chart(
        charts.linea_temporal(serie, "ventas", f"Ventas por {frecuencia.lower()}"),
        width="stretch",
    )

with col_der:
    st.plotly_chart(charts.comparacion_bruto_neto(metricas), width="stretch")

st.plotly_chart(charts.cascada_neto(desglose_cascada(df)), width="stretch")
st.caption(
    "Los escalones suman exactamente el neto. Los reembolsos ya están incluidos dentro "
    "de «Ventas de productos» y de «Tarifas de venta» (la devolución regresa parte de "
    "la comisión), por eso no llevan un escalón propio."
)

# =============================================================================
# Comparación entre periodos
# =============================================================================

if tiene_funcion(contexto.sesion, "comparacion_periodos"):
    st.markdown("### Comparación entre periodos")
    if comparacion.hay_comparacion:
        tab_tabla, tab_grafica = st.tabs(["Tabla comparativa", "Curvas superpuestas"])

        with tab_tabla:
            tabla = tabla_comparativa(comparacion)
            st.dataframe(
                tabla,
                width="stretch",
                hide_index=True,
                column_config={
                    "Periodo actual": st.column_config.NumberColumn(format="%.2f"),
                    "Periodo anterior": st.column_config.NumberColumn(format="%.2f"),
                    "Diferencia": st.column_config.NumberColumn(format="%.2f"),
                    "Variación %": st.column_config.NumberColumn(format="percent"),
                },
            )
            st.caption(
                "Cuando el periodo anterior vale cero la variación porcentual se muestra "
                "vacía: un porcentaje sobre base cero no significa nada."
            )

        with tab_grafica:
            metrica = st.selectbox(
                "Métrica a comparar",
                ["ventas", "pedidos", "unidades", "neto", "tarifas", "reembolsos", "ticket_promedio"],
                format_func=lambda c: {
                    "ventas": "Ventas", "pedidos": "Pedidos", "unidades": "Unidades",
                    "neto": "Neto", "tarifas": "Tarifas", "reembolsos": "Reembolsos",
                    "ticket_promedio": "Ticket promedio",
                }[c],
                key="metrica_comparacion",
            )
            serie_doble = serie_comparativa(contexto.df_completo, comparacion, frecuencia)
            st.plotly_chart(
                charts.lineas_comparadas(
                    serie_doble, metrica,
                    f"{metrica.replace('_', ' ').capitalize()}: actual frente a anterior",
                    es_moneda=metrica not in {"pedidos", "unidades"},
                ),
                width="stretch",
            )
    else:
        st.info(
            "No hay datos en el periodo de comparación. Carga más historial o elige "
            "otro modo de comparación en la barra lateral."
        )
else:
    from components.alerts import funcion_no_disponible

    funcion_no_disponible("La comparación entre periodos")

st.markdown("---")

# =============================================================================
# Top productos y hallazgos
# =============================================================================

col_prod, col_hall = st.columns([1, 1])

with col_prod:
    tabla_sku = tabla_por_sku(df)
    st.plotly_chart(
        charts.top_barras(
            tabla_sku, "sku", "ventas",
            "Top 10 SKU por ventas", "Ventas brutas del periodo",
        ),
        width="stretch",
    )

with col_hall:
    panel_hallazgos(hallazgos, "Hallazgos", maximo=6, con_filtro=False)
    if len(hallazgos) > 6:
        st.caption(f"Hay {len(hallazgos)} hallazgos en total; los demás se detallan por sección.")

st.markdown("---")

# =============================================================================
# Indicadores complementarios
# =============================================================================

with st.expander("Todos los indicadores del periodo", expanded=False):
    import pandas as pd

    from utils.constants import DICCIONARIO_METRICAS

    filas = [
        {
            "Grupo": info["grupo"],
            "Métrica": info["nombre"],
            "Valor": metricas.get(clave),
            "Fórmula": info["formula"],
        }
        for clave, info in DICCIONARIO_METRICAS.items()
        if clave in metricas
    ]
    tabla_simple(pd.DataFrame(filas))

boton_descarga_filtrados(df, "resumen_filtrado")

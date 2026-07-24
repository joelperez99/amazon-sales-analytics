"""Página de tarifas: cuánto cobra Amazon y por qué concepto."""

from __future__ import annotations

import pandas as pd
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
    desglose_tarifas,
    serie_temporal,
    tabla_por_sku,
)
from utils.constants import COLOR_TARIFAS
from utils.formatting import formato_moneda, formato_porcentaje

barra_lateral_usuario()

contexto = preparar_pagina(
    "Tarifas",
    "Todo lo que Amazon descuenta: comisiones, logística, almacenamiento y servicios.",
    "💳",
)
if contexto is None:
    st.stop()

df, metricas, comparacion = contexto.df, contexto.metricas, contexto.comparacion

# =============================================================================
# Indicadores de cargos
# =============================================================================

fila_tarjetas(
    metricas,
    [
        ("total_cargos", "moneda"),
        ("tarifas_venta", "moneda"),
        ("tarifas_fba", "moneda"),
        ("tarifas_inventario", "moneda"),
        ("tarifas_servicio", "moneda"),
    ],
    comparacion,
    columnas=5,
)
fila_tarjetas(
    metricas,
    [
        ("retenciones", "moneda"),
        ("descuentos_promocionales", "moneda"),
        ("tarifa_por_pedido", "moneda"),
        ("tarifa_por_unidad", "moneda"),
        ("pct_cargos", "porcentaje"),
    ],
    comparacion,
    columnas=5,
)

st.info(
    f"De cada peso vendido, Amazon se queda con "
    f"**{formato_porcentaje(metricas.get('pct_cargos'))}** en cargos "
    f"({formato_moneda(metricas.get('total_cargos'))} sobre "
    f"{formato_moneda(metricas.get('ventas_brutas'))} de venta bruta). "
    f"Las comisiones pesan {formato_porcentaje(metricas.get('pct_comisiones'))} "
    f"y la logística FBA {formato_porcentaje(metricas.get('pct_fba'))}."
)

nota_metodologica(
    "las retenciones de impuestos NO se cuentan dentro del total de cargos: es dinero "
    "que Amazon entera a la autoridad fiscal, no una tarifa suya. Se muestra aparte."
)

st.markdown("---")

# =============================================================================
# Composición
# =============================================================================

tarifas = desglose_tarifas(metricas)

col_izq, col_der = st.columns([3, 2])
with col_izq:
    st.plotly_chart(charts.barras_desglose_tarifas(tarifas), width="stretch")
with col_der:
    st.plotly_chart(
        charts.dona_composicion(
            tarifas, "concepto", "importe",
            "Distribución porcentual de los cargos",
        ),
        width="stretch",
    )

# =============================================================================
# Evolución
# =============================================================================

frecuencia = selector_frecuencia("frecuencia_tarifas")
serie = serie_temporal(df, frecuencia)
st.plotly_chart(
    charts.linea_temporal(
        serie, "tarifas", f"Tarifas por {frecuencia.lower()}", color=COLOR_TARIFAS
    ),
    width="stretch",
)

st.markdown("---")

# =============================================================================
# Tarifas por SKU
# =============================================================================

st.markdown("### Cargos por producto")

tabla_sku = tabla_por_sku(df)
if tabla_sku.empty:
    st.info("No hay productos con cargos en el periodo.")
else:
    columnas = [
        "sku", "descripcion", "unidades", "ventas", "tarifas_venta",
        "tarifas_fba", "retenciones", "otros_cargos", "total_cargos",
        "tarifa_por_unidad", "pct_cargos", "neto",
    ]
    vista = tabla_sku[[c for c in columnas if c in tabla_sku.columns]].copy()
    tabla_simple(
        vista,
        etiquetas={
            "sku": "SKU", "descripcion": "Descripción", "unidades": "Unidades",
            "ventas": "Ventas", "tarifas_venta": "Tarifas de venta",
            "tarifas_fba": "Tarifas FBA", "retenciones": "Retenciones",
            "otros_cargos": "Otros cargos", "total_cargos": "Total de cargos",
            "tarifa_por_unidad": "Tarifa por unidad", "pct_cargos": "% de cargos",
            "neto": "Neto",
        },
        columna_barra="total_cargos",
    )

    st.download_button(
        "Descargar reporte de tarifas (Excel)",
        data=exportar_excel_simple(vista, "Tarifas", "Cargos de Amazon por SKU"),
        file_name=nombre_archivo_exportacion("reporte_tarifas"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

# =============================================================================
# Detalle de conceptos
# =============================================================================

with st.expander("Qué incluye cada concepto", expanded=False):
    from utils.constants import DICCIONARIO_METRICAS

    filas = [
        {
            "Concepto": info["nombre"],
            "Importe": metricas.get(clave),
            "Cómo se calcula": info["formula"],
            "Qué es": info["descripcion"],
        }
        for clave, info in DICCIONARIO_METRICAS.items()
        if info["grupo"] == "Tarifas" and clave in metricas
    ]
    st.dataframe(
        pd.DataFrame(filas),
        width="stretch",
        hide_index=True,
        column_config={"Importe": st.column_config.NumberColumn(format="$%.2f")},
    )

    residual = metricas.get("cargos_residuales", 0.0)
    if residual:
        st.caption(
            f"Se recuperaron {formato_moneda(residual)} de cargos que el archivo registró "
            "solo en la columna «total», sin desglose por concepto."
        )

"""Página de liquidaciones: conciliación de cada depósito de Amazon."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import charts
from components.layout import barra_lateral_usuario, nota_metodologica, preparar_pagina
from components.tables import tabla_simple
from services.export_service import exportar_excel_simple, nombre_archivo_exportacion
from services.metrics_service import particionar, tabla_liquidaciones
from utils.constants import COL_LIQUIDACION, ETIQUETAS_COLUMNAS, ORDEN_COLUMNAS
from utils.formatting import formato_entero, formato_fecha, formato_moneda

barra_lateral_usuario()

contexto = preparar_pagina(
    "Liquidaciones",
    "Cada liquidación es un corte de Amazon: qué entró, qué se descontó y qué se depositó.",
    "🧾",
)
if contexto is None:
    st.stop()

df, metricas = contexto.df, contexto.metricas

liquidaciones = tabla_liquidaciones(df)
if liquidaciones.empty:
    st.info(
        "El reporte no trae Id. de liquidación. Verifica que el archivo incluya "
        "la columna «Id. de liquidación»."
    )
    st.stop()

# =============================================================================
# Resumen
# =============================================================================

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Liquidaciones", formato_entero(len(liquidaciones)))
col_b.metric("Neto acumulado", formato_moneda(liquidaciones["neto"].sum()))
col_c.metric("Transferido al banco", formato_moneda(metricas.get("transferencias", 0.0)))
col_d.metric("Transferencias", formato_entero(metricas.get("num_transferencias", 0)))

particiones = particionar(df)
if not particiones.transferencias.empty:
    st.caption(
        "Las transferencias son los retiros a tu cuenta bancaria. **No** se cuentan como "
        "ventas ni como cargos: el dinero ya estaba contabilizado cuando entró por la venta."
    )

st.markdown("---")

# =============================================================================
# Neto por liquidación
# =============================================================================

st.plotly_chart(charts.barras_liquidaciones(liquidaciones), width="stretch")

# =============================================================================
# Tabla de conciliación
# =============================================================================

st.markdown("### Conciliación por liquidación")

vista = liquidaciones.copy()
etiquetas = {
    COL_LIQUIDACION: "Id. de liquidación",
    "fecha_inicial": "Fecha inicial",
    "fecha_final": "Fecha final",
    "fecha_liberacion": "Liberación más reciente",
    "pedidos": "Pedidos",
    "transacciones": "Transacciones",
    "ventas": "Ventas",
    "reembolsos": "Reembolsos",
    "tarifas": "Tarifas",
    "ajustes": "Ajustes",
    "neto": "Neto",
    "transferido": "Transferido",
    "estado": "Estado",
}
tabla_simple(vista, etiquetas=etiquetas, columna_barra="neto")

nota_metodologica(
    "«Neto» es la suma de la columna «total» de la liquidación, sin contar la fila de "
    "transferencia. «Transferido» es esa fila: lo que efectivamente salió hacia tu banco."
)

# =============================================================================
# Detalle de una liquidación
# =============================================================================

st.markdown("### Detalle de una liquidación")

seleccion = st.selectbox(
    "Selecciona la liquidación",
    liquidaciones[COL_LIQUIDACION].astype(str).tolist(),
    key="seleccion_liquidacion",
)

if seleccion:
    detalle = df.loc[df[COL_LIQUIDACION].astype("string") == str(seleccion)]
    fila = liquidaciones.loc[liquidaciones[COL_LIQUIDACION].astype(str) == str(seleccion)].iloc[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ventas", formato_moneda(fila["ventas"]))
    col2.metric("Tarifas", formato_moneda(fila["tarifas"]))
    col3.metric("Reembolsos", formato_moneda(fila["reembolsos"]))
    col4.metric("Neto", formato_moneda(fila["neto"]))

    st.caption(
        f"Periodo: {formato_fecha(fila['fecha_inicial'])} al {formato_fecha(fila['fecha_final'])} · "
        f"{formato_entero(fila['transacciones'])} transacciones · "
        f"{formato_entero(fila['pedidos'])} pedidos · "
        f"Liberación más reciente: {formato_fecha(fila['fecha_liberacion'], con_hora=True)}"
    )

    # --- Composición por tipo dentro de la liquidación ---
    from services.metrics_service import tabla_por_tipo

    col_izq, col_der = st.columns([2, 3])
    with col_izq:
        tipos = tabla_por_tipo(detalle)
        st.dataframe(
            tipos.rename(columns={
                "tipo": "Tipo", "transacciones": "Transacciones",
                "importe": "Importe", "participacion": "Participación",
            }),
            width="stretch", hide_index=True,
            column_config={
                "Importe": st.column_config.NumberColumn("Importe", format="$%.2f"),
                "Participación": st.column_config.NumberColumn("Participación", format="percent"),
            },
        )
    with col_der:
        st.plotly_chart(
            charts.dona_composicion(
                tipos.assign(importe_abs=tipos["importe"].abs()),
                "tipo", "importe_abs",
                "Composición de la liquidación",
            ),
            width="stretch",
        )

    with st.expander(f"Ver las {formato_entero(len(detalle))} transacciones", expanded=False):
        columnas = [c for c in ORDEN_COLUMNAS if c in detalle.columns]
        st.dataframe(
            detalle[columnas].rename(columns=ETIQUETAS_COLUMNAS),
            width="stretch", hide_index=True,
        )

st.markdown("---")

st.download_button(
    "Descargar resumen de conciliación (Excel)",
    data=exportar_excel_simple(
        vista.rename(columns=etiquetas), "Liquidaciones",
        "Conciliación de liquidaciones",
    ),
    file_name=nombre_archivo_exportacion("conciliacion_liquidaciones"),
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    width="stretch",
)

"""Página de costos y rentabilidad.

El reporte de Amazon no trae el costo de compra del producto, así que aquí el
usuario lo captura o lo sube.  Sin costo capturado la aplicación **no** habla de
«utilidad»: usa el término «neto después de tarifas Amazon».
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import charts
from components.alerts import funcion_no_disponible
from components.layout import barra_lateral_usuario, nota_metodologica, preparar_pagina
from components.tables import editor_costos, tabla_simple
from database.repositories import CostRepository
from services.amazon_parser import leer_archivo
from services.auth_service import tiene_funcion
from services.export_service import exportar_csv, exportar_excel_simple, nombre_archivo_exportacion
from services.profitability_service import (
    calcular_rentabilidad,
    catalogo_vacio,
    combinar_catalogos,
    normalizar_catalogo,
    plantilla_catalogo,
)
from utils.constants import COL_SKU, COLOR_NETO
from utils.formatting import formato_moneda, formato_porcentaje
from utils.logger import get_logger, registrar_error

logger = get_logger("pagina_rentabilidad")

barra_lateral_usuario()

contexto = preparar_pagina(
    "Costos y rentabilidad",
    "Cruza tus costos de producto con lo que Amazon te deposita.",
    "💰",
)
if contexto is None:
    st.stop()

df, sesion, metricas = contexto.df, contexto.sesion, contexto.metricas

if not tiene_funcion(sesion, "rentabilidad"):
    funcion_no_disponible("El análisis de costos y rentabilidad")
    st.stop()

st.info(
    "El reporte de transacciones de Amazon **no** incluye el costo de compra de tus "
    "productos. Captúralo aquí para convertir el «neto después de tarifas» en utilidad real."
)

# =============================================================================
# Catálogo de costos
# =============================================================================

CLAVE_CATALOGO = "catalogo_costos"

if CLAVE_CATALOGO not in st.session_state:
    try:
        st.session_state[CLAVE_CATALOGO] = CostRepository.cargar(sesion.organization_id)
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "carga del catálogo de costos")
        st.session_state[CLAVE_CATALOGO] = catalogo_vacio()

catalogo: pd.DataFrame = st.session_state[CLAVE_CATALOGO]

with st.expander("Capturar o actualizar costos", expanded=catalogo.empty):
    tab_manual, tab_archivo = st.tabs(["Capturar en la tabla", "Subir catálogo"])

    with tab_manual:
        st.caption(
            "Agrega o edita renglones directamente. El SKU debe coincidir exactamente "
            "con el del reporte de Amazon."
        )

        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("Precargar los SKU del periodo", width="stretch"):
                skus_periodo = sorted(
                    df.loc[df[COL_SKU].astype("string").ne("Sin SKU"), COL_SKU]
                    .astype(str).unique().tolist()
                )
                nuevos = plantilla_catalogo(
                    [s for s in skus_periodo if s not in set(catalogo["sku"].astype(str))]
                )
                st.session_state[CLAVE_CATALOGO] = combinar_catalogos(catalogo, nuevos)
                st.rerun()

        editado = editor_costos(
            st.session_state[CLAVE_CATALOGO], clave="editor_catalogo_costos"
        )

        col_guardar, col_descargar = st.columns(2)
        with col_guardar:
            if st.button("Guardar costos", type="primary", width="stretch"):
                try:
                    limpio = normalizar_catalogo(editado)
                    guardados = CostRepository.guardar(
                        sesion.organization_id, sesion.user_id, limpio
                    )
                    st.session_state[CLAVE_CATALOGO] = limpio
                    st.success(f"Se guardaron los costos de {guardados} SKU.")
                    st.rerun()
                except Exception as error:  # noqa: BLE001
                    id_error = registrar_error(logger, error, "guardado del catálogo de costos")
                    st.error(f"No fue posible guardar los costos. Referencia: {id_error}.")
        with col_descargar:
            st.download_button(
                "Descargar catálogo (CSV)",
                data=exportar_csv(st.session_state[CLAVE_CATALOGO]),
                file_name=nombre_archivo_exportacion("catalogo_costos", "csv"),
                mime="text/csv",
                width="stretch",
            )

    with tab_archivo:
        st.caption(
            "Sube un CSV o Excel con las columnas: `sku`, `costo_unitario`, "
            "`costo_logistico_adicional`, `gasto_publicitario`, `marca`, `categoria`. "
            "Solo `sku` y `costo_unitario` son indispensables."
        )
        archivo_costos = st.file_uploader(
            "Catálogo de costos",
            type=["csv", "xlsx", "xls"],
            key="cargador_costos",
        )
        if archivo_costos is not None and st.button("Importar catálogo", width="stretch"):
            try:
                bruto = pd.read_csv(archivo_costos) if archivo_costos.name.lower().endswith(".csv") \
                    else pd.read_excel(archivo_costos)
                nuevo = normalizar_catalogo(bruto)
                combinado = combinar_catalogos(st.session_state[CLAVE_CATALOGO], nuevo)
                CostRepository.guardar(sesion.organization_id, sesion.user_id, combinado)
                st.session_state[CLAVE_CATALOGO] = combinado
                st.success(f"Se importaron {len(nuevo)} SKU con costo.")
                st.rerun()
            except Exception as error:  # noqa: BLE001
                id_error = registrar_error(logger, error, "importación del catálogo de costos")
                st.error(
                    "No fue posible leer el catálogo. Revisa que tenga una columna «sku» "
                    f"y una columna de costo. Referencia: {id_error}."
                )

# --- Gasto publicitario global ----------------------------------------------
col_pub, col_info = st.columns([1, 3])
with col_pub:
    gasto_publicitario = st.number_input(
        "Gasto publicitario del periodo",
        min_value=0.0, value=0.0, step=100.0, format="%.2f",
        key="gasto_publicitario_global",
        help=(
            "Inversión total en anuncios del periodo. Si lo capturas aquí, se reparte "
            "entre los SKU proporcional a sus ventas e ignora el gasto por SKU del catálogo."
        ),
    )
with col_info:
    st.caption(
        "El reporte de transacciones no incluye el gasto en publicidad. "
        "Tómalo del informe de campañas de Amazon Ads y captúralo aquí para calcular "
        "ACOS y TACOS."
    )

st.markdown("---")

# =============================================================================
# Resultados
# =============================================================================

resultado = calcular_rentabilidad(
    df, st.session_state[CLAVE_CATALOGO], gasto_publicitario
)

if not resultado.hay_costos:
    st.warning(
        "Todavía no hay costos capturados, así que no es posible calcular la utilidad. "
        "Mientras tanto, el indicador disponible es el **neto después de tarifas Amazon**: "
        f"{formato_moneda(metricas.get('neto'))} "
        f"({formato_porcentaje(metricas.get('margen_neto'))} de la venta bruta)."
    )
    st.stop()

if resultado.cobertura < 0.95:
    st.warning(
        f"Solo el {formato_porcentaje(resultado.cobertura)} de las ventas tiene costo "
        f"capturado ({len(resultado.skus_sin_costo)} SKU sin costo). "
        "Los totales de utilidad consideran únicamente los SKU con costo."
    )

metricas_rent = resultado.metricas

col1, col2, col3, col4 = st.columns(4)
col1.metric("Costo de mercancía vendida", formato_moneda(metricas_rent["costo_mercancia"]))
col2.metric("Utilidad antes de publicidad", formato_moneda(metricas_rent["utilidad_antes_publicidad"]))
col3.metric("Utilidad después de publicidad", formato_moneda(metricas_rent["utilidad_despues_publicidad"]))
col4.metric("Margen de contribución", formato_porcentaje(metricas_rent["margen_contribucion"]))

col5, col6, col7, col8 = st.columns(4)
col5.metric("Margen bruto", formato_porcentaje(metricas_rent["margen_bruto"]))
col6.metric("ROI", formato_porcentaje(metricas_rent["roi"]))
col7.metric(
    "ACOS", formato_porcentaje(metricas_rent["acos"]),
    help="Gasto publicitario sobre las ventas de los SKU con costo capturado.",
)
col8.metric(
    "TACOS", formato_porcentaje(metricas_rent["tacos"]),
    help="Gasto publicitario sobre todas las ventas del periodo.",
)

col9, col10 = st.columns(2)
col9.metric("Utilidad por pedido", formato_moneda(metricas_rent["utilidad_por_pedido"]))
col10.metric("Utilidad por unidad", formato_moneda(metricas_rent["utilidad_por_unidad"]))

nota_metodologica(
    "el costo de mercancía usa las **unidades netas** (vendidas menos devueltas): la pieza "
    "que regresa vuelve al inventario, así que su costo no es del periodo."
)

st.markdown("---")

# =============================================================================
# Gráficas
# =============================================================================

con_costo = resultado.tabla.loc[resultado.tabla["tiene_costo"]].copy()

if not con_costo.empty:
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            charts.top_barras(
                con_costo, "sku", "utilidad",
                "Top 10 SKU por utilidad", "Después de tarifas, costo y publicidad",
                color=COLOR_NETO,
            ),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            charts.top_barras(
                con_costo, "sku", "roi",
                "Top 10 SKU por ROI", "Utilidad sobre la inversión en mercancía",
                es_moneda=False,
            ),
            width="stretch",
        )

    perdedores = con_costo.loc[pd.to_numeric(con_costo["utilidad"], errors="coerce") < 0]
    if not perdedores.empty:
        st.error(
            f"**{len(perdedores)} SKU generan pérdida** en el periodo: "
            + ", ".join(perdedores[COL_SKU].astype(str).head(6).tolist())
            + ". Revisa su precio de venta, su costo o su tarifa FBA."
        )

# =============================================================================
# Tabla de rentabilidad
# =============================================================================

st.markdown("### Rentabilidad por SKU")

columnas = [
    "sku", "descripcion", "marca", "categoria", "unidades", "unidades_netas",
    "ventas", "neto", "costo_unitario", "costo_logistico_adicional",
    "costo_mercancia", "publicidad", "utilidad_antes_publicidad", "utilidad",
    "utilidad_por_unidad", "margen_bruto", "margen", "roi", "acos",
]
vista = resultado.tabla[[c for c in columnas if c in resultado.tabla.columns]]
tabla_simple(vista, etiquetas={"sku": "SKU"}, columna_barra="ventas")

col_a, col_b = st.columns(2)
with col_a:
    st.download_button(
        "Descargar rentabilidad (CSV)",
        data=exportar_csv(vista),
        file_name=nombre_archivo_exportacion("rentabilidad", "csv"),
        mime="text/csv",
        width="stretch",
    )
with col_b:
    st.download_button(
        "Descargar rentabilidad (Excel)",
        data=exportar_excel_simple(vista, "Rentabilidad", "Costos y rentabilidad por SKU"),
        file_name=nombre_archivo_exportacion("rentabilidad"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

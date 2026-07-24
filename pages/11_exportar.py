"""Página de exportación: todas las descargas en un solo lugar."""

from __future__ import annotations

import streamlit as st

from components.alerts import funcion_no_disponible
from components.layout import barra_lateral_usuario, preparar_pagina
from database.repositories import CostRepository, ExportRepository
from services.alerts_service import generar_hallazgos, hallazgos_a_dataframe
from services.auth_service import tiene_funcion
from services.export_service import (
    exportar_csv,
    exportar_datos_originales,
    exportar_excel_simple,
    exportar_reporte_completo,
    nombre_archivo_exportacion,
    tabla_diccionario_metricas,
    tabla_resumen_ejecutivo,
)
from services.metrics_service import (
    detalle_pedidos,
    desglose_tarifas,
    serie_temporal,
    tabla_liquidaciones,
    tabla_por_ciudad,
    tabla_por_estado,
    tabla_por_sku,
    tabla_reembolsos,
)
from services.profitability_service import calcular_rentabilidad
from utils.formatting import formato_entero
from utils.logger import get_logger, registrar_error

logger = get_logger("pagina_exportar")

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

barra_lateral_usuario()

contexto = preparar_pagina(
    "Exportar",
    "Descarga los datos y los reportes con los filtros que tienes aplicados.",
    "⬇️",
)
if contexto is None:
    st.stop()

df, sesion, metricas, comparacion = (
    contexto.df, contexto.sesion, contexto.metricas, contexto.comparacion
)

st.caption(
    f"Todas las descargas de esta página incluyen {formato_entero(len(df))} transacciones: "
    "exactamente las que dejan pasar tus filtros."
)


def _registrar(tipo: str, formato: str, nombre: str, filas: int) -> None:
    """Deja constancia de la descarga en el historial de la cuenta."""
    try:
        ExportRepository.registrar(
            sesion.user_id, sesion.organization_id, tipo, formato, nombre, filas
        )
    except Exception as error:  # noqa: BLE001 - el historial no debe bloquear la descarga
        registrar_error(logger, error, "registro de exportación")


# =============================================================================
# Reporte completo
# =============================================================================

st.markdown("### Reporte completo en Excel")
st.markdown(
    "Un solo libro con **doce hojas**: Resumen · Comparación · Ventas por día · "
    "Productos · Pedidos · Reembolsos · Tarifas · Estados · Ciudades · Liquidaciones · "
    "Tipos de transacción · Datos procesados · Alertas · Diccionario de métricas."
)

with st.container(border=True):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        frecuencia = st.selectbox(
            "Agrupación de la hoja temporal", ["Día", "Semana", "Mes"], key="freq_export"
        )
    with col_b:
        incluir_datos = st.checkbox(
            "Incluir la hoja de datos procesados", value=True,
            help="Puede hacer el archivo más pesado si cargaste muchos registros.",
        )
    with col_c:
        incluir_rentabilidad = st.checkbox(
            "Incluir la hoja de rentabilidad",
            value=tiene_funcion(sesion, "rentabilidad"),
            disabled=not tiene_funcion(sesion, "rentabilidad"),
        )

    if st.button("Generar reporte completo", type="primary", width="stretch"):
        with st.spinner("Armando el libro de Excel…"):
            try:
                hallazgos = generar_hallazgos(df, metricas, comparacion)

                rentabilidad = None
                if incluir_rentabilidad:
                    catalogo = st.session_state.get("catalogo_costos")
                    if catalogo is None:
                        catalogo = CostRepository.cargar(sesion.organization_id)
                    resultado_rent = calcular_rentabilidad(df, catalogo)
                    if resultado_rent.hay_costos:
                        rentabilidad = resultado_rent.tabla

                contenido = exportar_reporte_completo(
                    df,
                    metricas=metricas,
                    comparacion=comparacion,
                    hallazgos=hallazgos,
                    rentabilidad=rentabilidad,
                    frecuencia=frecuencia,
                    incluir_datos=incluir_datos,
                )
                nombre = nombre_archivo_exportacion("reporte_amazon_completo")
                st.session_state["_reporte_completo"] = (nombre, contenido)
                _registrar("Reporte completo", "xlsx", nombre, len(df))
            except Exception as error:  # noqa: BLE001
                id_error = registrar_error(logger, error, "generación del reporte completo")
                st.error(f"No fue posible generar el reporte. Referencia: {id_error}.")

    if "_reporte_completo" in st.session_state:
        nombre, contenido = st.session_state["_reporte_completo"]
        st.download_button(
            f"Descargar {nombre}",
            data=contenido,
            file_name=nombre,
            mime=MIME_EXCEL,
            width="stretch",
        )

st.markdown("---")

# =============================================================================
# Descargas individuales
# =============================================================================

st.markdown("### Descargas individuales")

avanzada = tiene_funcion(sesion, "exportacion_avanzada")
if not avanzada:
    funcion_no_disponible("La exportación avanzada por reporte")

tab_datos, tab_reportes, tab_referencia = st.tabs(
    ["Datos", "Reportes de análisis", "Referencia"]
)

# --- Datos -------------------------------------------------------------------
with tab_datos:
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.markdown("**Datos filtrados**")
        st.caption("Lo que ves en el tablero, con los encabezados legibles.")
        st.download_button(
            "CSV", data=exportar_csv(df),
            file_name=nombre_archivo_exportacion("datos_filtrados", "csv"),
            mime="text/csv", width="stretch", key="dl_filtrados_csv",
        )
        st.download_button(
            "Excel", data=exportar_excel_simple(df, "Datos", "Datos filtrados"),
            file_name=nombre_archivo_exportacion("datos_filtrados"),
            mime=MIME_EXCEL, width="stretch", key="dl_filtrados_xlsx",
        )

    with col_b:
        st.markdown("**Datos limpios completos**")
        st.caption("Todo lo cargado, ya normalizado, sin aplicar filtros.")
        st.download_button(
            "CSV", data=exportar_csv(contexto.df_completo),
            file_name=nombre_archivo_exportacion("datos_limpios", "csv"),
            mime="text/csv", width="stretch", key="dl_limpios_csv",
        )

    with col_c:
        st.markdown("**Encabezados originales**")
        st.caption("Los mismos datos con los nombres de columna de Amazon.")
        st.download_button(
            "Excel", data=exportar_datos_originales(df),
            file_name=nombre_archivo_exportacion("datos_originales"),
            mime=MIME_EXCEL, width="stretch", key="dl_originales",
        )
        st.download_button(
            "CSV", data=exportar_csv(df, usar_encabezados_originales=True),
            file_name=nombre_archivo_exportacion("datos_originales", "csv"),
            mime="text/csv", width="stretch", key="dl_originales_csv",
        )

# --- Reportes ----------------------------------------------------------------
with tab_reportes:
    reportes = [
        ("Resumen ejecutivo", "resumen_ejecutivo",
         lambda: tabla_resumen_ejecutivo(metricas, comparacion)),
        ("Ventas por día", "ventas_por_dia", lambda: serie_temporal(df, "Día")),
        ("Reporte por SKU", "reporte_sku", lambda: tabla_por_sku(df)),
        ("Reporte por pedido", "reporte_pedidos", lambda: detalle_pedidos(df)),
        ("Reporte por estado", "reporte_estados", lambda: tabla_por_estado(df)),
        ("Reporte por ciudad", "reporte_ciudades", lambda: tabla_por_ciudad(df)),
        ("Reporte de tarifas", "reporte_tarifas", lambda: desglose_tarifas(metricas)),
        ("Reporte de reembolsos", "reporte_reembolsos", lambda: tabla_reembolsos(df)),
        ("Reporte de liquidaciones", "reporte_liquidaciones", lambda: tabla_liquidaciones(df)),
        ("Hallazgos", "hallazgos",
         lambda: hallazgos_a_dataframe(generar_hallazgos(df, metricas, comparacion))),
    ]

    if not avanzada:
        # En el plan gratuito solo se ofrecen los dos reportes básicos.
        reportes = reportes[:2]

    columnas = st.columns(2)
    for indice, (titulo, prefijo, generador) in enumerate(reportes):
        with columnas[indice % 2]:
            with st.container(border=True):
                st.markdown(f"**{titulo}**")
                try:
                    tabla = generador()
                except Exception as error:  # noqa: BLE001
                    id_error = registrar_error(logger, error, f"generación de «{titulo}»")
                    st.caption(f"No disponible (referencia {id_error}).")
                    continue

                if tabla is None or tabla.empty:
                    st.caption("Sin datos en el periodo seleccionado.")
                    continue

                st.caption(f"{formato_entero(len(tabla))} renglones")
                col_x, col_y = st.columns(2)
                with col_x:
                    st.download_button(
                        "CSV", data=exportar_csv(tabla),
                        file_name=nombre_archivo_exportacion(prefijo, "csv"),
                        mime="text/csv", width="stretch",
                        key=f"dl_{prefijo}_csv",
                    )
                with col_y:
                    st.download_button(
                        "Excel",
                        data=exportar_excel_simple(tabla, titulo[:31], titulo),
                        file_name=nombre_archivo_exportacion(prefijo),
                        mime=MIME_EXCEL, width="stretch",
                        key=f"dl_{prefijo}_xlsx",
                    )

# --- Referencia --------------------------------------------------------------
with tab_referencia:
    st.markdown("**Diccionario de métricas**")
    st.caption(
        "Qué significa cada indicador y con qué fórmula se calcula. "
        "Se incluye también como hoja en el reporte completo."
    )
    diccionario = tabla_diccionario_metricas()
    st.dataframe(diccionario, width="stretch", hide_index=True)
    st.download_button(
        "Descargar diccionario (Excel)",
        data=exportar_excel_simple(diccionario, "Diccionario", "Diccionario de métricas"),
        file_name=nombre_archivo_exportacion("diccionario_metricas"),
        mime=MIME_EXCEL, width="stretch",
    )

st.markdown("---")

# =============================================================================
# Historial de descargas
# =============================================================================

with st.expander("Historial de descargas", expanded=False):
    try:
        historial = ExportRepository.listar(sesion.organization_id, limite=30)
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "consulta del historial de exportaciones")
        historial = None

    if historial is not None and not historial.empty:
        st.dataframe(historial, width="stretch", hide_index=True)
    else:
        st.caption("Todavía no has generado reportes completos.")

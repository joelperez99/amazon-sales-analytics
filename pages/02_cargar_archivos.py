"""Página de carga: subir, validar, relacionar columnas y previsualizar."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.alerts import mostrar_validacion
from components.layout import barra_lateral_usuario, encabezado
from services.amazon_parser import leer_archivo, sugerir_columna
from services.auth_service import sesion_actual
from services.file_service import (
    CLAVE_EXCLUIR_DUPLICADOS,
    cargar_datos_demo,
    cargar_historico,
    guardar_datos_en_sesion,
    hay_datos,
    limpiar_datos_sesion,
    obtener_datos,
    procesar_archivos,
)
from utils.config import get_settings
from utils.constants import (
    ALIAS_COLUMNAS,
    COL_ES_DUPLICADO,
    ETIQUETAS_COLUMNAS,
    ORDEN_COLUMNAS,
)
from utils.formatting import formato_entero, formato_fecha
from utils.logger import get_logger

logger = get_logger("pagina_carga")
settings = get_settings()

barra_lateral_usuario()
sesion = sesion_actual()
if sesion is None:
    st.stop()

encabezado(
    "Cargar archivos",
    "Sube uno o varios reportes de transacciones de Amazon en CSV o Excel.",
    "📤",
)

# =============================================================================
# Carga
# =============================================================================

with st.container(border=True):
    archivos = st.file_uploader(
        "Arrastra aquí tus archivos o haz clic para seleccionarlos",
        type=[e.lstrip(".") for e in settings.allowed_extensions],
        accept_multiple_files=True,
        key="cargador_archivos",
        help=(
            f"Formatos aceptados: {', '.join(settings.allowed_extensions)}. "
            f"Tamaño máximo por archivo: {settings.max_file_size_mb} MB. "
            "Puedes subir varios periodos a la vez: se concatenan automáticamente."
        ),
    )

    col_opc1, col_opc2, col_opc3 = st.columns([2, 2, 2])
    with col_opc1:
        reemplazar = st.radio(
            "Al procesar",
            ["Reemplazar los datos actuales", "Agregar a los datos actuales"],
            index=0,
            key="modo_carga",
            help="«Agregar» concatena los nuevos reportes con lo que ya está en el tablero.",
        ) == "Reemplazar los datos actuales"
    with col_opc2:
        guardar_bd = st.checkbox(
            "Guardar en mi histórico",
            value=True,
            help=(
                "Conserva las transacciones en tu cuenta para consultarlas después "
                "sin volver a subir el archivo."
            ),
        )
    with col_opc3:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        procesar = st.button(
            "Procesar archivos",
            type="primary",
            width="stretch",
            disabled=not archivos,
        )

# --- Asistente de relación manual de columnas --------------------------------
mapeo_manual: dict[str, dict[str, str]] = st.session_state.get("mapeo_manual", {})

if archivos:
    with st.expander("Relacionar columnas manualmente (opcional)", expanded=False):
        st.caption(
            "Úsalo solo si tu archivo tiene encabezados distintos a los del reporte "
            "estándar de Amazon. La aplicación ya reconoce mayúsculas, acentos y "
            "espacios adicionales por su cuenta."
        )
        for archivo in archivos:
            try:
                archivo.seek(0)
                previa = leer_archivo(archivo.read(), archivo.name)
                archivo.seek(0)
            except Exception:  # noqa: BLE001 - la vista previa no debe romper la página
                continue

            if not previa.columnas_sin_reconocer:
                st.success(f"«{archivo.name}»: todas las columnas se reconocieron.")
                continue

            st.markdown(f"**{archivo.name}**")
            asignaciones = mapeo_manual.get(archivo.name, {})
            opciones = ["(ignorar)"] + list(ALIAS_COLUMNAS.keys())

            for encabezado_original in previa.columnas_sin_reconocer[:20]:
                sugerencias = sugerir_columna(encabezado_original)
                seleccion_previa = asignaciones.get(encabezado_original)
                indice = (
                    opciones.index(seleccion_previa)
                    if seleccion_previa in opciones
                    else 0
                )
                eleccion = st.selectbox(
                    f"«{encabezado_original}» corresponde a",
                    opciones,
                    index=indice,
                    format_func=lambda c: (
                        "(ignorar)" if c == "(ignorar)" else ETIQUETAS_COLUMNAS.get(c, c)
                    ),
                    key=f"map_{archivo.name}_{encabezado_original}",
                    help="Sugerencias: " + ", ".join(
                        ETIQUETAS_COLUMNAS.get(s, s) for s in sugerencias
                    ),
                )
                if eleccion != "(ignorar)":
                    asignaciones[encabezado_original] = eleccion
                else:
                    asignaciones.pop(encabezado_original, None)

            mapeo_manual[archivo.name] = asignaciones
        st.session_state["mapeo_manual"] = mapeo_manual

# --- Procesamiento -----------------------------------------------------------
if procesar and archivos:
    barra = st.progress(0.0, text="Iniciando…")
    with st.spinner("Leyendo y limpiando los archivos…"):
        resultado = procesar_archivos(
            list(archivos),
            sesion,
            mapeo_manual=mapeo_manual,
            guardar_en_bd=guardar_bd,
            barra_progreso=barra,
        )
    barra.empty()

    mostrar_validacion(resultado.validacion)

    if resultado.exitoso:
        guardar_datos_en_sesion(resultado, reemplazar=reemplazar)
        st.success(
            f"Listo: {formato_entero(resultado.filas_totales)} transacciones cargadas "
            f"desde {len(resultado.archivos)} archivo(s)."
        )

        # Detalle por archivo.
        detalle = []
        for info in resultado.archivos:
            detalle.append({
                "Archivo": info["nombre"],
                "Filas": info.get("filas", 0),
                "Columnas": info.get("columnas", 0),
                "Codificación": info.get("encoding", ""),
                "Separador": repr(info.get("delimitador", "")) if info.get("delimitador") else "—",
                "Guardadas en histórico": info.get("guardadas", 0),
                "Ya existía": "Sí" if info.get("ya_existia") else "No",
            })
        st.dataframe(pd.DataFrame(detalle), width="stretch", hide_index=True)

        for info in resultado.archivos:
            if info.get("error_persistencia"):
                st.warning(
                    f"«{info['nombre']}» se analizó correctamente pero no se pudo guardar en "
                    f"tu histórico (referencia {info['error_persistencia']}). "
                    "El tablero funciona con normalidad en esta sesión."
                )

        # Reporte de limpieza.
        with st.expander("Detalle de la limpieza", expanded=False):
            for reporte in resultado.reportes:
                st.markdown(f"- {reporte.resumen()}")
                for mensaje in reporte.mensajes:
                    st.caption(f"  · {mensaje}")
                if reporte.columnas_agregadas:
                    st.caption(
                        "  · Columnas ausentes en el archivo que se crearon en cero: "
                        + ", ".join(
                            ETIQUETAS_COLUMNAS.get(c, c) for c in reporte.columnas_agregadas[:10]
                        )
                    )

st.markdown("---")

# =============================================================================
# Otras formas de traer datos
# =============================================================================

col_hist, col_demo, col_limpiar = st.columns(3)

with col_hist:
    if st.button("Cargar mi histórico guardado", width="stretch"):
        filas = cargar_historico(sesion)
        if filas:
            st.success(f"Se cargaron {formato_entero(filas)} transacciones del histórico.")
            st.rerun()
        else:
            st.warning("Todavía no hay transacciones guardadas en tu cuenta.")

with col_demo:
    if st.button("Cargar datos de ejemplo", width="stretch"):
        filas = cargar_datos_demo()
        if filas:
            st.success(f"Se cargaron {formato_entero(filas)} transacciones de ejemplo.")
            st.rerun()
        else:
            st.error("No fue posible generar los datos de ejemplo.")

with col_limpiar:
    if st.button("Vaciar el tablero", width="stretch"):
        limpiar_datos_sesion()
        st.rerun()

# =============================================================================
# Vista previa de los datos cargados
# =============================================================================

if hay_datos():
    df = obtener_datos()
    st.markdown("### Datos cargados")

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Filas", formato_entero(len(df)))
    col_b.metric("Columnas", formato_entero(len(df.columns)))
    fechas = pd.to_datetime(df["fecha_hora"], errors="coerce").dropna()
    col_c.metric("Desde", formato_fecha(fechas.min()) if not fechas.empty else "N/D")
    col_d.metric("Hasta", formato_fecha(fechas.max()) if not fechas.empty else "N/D")

    # --- Duplicados ---
    if COL_ES_DUPLICADO in df.columns:
        duplicados = int(df[COL_ES_DUPLICADO].fillna(False).astype(bool).sum())
        if duplicados:
            st.warning(
                f"Se detectaron **{formato_entero(duplicados)} posibles duplicados**: registros que "
                "comparten Id. del pedido, tipo, SKU, fecha, total e Id. de liquidación. "
                "No se eliminó ninguno automáticamente."
            )
            excluir = st.checkbox(
                "Excluir los duplicados de todo el análisis",
                value=st.session_state.get(CLAVE_EXCLUIR_DUPLICADOS, False),
                key="excluir_dup_carga",
            )
            st.session_state[CLAVE_EXCLUIR_DUPLICADOS] = excluir

            with st.expander(f"Ver los {formato_entero(duplicados)} registros marcados"):
                columnas = [
                    c for c in ("fecha_hora", "tipo", "id_pedido", "sku", "total", "id_liquidacion")
                    if c in df.columns
                ]
                st.dataframe(
                    df.loc[df[COL_ES_DUPLICADO].fillna(False).astype(bool), columnas]
                    .rename(columns=ETIQUETAS_COLUMNAS),
                    width="stretch", hide_index=True,
                )

    # --- Vista previa ---
    st.markdown("#### Vista previa")
    filas_previa = st.slider("Registros a mostrar", 5, 100, 20, step=5, key="previa_filas")
    columnas_visibles = [c for c in ORDEN_COLUMNAS if c in df.columns]
    st.dataframe(
        df[columnas_visibles].head(filas_previa).rename(columns=ETIQUETAS_COLUMNAS),
        width="stretch",
        hide_index=True,
    )

    # --- Composición por tipo ---
    from services.metrics_service import tabla_por_tipo

    st.markdown("#### Composición por tipo de transacción")
    st.caption(
        "Solo las filas de tipo «Pedido» generan ventas y unidades. Las transferencias "
        "son retiros a tu banco y se excluyen de los importes."
    )
    tipos = tabla_por_tipo(df)
    st.dataframe(
        tipos.rename(columns={
            "tipo": "Tipo", "transacciones": "Transacciones",
            "importe": "Importe", "participacion": "Participación",
        }),
        width="stretch",
        hide_index=True,
        column_config={
            "Importe": st.column_config.NumberColumn("Importe", format="$%.2f"),
            "Participación": st.column_config.NumberColumn("Participación", format="percent"),
        },
    )

    if st.button("Ir al resumen ejecutivo", type="primary", width="stretch"):
        st.switch_page("pages/03_resumen.py")

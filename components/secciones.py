"""Secciones compuestas reutilizables entre páginas.

Bloques de tablero que aparecen en más de una página se definen aquí una sola
vez, para que se vean y se calculen igual en todos lados.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from components import charts
from components.layout import nota_metodologica
from components.tables import tabla_simple
from services.export_service import exportar_excel_simple, nombre_archivo_exportacion
from services.metrics_service import tabla_por_ciudad, tabla_por_estado
from utils.constants import (
    COL_DESCRIPCION,
    COL_ESTADO,
    COL_FECHA,
    COLOR_NETO,
    COLOR_PEDIDOS,
    COLOR_UNIDADES,
    MESES_ES,
)
from utils.formatting import formato_entero, formato_moneda, formato_porcentaje, truncar


#: Meses en orden de calendario (número -> nombre).
_MES_A_NUMERO = {nombre: numero for numero, nombre in MESES_ES.items()}

TODOS = "Todos"


def barra_filtros_ventas(
    df_completo: pd.DataFrame,
    *,
    con_comparacion: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any], Any]:
    """Barra de filtros tipo «slicer» para la página de Ventas.

    Dibuja cuatro filtros con aspecto de tarjeta (Año, Mes en botones, Estado y
    Producto) y aplica la selección sobre todos los datos cargados.

    Returns:
        ``(df_filtrado, metricas, comparacion)`` listos para alimentar la página.
    """
    from components.filters import EstadoFiltros, aplicar_filtros
    from services.comparison_service import Comparacion, comparar_periodos
    from services.metrics_service import calcular_metricas

    _inyectar_estilos_filtros()

    fechas = pd.to_datetime(df_completo[COL_FECHA], errors="coerce")
    anios = sorted(fechas.dt.year.dropna().astype(int).unique().tolist())

    if not anios:
        st.info("Los datos cargados no tienen fechas válidas para filtrar por año y mes.")
        metricas = calcular_metricas(df_completo)
        return df_completo, metricas, Comparacion(metricas_actual=metricas)

    st.markdown('<div class="filtros-ventas">', unsafe_allow_html=True)

    fila1 = st.columns([1, 3], gap="small")

    # --- Año -----------------------------------------------------------------
    with fila1[0]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Año</div>', unsafe_allow_html=True)
            anio = st.selectbox(
                "Año", anios, index=len(anios) - 1,
                label_visibility="collapsed", key="vt_anio",
            )

    # Meses disponibles para el año elegido, en orden de calendario.
    del_anio = fechas.dt.year == anio
    meses_num = sorted(fechas[del_anio].dt.month.dropna().astype(int).unique().tolist())
    meses_nombres = [MESES_ES[m] for m in meses_num]

    # --- Mes -----------------------------------------------------------------
    with fila1[1]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Mes</div>', unsafe_allow_html=True)
            mes = st.segmented_control(
                "Mes", [TODOS] + meses_nombres, default=TODOS,
                label_visibility="collapsed", key="vt_mes",
            )

    fila2 = st.columns([1, 2], gap="small")

    # --- Estado --------------------------------------------------------------
    estados = _valores(df_completo, COL_ESTADO)
    with fila2[0]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Estado</div>', unsafe_allow_html=True)
            estado = st.selectbox(
                "Estado", [TODOS] + estados,
                label_visibility="collapsed", key="vt_estado",
            )

    # --- Producto ------------------------------------------------------------
    productos = _valores(df_completo, COL_DESCRIPCION)
    with fila2[1]:
        with st.container(border=True):
            st.markdown('<div class="filtro-titulo">Producto</div>', unsafe_allow_html=True)
            producto = st.selectbox(
                "Producto", [TODOS] + productos,
                format_func=lambda v: v if v == TODOS else truncar(v, 70),
                label_visibility="collapsed", key="vt_producto",
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # --- Rango de fechas a partir de Año / Mes -------------------------------
    if mes and mes != TODOS:
        numero_mes = _MES_A_NUMERO[mes]
        inicio = date(anio, numero_mes, 1)
        fin = (pd.Timestamp(anio, numero_mes, 1) + pd.offsets.MonthEnd(0)).date()
    else:
        inicio, fin = date(anio, 1, 1), date(anio, 12, 31)

    estados_sel = [estado] if estado != TODOS else []
    productos_sel = [producto] if producto != TODOS else []

    filtros = EstadoFiltros(
        fecha_inicio=inicio, fecha_fin=fin,
        estados=estados_sel, productos=productos_sel,
    )
    df_filtrado = aplicar_filtros(df_completo, filtros)
    metricas = calcular_metricas(df_filtrado)

    # --- Comparación contra el periodo anterior equivalente ------------------
    if con_comparacion:
        base = aplicar_filtros(
            df_completo,
            EstadoFiltros(estados=estados_sel, productos=productos_sel),
        )
        comparacion = comparar_periodos(base, inicio, fin, "Periodo anterior equivalente")
    else:
        comparacion = Comparacion(metricas_actual=metricas, rango_actual=(inicio, fin))

    # --- Resumen de la selección --------------------------------------------
    partes = [f"{formato_entero(len(df_filtrado))} transacciones"]
    partes.append(f"{inicio:%d/%m/%Y} – {fin:%d/%m/%Y}")
    if estado != TODOS:
        partes.append(f"estado: {estado}")
    if producto != TODOS:
        partes.append(f"producto: {truncar(producto, 40)}")
    st.caption(" · ".join(partes))

    return df_filtrado, metricas, comparacion


def _valores(df: pd.DataFrame, columna: str) -> list[str]:
    """Valores distintos de una columna, ordenados, sin vacíos ni marcadores."""
    if df.empty or columna not in df.columns:
        return []
    serie = df[columna].astype("string").dropna()
    serie = serie[serie.str.strip().ne("") & ~serie.isin(["Sin estado", "Sin descripción"])]
    return sorted(serie.unique().tolist())


def _inyectar_estilos_filtros() -> None:
    """Estilo de la barra de filtros para que parezca un panel de «slicers»."""
    from utils.constants import COLOR_TINTA_SECUNDARIA, FUENTE_UI

    st.markdown(
        f"""
        <style>
        .filtro-titulo {{
            font-family: {FUENTE_UI};
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .04em;
            color: {COLOR_TINTA_SECUNDARIA};
            margin-bottom: 6px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def seccion_geografia(
    df: pd.DataFrame,
    *,
    incluir_tabla_detalle: bool = True,
    incluir_descargas: bool = True,
    grafico_secundario: str = "neto",
    prefijo: str = "geo",
) -> None:
    """Dibuja la distribución geográfica: resumen, mapa y rankings por estado.

    Args:
        df: datos ya filtrados del periodo.
        incluir_tabla_detalle: si se muestra la tabla geográfica completa por estado.
        incluir_descargas: si se muestran los botones de descarga a Excel.
        grafico_secundario: qué mostrar a la derecha del primer tab. ``"neto"``
            pone «Top 10 estados por neto»; ``"ciudades"`` pone «Top 10 ciudades
            por ventas».
        prefijo: prefijo para las claves de los widgets, para poder usar la
            sección más de una vez en distintas páginas sin colisiones.
    """
    estados = tabla_por_estado(df)
    ciudades = tabla_por_ciudad(df)

    if estados.empty:
        st.info(
            "El reporte no trae información de estado. Verifica que el archivo incluya "
            "la columna «estado del pedido»."
        )
        return

    # --- Resumen -------------------------------------------------------------
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

    st.markdown("")

    # --- Mapa ----------------------------------------------------------------
    mapa = charts.mapa_mexico(estados, "ventas")
    if mapa is not None:
        st.plotly_chart(mapa, width="stretch", key=f"{prefijo}_mapa")
        st.caption(
            "El color codifica el importe vendido: entre más oscuro, mayor venta. "
            "Los estados sin registros aparecen sin color."
        )
    else:
        st.info(
            "El mapa de México necesita descargar su contorno geográfico y no hubo conexión. "
            "Abajo tienes la misma información en barras."
        )

    # --- Rankings ------------------------------------------------------------
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
                key=f"{prefijo}_estados_ventas",
            )
        with col_b:
            if grafico_secundario == "ciudades":
                figura_secundaria = charts.top_barras(
                    ciudades, "ciudad", "ventas",
                    "Top 10 ciudades por ventas", "Ventas brutas del periodo",
                )
            else:
                figura_secundaria = charts.top_barras(
                    estados, "estado", "neto",
                    "Top 10 estados por neto", "Depósito después de tarifas",
                    color=COLOR_NETO,
                )
            st.plotly_chart(figura_secundaria, width="stretch", key=f"{prefijo}_secundario")

    with tab_operacion:
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(
                charts.top_barras(
                    estados, "estado", "pedidos",
                    "Top 10 estados por pedidos", color=COLOR_PEDIDOS, es_moneda=False,
                ),
                width="stretch",
                key=f"{prefijo}_estados_pedidos",
            )
        with col_b:
            st.plotly_chart(
                charts.top_barras(
                    estados, "estado", "unidades",
                    "Top 10 estados por unidades", color=COLOR_UNIDADES, es_moneda=False,
                ),
                width="stretch",
                key=f"{prefijo}_estados_unidades",
            )

    with tab_ciudades:
        st.plotly_chart(
            charts.top_barras(
                ciudades, "ciudad", "ventas",
                "Top 10 ciudades por ventas", "Ventas brutas del periodo",
            ),
            width="stretch",
            key=f"{prefijo}_ciudades_ventas",
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

    # --- Tabla geográfica completa (opcional) --------------------------------
    if incluir_tabla_detalle:
        st.markdown("---")
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
    else:
        vista_estados = estados

    # --- Descargas (opcional) ------------------------------------------------
    if incluir_descargas:
        col_a, col_b = st.columns(2)
        with col_a:
            st.download_button(
                "Descargar reporte por estado (Excel)",
                data=exportar_excel_simple(vista_estados, "Estados", "Ventas por estado"),
                file_name=nombre_archivo_exportacion("reporte_estados"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key=f"{prefijo}_dl_estados",
            )
        with col_b:
            st.download_button(
                "Descargar reporte por ciudad (Excel)",
                data=exportar_excel_simple(ciudades, "Ciudades", "Ventas por ciudad"),
                file_name=nombre_archivo_exportacion("reporte_ciudades"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key=f"{prefijo}_dl_ciudades",
            )

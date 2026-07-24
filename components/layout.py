"""Andamiaje común de las páginas del tablero.

Cada página analítica repite el mismo preámbulo: comprobar la sesión, recuperar
los datos, dibujar los filtros, calcular la comparación y las métricas.  Todo eso
vive aquí para que las páginas se concentren en lo que muestran.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from components.alerts import pagina_sin_datos
from components.filters import EstadoFiltros, aplicar_filtros, render_filtros, resumen_filtros
from services.auth_service import Sesion, sesion_actual, tiene_funcion
from services.comparison_service import Comparacion, comparar_periodos
from services.file_service import hay_datos, obtener_datos
from utils.constants import COLOR_TINTA, COLOR_TINTA_TENUE, FUENTE_UI
from utils.logger import get_logger

logger = get_logger("layout")


@dataclass
class ContextoPagina:
    """Todo lo que una página necesita para dibujarse."""

    sesion: Sesion
    df_completo: pd.DataFrame
    df: pd.DataFrame
    filtros: EstadoFiltros
    comparacion: Comparacion
    metricas: dict[str, Any]

    @property
    def hay_datos(self) -> bool:
        return not self.df.empty


def encabezado(titulo: str, descripcion: str = "", icono: str = "") -> None:
    """Título de página con una línea de contexto."""
    st.markdown(
        f"""
        <div style="margin-bottom:6px">
            <div style="font-family:{FUENTE_UI};font-size:26px;font-weight:600;color:{COLOR_TINTA}">
                {icono + ' ' if icono else ''}{titulo}
            </div>
            {f'<div style="font-family:{FUENTE_UI};font-size:13.5px;color:{COLOR_TINTA_TENUE};margin-top:2px">{descripcion}</div>' if descripcion else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("")


def preparar_pagina(
    titulo: str,
    descripcion: str = "",
    icono: str = "",
    con_filtros: bool = True,
    requiere_datos: bool = True,
) -> ContextoPagina | None:
    """Prepara una página analítica.

    Returns:
        El contexto listo para usar, o ``None`` si no hay sesión o no hay datos
        (en cuyo caso ya se mostró el mensaje correspondiente).
    """
    sesion = sesion_actual()
    if sesion is None:
        st.warning("Tu sesión terminó. Vuelve a iniciar sesión para continuar.")
        st.stop()

    encabezado(titulo, descripcion, icono)

    if requiere_datos and not hay_datos():
        pagina_sin_datos()
        return None

    df_completo = obtener_datos()

    if not con_filtros:
        return ContextoPagina(
            sesion=sesion,
            df_completo=df_completo,
            df=df_completo,
            filtros=EstadoFiltros(),
            comparacion=Comparacion(),
            metricas={},
        )

    puede_comparar = tiene_funcion(sesion, "comparacion_periodos")
    filtros = render_filtros(df_completo, mostrar_comparacion=puede_comparar)
    df_filtrado = aplicar_filtros(df_completo, filtros)

    # La comparación se calcula sobre el conjunto completo con los mismos filtros
    # de dimensión, pero con el rango de fechas del periodo anterior.
    modo = filtros.modo_comparacion if puede_comparar else "Sin comparación"
    filtros_sin_fecha = EstadoFiltros(**{**filtros.__dict__, "fecha_inicio": None, "fecha_fin": None})
    base_comparacion = aplicar_filtros(df_completo, filtros_sin_fecha)

    comparacion = comparar_periodos(
        base_comparacion,
        filtros.fecha_inicio,
        filtros.fecha_fin,
        modo=modo,
        rango_personalizado=filtros.rango_personalizado,
    )

    st.caption(resumen_filtros(filtros, len(df_filtrado), len(df_completo)))

    if df_filtrado.empty:
        st.warning(
            "Los filtros seleccionados no dejaron ningún registro. "
            "Amplía el rango de fechas o limpia los filtros de la barra lateral."
        )

    return ContextoPagina(
        sesion=sesion,
        df_completo=df_completo,
        df=df_filtrado,
        filtros=filtros,
        comparacion=comparacion,
        metricas=comparacion.metricas_actual,
    )


def barra_lateral_usuario() -> None:
    """Bloque de identidad y cierre de sesión al pie de la barra lateral."""
    from services.auth_service import cerrar_sesion
    from utils.config import get_settings
    from utils.constants import PLANES

    sesion = sesion_actual()
    if sesion is None:
        return

    settings = get_settings()
    with st.sidebar:
        st.markdown("---")
        plan = PLANES.get(sesion.plan, PLANES["gratuito"])
        st.markdown(
            f"""
            <div style="font-family:{FUENTE_UI};font-size:12.5px;color:{COLOR_TINTA_TENUE};line-height:1.6">
                <div style="color:{COLOR_TINTA};font-weight:600;font-size:13.5px">{sesion.nombre}</div>
                <div>{sesion.email}</div>
                <div>Plan {plan['nombre']}{' · demostración' if sesion.es_demo else ''}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if settings.auth_enabled and st.button("Cerrar sesión", width="stretch"):
            cerrar_sesion()
            st.rerun()


def selector_frecuencia(clave: str = "frecuencia", etiqueta: str = "Agrupar por") -> str:
    """Selector Día / Semana / Mes usado por las gráficas temporales."""
    return st.radio(
        etiqueta, ["Día", "Semana", "Mes"], horizontal=True,
        key=clave, label_visibility="visible",
    )


def boton_descarga_filtrados(df: pd.DataFrame, prefijo: str = "datos_filtrados") -> None:
    """Botón para descargar exactamente lo que está viendo el usuario."""
    from services.export_service import exportar_csv, nombre_archivo_exportacion

    if df.empty:
        return
    st.download_button(
        "Descargar datos filtrados (CSV)",
        data=exportar_csv(df),
        file_name=nombre_archivo_exportacion(prefijo, "csv"),
        mime="text/csv",
        width="stretch",
    )


def nota_metodologica(texto: str) -> None:
    """Nota al pie que explica un criterio de cálculo."""
    st.caption(f"Nota: {texto}")

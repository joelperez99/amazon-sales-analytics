"""Presentación de los hallazgos y de los mensajes de la aplicación.

Los hallazgos nunca se distinguen solo por color: cada uno lleva un icono y una
etiqueta de severidad, de modo que se entienden también en escala de grises o
con daltonismo.
"""

from __future__ import annotations

import streamlit as st

from services.alerts_service import (
    SEVERIDAD_ADVERTENCIA,
    SEVERIDAD_CRITICO,
    SEVERIDAD_INFORMATIVO,
    Hallazgo,
)
from utils.constants import (
    COLOR_ADVERTENCIA,
    COLOR_CRITICO,
    COLOR_SUPERFICIE,
    COLOR_TINTA,
    COLOR_TINTA_SECUNDARIA,
    COLOR_TINTA_TENUE,
    COLOR_VENTAS,
    FUENTE_UI,
)

#: Icono, color y etiqueta de cada severidad.
_ESTILO_SEVERIDAD: dict[str, tuple[str, str, str]] = {
    SEVERIDAD_CRITICO: ("⛔", COLOR_CRITICO, "Crítico"),
    SEVERIDAD_ADVERTENCIA: ("⚠️", COLOR_ADVERTENCIA, "Advertencia"),
    SEVERIDAD_INFORMATIVO: ("ℹ️", COLOR_VENTAS, "Informativo"),
}


def _inyectar_estilos() -> None:
    if st.session_state.get("_estilos_hallazgos"):
        return
    st.session_state["_estilos_hallazgos"] = True
    st.markdown(
        f"""
        <style>
        .hallazgo {{
            background: {COLOR_SUPERFICIE};
            border: 1px solid rgba(11,11,11,0.10);
            border-left-width: 4px;
            border-radius: 10px;
            padding: 13px 16px;
            margin-bottom: 10px;
            font-family: {FUENTE_UI};
        }}
        .hallazgo .cabecera {{
            display: flex; align-items: center; gap: 8px;
            font-size: 14px; font-weight: 600; color: {COLOR_TINTA};
            margin-bottom: 4px;
        }}
        .hallazgo .etiqueta-severidad {{
            font-size: 11px; font-weight: 600; text-transform: uppercase;
            letter-spacing: .04em; padding: 2px 7px; border-radius: 5px;
        }}
        .hallazgo .cuerpo {{
            font-size: 13.5px; color: {COLOR_TINTA_SECUNDARIA}; line-height: 1.5;
        }}
        .hallazgo .recomendacion {{
            font-size: 12.5px; color: {COLOR_TINTA_TENUE};
            margin-top: 6px; font-style: italic;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _escapar(texto: str) -> str:
    return (
        str(texto)
        .replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def tarjeta_hallazgo(hallazgo: Hallazgo) -> None:
    """Pinta un hallazgo individual."""
    _inyectar_estilos()
    icono, color, etiqueta = _ESTILO_SEVERIDAD.get(
        hallazgo.severidad, _ESTILO_SEVERIDAD[SEVERIDAD_INFORMATIVO]
    )

    recomendacion = (
        f'<div class="recomendacion">Qué hacer: {_escapar(hallazgo.recomendacion)}</div>'
        if hallazgo.recomendacion else ""
    )

    st.markdown(
        f"""
        <div class="hallazgo" style="border-left-color:{color}">
            <div class="cabecera">
                <span>{icono}</span>
                <span>{_escapar(hallazgo.titulo)}</span>
                <span class="etiqueta-severidad" style="background:{color}1a;color:{color}">
                    {etiqueta}
                </span>
                <span style="font-size:11.5px;color:{COLOR_TINTA_TENUE};font-weight:400">
                    {_escapar(hallazgo.categoria)}
                </span>
            </div>
            <div class="cuerpo">{_escapar(hallazgo.mensaje)}</div>
            {recomendacion}
        </div>
        """,
        unsafe_allow_html=True,
    )


def panel_hallazgos(
    hallazgos: list[Hallazgo],
    titulo: str = "Hallazgos",
    maximo: int | None = None,
    con_filtro: bool = True,
) -> None:
    """Sección completa de hallazgos, con filtro por severidad."""
    st.subheader(titulo)

    if not hallazgos:
        st.success("No se detectaron problemas en el periodo analizado.")
        return

    conteos = {
        severidad: sum(1 for h in hallazgos if h.severidad == severidad)
        for severidad in _ESTILO_SEVERIDAD
    }

    if con_filtro:
        col_res, col_filtro = st.columns([2, 1])
        with col_res:
            resumen = " · ".join(
                f"{_ESTILO_SEVERIDAD[s][0]} {c} {_ESTILO_SEVERIDAD[s][2].lower()}"
                for s, c in conteos.items() if c
            )
            st.caption(resumen)
        with col_filtro:
            severidades = st.multiselect(
                "Severidad",
                [_ESTILO_SEVERIDAD[s][2] for s in _ESTILO_SEVERIDAD],
                default=[],
                placeholder="Todas las severidades",
                key=f"filtro_severidad_{titulo}",
                label_visibility="collapsed",
            )
        if severidades:
            inversa = {v[2]: k for k, v in _ESTILO_SEVERIDAD.items()}
            hallazgos = [h for h in hallazgos if h.severidad in {inversa[s] for s in severidades}]

    mostrados = hallazgos[:maximo] if maximo else hallazgos
    for hallazgo in mostrados:
        tarjeta_hallazgo(hallazgo)

    if maximo and len(hallazgos) > maximo:
        st.caption(f"Se muestran {maximo} de {len(hallazgos)} hallazgos.")


def resumen_hallazgos(hallazgos: list[Hallazgo]) -> None:
    """Franja compacta con el conteo por severidad, para la parte superior."""
    if not hallazgos:
        return
    criticos = sum(1 for h in hallazgos if h.severidad == SEVERIDAD_CRITICO)
    advertencias = sum(1 for h in hallazgos if h.severidad == SEVERIDAD_ADVERTENCIA)

    if criticos:
        st.error(
            f"{criticos} hallazgo{'s' if criticos > 1 else ''} crítico"
            f"{'s' if criticos > 1 else ''} y {advertencias} advertencia"
            f"{'s' if advertencias != 1 else ''}. Revisa la sección de hallazgos."
        )
    elif advertencias:
        st.warning(
            f"{advertencias} advertencia{'s' if advertencias > 1 else ''} en el periodo. "
            "Revisa la sección de hallazgos."
        )


# =============================================================================
# Mensajes de la aplicación
# =============================================================================


def mostrar_validacion(resultado: object, contexto: str = "") -> None:
    """Muestra los errores y advertencias de un ``ResultadoValidacion``."""
    errores = getattr(resultado, "errores", []) or []
    advertencias = getattr(resultado, "advertencias", []) or []

    for error in errores:
        st.error(f"{contexto + ': ' if contexto else ''}{error}")
    for advertencia in advertencias:
        st.warning(advertencia)


def pagina_sin_datos(mensaje_extra: str = "") -> None:
    """Estado vacío amigable que guía al usuario a cargar un archivo."""
    st.info(
        "Todavía no hay datos cargados.\n\n"
        "Ve a **Cargar archivos** y sube tu reporte de transacciones de Amazon "
        "(CSV o Excel). También puedes probar la aplicación con datos de ejemplo "
        "desde la página de **Inicio**."
        + (f"\n\n{mensaje_extra}" if mensaje_extra else "")
    )


def error_amigable(id_error: str, accion: str = "") -> None:
    """Mensaje de error que no expone detalles internos."""
    st.error(
        f"Ocurrió un problema{' al ' + accion if accion else ''}. "
        f"El equipo puede investigarlo con esta referencia: **{id_error}**.\n\n"
        "Intenta de nuevo; si el problema continúa, revisa que el archivo tenga "
        "el formato de un reporte de transacciones de Amazon."
    )


def funcion_no_disponible(nombre_funcion: str, plan_requerido: str = "Profesional") -> None:
    """Aviso cuando el plan del usuario no incluye una función."""
    st.warning(
        f"**{nombre_funcion}** está disponible a partir del plan {plan_requerido}. "
        "Puedes cambiar de plan desde la página de **Configuración**."
    )

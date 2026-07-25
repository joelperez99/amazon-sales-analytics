"""Página de geografía: dónde compran tus clientes."""

from __future__ import annotations

import streamlit as st

from components.layout import barra_lateral_usuario, preparar_pagina
from components.secciones import seccion_geografia

barra_lateral_usuario()

contexto = preparar_pagina(
    "Geografía",
    "Distribución de la venta por estado y por ciudad.",
    "🗺️",
)
if contexto is None:
    st.stop()

# Sección completa: resumen, mapa, rankings, tabla por estado y descargas.
seccion_geografia(
    contexto.df,
    incluir_tabla_detalle=True,
    incluir_descargas=True,
    prefijo="geografia",
)

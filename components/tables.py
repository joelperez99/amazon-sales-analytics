"""Tablas interactivas del tablero.

Se apoyan en ``st.dataframe`` con ``column_config``, que ya ofrece ordenamiento,
redimensionado, búsqueda y descarga.  Encima se agregan buscador propio,
selección de columnas visibles, paginación y barras de progreso dentro de las
celdas.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import streamlit as st

from utils.constants import (
    COL_DESCRIPCION,
    COL_PEDIDO,
    COL_SKU,
    ETIQUETAS_COLUMNAS,
)
from utils.formatting import formato_entero

#: Configuración por tipo de columna para ``st.dataframe``.
FORMATO_MONEDA = "$%,.2f"
FORMATO_PORCENTAJE = "%.1f%%"


def config_moneda(etiqueta: str, ayuda: str = "") -> st.column_config.NumberColumn:
    """Columna monetaria con formato de México."""
    return st.column_config.NumberColumn(
        etiqueta, format="$%.2f", help=ayuda or None
    )


def config_entero(etiqueta: str, ayuda: str = "") -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(etiqueta, format="%d", help=ayuda or None)


def config_porcentaje(etiqueta: str, ayuda: str = "") -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(
        etiqueta, format="percent", help=ayuda or None
    )


def config_barra(
    etiqueta: str, maximo: float, ayuda: str = "", formato: str = "$%.2f"
) -> st.column_config.ProgressColumn:
    """Columna con barra de progreso dentro de la celda."""
    return st.column_config.ProgressColumn(
        etiqueta, help=ayuda or None, format=formato,
        min_value=0.0, max_value=float(maximo) if maximo else 1.0,
    )


# =============================================================================
# Tabla de productos
# =============================================================================

#: Columnas de la tabla de SKU: (clave, etiqueta, tipo).
COLUMNAS_SKU: list[tuple[str, str, str]] = [
    (COL_SKU, "SKU", "texto"),
    ("descripcion", "Descripción", "texto"),
    ("pedidos", "Pedidos", "entero"),
    ("unidades", "Unidades", "entero"),
    ("ventas", "Ventas", "barra"),
    ("impuestos", "Impuestos", "moneda"),
    ("descuentos", "Descuentos", "moneda"),
    ("tarifas_venta", "Tarifas de venta", "moneda"),
    ("tarifas_fba", "Tarifas FBA", "moneda"),
    ("retenciones", "Retenciones", "moneda"),
    ("otros_cargos", "Otros cargos", "moneda"),
    ("reembolsos", "Reembolsos", "moneda"),
    ("neto", "Neto", "moneda"),
    ("precio_promedio", "Precio promedio", "moneda"),
    ("tarifa_por_unidad", "Tarifa por unidad", "moneda"),
    ("neto_por_unidad", "Neto por unidad", "moneda"),
    ("pct_cargos", "% de cargos", "porcentaje"),
    ("participacion", "Participación", "porcentaje"),
    ("tasa_reembolso", "Tasa de reembolso", "porcentaje"),
    ("costo_unitario", "Costo unitario", "moneda"),
    ("utilidad", "Utilidad", "moneda"),
    ("margen", "Margen", "porcentaje"),
]

#: Columnas visibles por omisión (las demás se activan desde el selector).
COLUMNAS_SKU_INICIALES = [
    COL_SKU, "descripcion", "pedidos", "unidades", "ventas",
    "tarifas_venta", "tarifas_fba", "reembolsos", "neto",
    "precio_promedio", "pct_cargos", "participacion", "tasa_reembolso",
]


def tabla_productos(
    tabla: pd.DataFrame, clave: str = "tabla_sku", filas_por_pagina: int = 25
) -> pd.DataFrame:
    """Tabla detallada por SKU con buscador, selección de columnas y paginación.

    Returns:
        El subconjunto visible (útil para exportar exactamente lo mostrado).
    """
    if tabla.empty:
        st.info("No hay productos que mostrar con los filtros actuales.")
        return tabla

    columnas_disponibles = [c for c, _, _ in COLUMNAS_SKU if c in tabla.columns]

    col_busqueda, col_columnas = st.columns([2, 3])
    with col_busqueda:
        busqueda = st.text_input(
            "Buscar", placeholder="SKU o descripción…", key=f"{clave}_busqueda",
            label_visibility="collapsed",
        )
    with col_columnas:
        visibles = st.multiselect(
            "Columnas visibles",
            columnas_disponibles,
            default=[c for c in COLUMNAS_SKU_INICIALES if c in columnas_disponibles],
            format_func=lambda c: dict((k, e) for k, e, _ in COLUMNAS_SKU).get(c, c),
            key=f"{clave}_columnas",
            label_visibility="collapsed",
            placeholder="Columnas visibles",
        )

    datos = tabla.copy()

    # --- Búsqueda ------------------------------------------------------------
    if busqueda:
        patron = busqueda.strip()
        mascara = pd.Series(False, index=datos.index)
        for columna in (COL_SKU, "descripcion"):
            if columna in datos.columns:
                mascara |= (
                    datos[columna].astype("string").str.contains(patron, case=False, na=False)
                )
        datos = datos.loc[mascara]
        if datos.empty:
            st.warning(f"Ningún producto coincide con «{patron}».")
            return datos

    if not visibles:
        visibles = [c for c in COLUMNAS_SKU_INICIALES if c in columnas_disponibles]

    datos = datos[[c for c in visibles if c in datos.columns]]

    # --- Paginación ----------------------------------------------------------
    total_paginas = max(1, math.ceil(len(datos) / filas_por_pagina))
    pagina = 1
    if total_paginas > 1:
        col_info, col_pagina = st.columns([3, 1])
        with col_info:
            st.caption(
                f"{formato_entero(len(datos))} productos · "
                f"{total_paginas} páginas de {filas_por_pagina}"
            )
        with col_pagina:
            pagina = st.number_input(
                "Página", min_value=1, max_value=total_paginas, value=1, step=1,
                key=f"{clave}_pagina", label_visibility="collapsed",
            )
    inicio = (int(pagina) - 1) * filas_por_pagina
    visible = datos.iloc[inicio: inicio + filas_por_pagina]

    st.dataframe(
        visible,
        width="stretch",
        hide_index=True,
        column_config=_config_columnas_sku(tabla, visibles),
    )
    return datos


def _config_columnas_sku(
    tabla_completa: pd.DataFrame, visibles: list[str]
) -> dict[str, Any]:
    """Construye el ``column_config`` de la tabla de productos."""
    etiquetas = {c: e for c, e, _ in COLUMNAS_SKU}
    tipos = {c: t for c, _, t in COLUMNAS_SKU}
    maximo_ventas = float(tabla_completa["ventas"].max()) if "ventas" in tabla_completa else 0.0

    config: dict[str, Any] = {}
    for columna in visibles:
        etiqueta = etiquetas.get(columna, ETIQUETAS_COLUMNAS.get(columna, columna))
        tipo = tipos.get(columna, "texto")
        if tipo == "barra":
            config[columna] = config_barra(
                etiqueta, maximo_ventas, "Barra proporcional a la venta del SKU"
            )
        elif tipo == "moneda":
            config[columna] = config_moneda(etiqueta)
        elif tipo == "entero":
            config[columna] = config_entero(etiqueta)
        elif tipo == "porcentaje":
            config[columna] = config_porcentaje(etiqueta)
        elif columna == "descripcion":
            config[columna] = st.column_config.TextColumn(etiqueta, width="large")
        else:
            config[columna] = st.column_config.TextColumn(etiqueta)
    return config


# =============================================================================
# Tabla de pedidos
# =============================================================================


def tabla_pedidos(
    detalle: pd.DataFrame, resumen: pd.DataFrame, clave: str = "tabla_pedidos"
) -> pd.DataFrame:
    """Detalle de pedidos con buscador y expansión de las líneas de cada pedido."""
    if detalle.empty:
        st.info("No hay transacciones que mostrar con los filtros actuales.")
        return detalle

    busqueda = st.text_input(
        "Buscar pedido",
        placeholder="Escribe un Id. del pedido, un SKU o parte de la descripción…",
        key=f"{clave}_busqueda",
    )

    datos = detalle
    if busqueda:
        patron = busqueda.strip()
        mascara = pd.Series(False, index=detalle.index)
        for columna in (COL_PEDIDO, COL_SKU, COL_DESCRIPCION):
            if columna in detalle.columns:
                mascara |= (
                    detalle[columna].astype("string").str.contains(patron, case=False, na=False)
                )
        datos = detalle.loc[mascara]
        if datos.empty:
            st.warning(f"Ningún pedido coincide con «{patron}».")
            return datos
        st.caption(f"{formato_entero(len(datos))} transacciones coinciden con la búsqueda.")

    st.dataframe(
        datos.head(1_000),
        width="stretch",
        hide_index=True,
        column_config=_config_columnas_detalle(datos),
    )
    if len(datos) > 1_000:
        st.caption(
            f"Se muestran las primeras 1,000 transacciones de {formato_entero(len(datos))}. "
            "Usa el buscador o descarga la tabla completa para ver el resto."
        )

    # --- Pedidos con varias líneas ------------------------------------------
    if not resumen.empty and "lineas" in resumen.columns:
        multiples = resumen.loc[resumen["lineas"] > 1]
        if not multiples.empty:
            with st.expander(
                f"Pedidos con varias líneas o SKU ({formato_entero(len(multiples))})",
                expanded=False,
            ):
                st.caption(
                    "Estos pedidos suman varias transacciones. En el conteo de «pedidos únicos» "
                    "cada uno cuenta una sola vez."
                )
                seleccion = st.selectbox(
                    "Selecciona un pedido para ver su detalle",
                    multiples[COL_PEDIDO].tolist(),
                    key=f"{clave}_expandir",
                )
                if seleccion:
                    lineas = detalle.loc[
                        detalle[COL_PEDIDO].astype("string") == str(seleccion)
                    ]
                    st.dataframe(
                        lineas, width="stretch", hide_index=True,
                        column_config=_config_columnas_detalle(lineas),
                    )
    return datos


def _config_columnas_detalle(df: pd.DataFrame) -> dict[str, Any]:
    """``column_config`` para las tablas de detalle a nivel transacción."""
    monetarias = {
        "ventas_productos", "impuestos", "tarifas_venta", "tarifas_fba",
        "retenciones_plataforma", "total", "creditos_envio", "descuentos_promocionales",
    }
    enteras = {"cantidad"}
    config: dict[str, Any] = {}
    for columna in df.columns:
        etiqueta = ETIQUETAS_COLUMNAS.get(columna, columna.replace("_", " ").capitalize())
        if columna in monetarias:
            config[columna] = config_moneda(etiqueta)
        elif columna in enteras:
            config[columna] = config_entero(etiqueta)
        elif pd.api.types.is_datetime64_any_dtype(df[columna]):
            config[columna] = st.column_config.DatetimeColumn(etiqueta, format="DD/MM/YYYY HH:mm")
        elif columna == "descripcion":
            config[columna] = st.column_config.TextColumn(etiqueta, width="large")
        else:
            config[columna] = st.column_config.TextColumn(etiqueta)
    return config


# =============================================================================
# Tabla genérica
# =============================================================================


def tabla_simple(
    df: pd.DataFrame,
    etiquetas: dict[str, str] | None = None,
    columna_barra: str | None = None,
    altura: int | None = None,
) -> None:
    """Tabla con formato automático según el nombre y el tipo de cada columna."""
    if df.empty:
        st.info("No hay datos que mostrar.")
        return

    etiquetas = etiquetas or {}
    maximo = float(df[columna_barra].max()) if columna_barra and columna_barra in df else 0.0

    config: dict[str, Any] = {}
    for columna in df.columns:
        etiqueta = etiquetas.get(
            columna, ETIQUETAS_COLUMNAS.get(columna, str(columna).replace("_", " ").capitalize())
        )
        minusculas = str(columna).lower()

        if columna == columna_barra:
            config[columna] = config_barra(etiqueta, maximo)
        elif pd.api.types.is_datetime64_any_dtype(df[columna]):
            config[columna] = st.column_config.DatetimeColumn(etiqueta, format="DD/MM/YYYY")
        elif not pd.api.types.is_numeric_dtype(df[columna]):
            config[columna] = st.column_config.TextColumn(etiqueta)
        elif any(p in minusculas for p in ("pct", "margen", "participacion", "tasa", "roi", "acos")):
            config[columna] = config_porcentaje(etiqueta)
        elif any(p in minusculas for p in ("pedido", "unidad", "transaccion", "cantidad", "linea")):
            config[columna] = config_entero(etiqueta)
        else:
            config[columna] = config_moneda(etiqueta)

    # ``height`` solo se envía cuando se pidió una altura fija: Streamlit rechaza
    # el valor ``None``.
    extra = {"height": altura} if altura else {}
    st.dataframe(df, width="stretch", hide_index=True, column_config=config, **extra)


def editor_costos(catalogo: pd.DataFrame, clave: str = "editor_costos") -> pd.DataFrame:
    """Tabla editable para capturar los costos por SKU."""
    return st.data_editor(
        catalogo,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key=clave,
        column_config={
            "sku": st.column_config.TextColumn(
                "SKU", required=True, help="Debe coincidir con el SKU del reporte de Amazon."
            ),
            "costo_unitario": st.column_config.NumberColumn(
                "Costo unitario", format="$%.2f", min_value=0.0, step=1.0,
                help="Cuánto te cuesta una pieza puesta en tu almacén.",
            ),
            "costo_logistico_adicional": st.column_config.NumberColumn(
                "Costo logístico adicional", format="$%.2f", min_value=0.0, step=1.0,
                help="Flete, empaque o maquila por unidad.",
            ),
            "gasto_publicitario": st.column_config.NumberColumn(
                "Gasto publicitario", format="$%.2f", min_value=0.0, step=1.0,
                help="Inversión en anuncios asignada a este SKU en el periodo.",
            ),
            "marca": st.column_config.TextColumn("Marca"),
            "categoria": st.column_config.TextColumn("Categoría"),
        },
    )

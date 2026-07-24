"""Filtros globales del tablero (barra lateral).

Los filtros viven en ``st.session_state["filtros"]`` y se aplican en **todas**
las páginas: tarjetas, gráficas y tablas leen siempre el mismo DataFrame
filtrado.

Los filtros se aplican de inmediato al cambiarlos.  El botón «Aplicar filtros»
existe para forzar el recálculo tras editar varios controles seguidos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from services.comparison_service import MODOS_COMPARACION, filtrar_por_rango
from utils.constants import (
    COL_CIUDAD,
    COL_CUMPLIMIENTO,
    COL_DESCRIPCION,
    COL_ESTADO,
    COL_ESTADO_TRANSACCION,
    COL_FECHA,
    COL_LIQUIDACION,
    COL_MARKETPLACE,
    COL_SKU,
    COL_TIPO,
    TIPO_PEDIDO,
    TIPO_REEMBOLSO,
)
from utils.formatting import formato_entero
from utils.logger import get_logger

logger = get_logger("filters")

CLAVE_FILTROS = "filtros"

#: Opciones del selector rápido «Pedido o reembolso».
OPCIONES_MOVIMIENTO = ["Todo", "Solo pedidos", "Solo reembolsos", "Sin transferencias"]


@dataclass
class EstadoFiltros:
    """Valores seleccionados en la barra lateral."""

    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    marketplaces: list[str] = field(default_factory=list)
    tipos: list[str] = field(default_factory=list)
    skus: list[str] = field(default_factory=list)
    productos: list[str] = field(default_factory=list)
    cumplimientos: list[str] = field(default_factory=list)
    estados: list[str] = field(default_factory=list)
    ciudades: list[str] = field(default_factory=list)
    liquidaciones: list[str] = field(default_factory=list)
    estados_transaccion: list[str] = field(default_factory=list)
    movimiento: str = "Todo"
    modo_comparacion: str = "Periodo anterior equivalente"
    rango_personalizado: tuple[date, date] | None = None
    excluir_duplicados: bool = False

    def como_dict(self) -> dict[str, Any]:
        """Representación serializable, para guardar el filtro en la base de datos."""
        return {
            "fecha_inicio": self.fecha_inicio.isoformat() if self.fecha_inicio else None,
            "fecha_fin": self.fecha_fin.isoformat() if self.fecha_fin else None,
            "marketplaces": self.marketplaces,
            "tipos": self.tipos,
            "skus": self.skus,
            "productos": self.productos,
            "cumplimientos": self.cumplimientos,
            "estados": self.estados,
            "ciudades": self.ciudades,
            "liquidaciones": self.liquidaciones,
            "estados_transaccion": self.estados_transaccion,
            "movimiento": self.movimiento,
            "modo_comparacion": self.modo_comparacion,
            "excluir_duplicados": self.excluir_duplicados,
        }


def _opciones(df: pd.DataFrame, columna: str, maximo: int = 5_000) -> list[str]:
    """Valores distintos de una columna, ordenados y sin vacíos."""
    if df.empty or columna not in df.columns:
        return []
    serie = df[columna].astype("string").dropna()
    serie = serie[serie.str.strip().ne("")]
    valores = sorted(serie.unique().tolist())
    return valores[:maximo]


def _rango_disponible(df: pd.DataFrame) -> tuple[date, date]:
    """Primera y última fecha con datos (hoy si no hay fechas válidas)."""
    if df.empty or COL_FECHA not in df.columns:
        hoy = date.today()
        return hoy - timedelta(days=30), hoy
    fechas = pd.to_datetime(df[COL_FECHA], errors="coerce").dropna()
    if fechas.empty:
        hoy = date.today()
        return hoy - timedelta(days=30), hoy
    return fechas.min().date(), fechas.max().date()


# =============================================================================
# Barra lateral
# =============================================================================


def render_filtros(df: pd.DataFrame, mostrar_comparacion: bool = True) -> EstadoFiltros:
    """Dibuja los filtros en la barra lateral y devuelve la selección.

    Args:
        df: DataFrame completo cargado en la sesión.
        mostrar_comparacion: si se ofrece el selector de periodo de comparación
            (se oculta en los planes que no incluyen la función).
    """
    minimo, maximo = _rango_disponible(df)
    guardados: EstadoFiltros = st.session_state.get(CLAVE_FILTROS) or EstadoFiltros(
        fecha_inicio=minimo, fecha_fin=maximo
    )

    with st.sidebar:
        st.markdown("### Filtros")

        # --- Fechas ----------------------------------------------------------
        inicio_defecto = guardados.fecha_inicio or minimo
        fin_defecto = guardados.fecha_fin or maximo
        # Si se cargaron datos nuevos, el rango guardado puede quedar fuera.
        inicio_defecto = max(min(inicio_defecto, maximo), minimo)
        fin_defecto = max(min(fin_defecto, maximo), minimo)

        rango = st.date_input(
            "Rango de fechas",
            value=(inicio_defecto, fin_defecto),
            min_value=minimo,
            max_value=maximo,
            format="DD/MM/YYYY",
            key="filtro_fechas",
            help="El rango se aplica sobre la columna «fecha/hora» del reporte.",
        )
        if isinstance(rango, (tuple, list)) and len(rango) == 2:
            fecha_inicio, fecha_fin = rango
        else:
            fecha_inicio, fecha_fin = inicio_defecto, fin_defecto

        # Accesos rápidos de rango.
        col_a, col_b, col_c = st.columns(3)
        if col_a.button("7 días", width="stretch", help="Últimos 7 días con datos"):
            fecha_fin, fecha_inicio = maximo, max(minimo, maximo - timedelta(days=6))
            st.session_state["filtro_fechas"] = (fecha_inicio, fecha_fin)
        if col_b.button("30 días", width="stretch", help="Últimos 30 días con datos"):
            fecha_fin, fecha_inicio = maximo, max(minimo, maximo - timedelta(days=29))
            st.session_state["filtro_fechas"] = (fecha_inicio, fecha_fin)
        if col_c.button("Todo", width="stretch", help="Todo el periodo cargado"):
            fecha_inicio, fecha_fin = minimo, maximo
            st.session_state["filtro_fechas"] = (fecha_inicio, fecha_fin)

        # --- Movimiento ------------------------------------------------------
        movimiento = st.radio(
            "Movimiento",
            OPCIONES_MOVIMIENTO,
            index=OPCIONES_MOVIMIENTO.index(guardados.movimiento)
            if guardados.movimiento in OPCIONES_MOVIMIENTO else 0,
            horizontal=False,
            key="filtro_movimiento",
            help=(
                "«Sin transferencias» quita los retiros a la cuenta bancaria, "
                "que no son ventas ni cargos."
            ),
        )

        # --- Dimensiones -----------------------------------------------------
        with st.expander("Marketplace y tipo", expanded=False):
            marketplaces = st.multiselect(
                "Marketplace", _opciones(df, COL_MARKETPLACE),
                default=_validar(guardados.marketplaces, _opciones(df, COL_MARKETPLACE)),
                key="filtro_marketplace",
                placeholder="Todos",
            )
            tipos = st.multiselect(
                "Tipo de transacción", _opciones(df, COL_TIPO),
                default=_validar(guardados.tipos, _opciones(df, COL_TIPO)),
                key="filtro_tipo",
                placeholder="Todos",
            )
            cumplimientos = st.multiselect(
                "Cumplimiento", _opciones(df, COL_CUMPLIMIENTO),
                default=_validar(guardados.cumplimientos, _opciones(df, COL_CUMPLIMIENTO)),
                key="filtro_cumplimiento",
                placeholder="Todos",
            )

        with st.expander("Productos", expanded=False):
            opciones_sku = _opciones(df, COL_SKU)
            skus = st.multiselect(
                "SKU", opciones_sku,
                default=_validar(guardados.skus, opciones_sku),
                key="filtro_sku",
                placeholder="Todos",
            )
            opciones_producto = _opciones(df, COL_DESCRIPCION, maximo=1_000)
            productos = st.multiselect(
                "Producto", opciones_producto,
                default=_validar(guardados.productos, opciones_producto),
                key="filtro_producto",
                placeholder="Todos",
                format_func=lambda v: v[:60] + "…" if len(v) > 60 else v,
            )

        with st.expander("Ubicación", expanded=False):
            estados = st.multiselect(
                "Estado", _opciones(df, COL_ESTADO),
                default=_validar(guardados.estados, _opciones(df, COL_ESTADO)),
                key="filtro_estado",
                placeholder="Todos",
            )
            opciones_ciudad = _opciones(df, COL_CIUDAD, maximo=2_000)
            ciudades = st.multiselect(
                "Ciudad", opciones_ciudad,
                default=_validar(guardados.ciudades, opciones_ciudad),
                key="filtro_ciudad",
                placeholder="Todas",
            )

        with st.expander("Liquidación", expanded=False):
            liquidaciones = st.multiselect(
                "Id. de liquidación", _opciones(df, COL_LIQUIDACION),
                default=_validar(guardados.liquidaciones, _opciones(df, COL_LIQUIDACION)),
                key="filtro_liquidacion",
                placeholder="Todas",
            )
            estados_transaccion = st.multiselect(
                "Estado de la transacción", _opciones(df, COL_ESTADO_TRANSACCION),
                default=_validar(
                    guardados.estados_transaccion, _opciones(df, COL_ESTADO_TRANSACCION)
                ),
                key="filtro_estado_transaccion",
                placeholder="Todos",
            )

        # --- Comparación -----------------------------------------------------
        modo_comparacion = guardados.modo_comparacion
        rango_personalizado = guardados.rango_personalizado
        if mostrar_comparacion:
            st.markdown("---")
            modo_comparacion = st.selectbox(
                "Periodo de comparación",
                MODOS_COMPARACION,
                index=MODOS_COMPARACION.index(modo_comparacion)
                if modo_comparacion in MODOS_COMPARACION else 0,
                key="filtro_comparacion",
                help=(
                    "«Periodo anterior equivalente» usa los mismos días inmediatamente "
                    "anteriores al rango seleccionado."
                ),
            )
            if modo_comparacion == "Periodo personalizado":
                rango_alterno = st.date_input(
                    "Comparar contra",
                    value=rango_personalizado or (minimo, fecha_inicio - timedelta(days=1)),
                    format="DD/MM/YYYY",
                    key="filtro_comparacion_rango",
                )
                if isinstance(rango_alterno, (tuple, list)) and len(rango_alterno) == 2:
                    rango_personalizado = tuple(rango_alterno)  # type: ignore[assignment]

        # --- Duplicados ------------------------------------------------------
        from utils.constants import COL_ES_DUPLICADO

        excluir_duplicados = guardados.excluir_duplicados
        if COL_ES_DUPLICADO in df.columns and bool(df[COL_ES_DUPLICADO].any()):
            duplicados = int(df[COL_ES_DUPLICADO].fillna(False).astype(bool).sum())
            excluir_duplicados = st.checkbox(
                f"Excluir {formato_entero(duplicados)} posibles duplicados",
                value=excluir_duplicados,
                key="filtro_duplicados",
                help=(
                    "Se consideran duplicados los registros que comparten pedido, tipo, "
                    "SKU, fecha, total y liquidación."
                ),
            )
            st.session_state["excluir_duplicados"] = excluir_duplicados

        # --- Botones ---------------------------------------------------------
        st.markdown("---")
        col_izq, col_der = st.columns(2)
        limpiar = col_izq.button("Limpiar filtros", width="stretch")
        aplicar = col_der.button("Aplicar filtros", width="stretch", type="primary")
        restablecer = st.button(
            "Restablecer tablero", width="stretch",
            help="Vuelve a los filtros iniciales y descarta la selección guardada.",
        )

        if limpiar or restablecer:
            _limpiar_estado_filtros()
            st.rerun()

    estado = EstadoFiltros(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        marketplaces=marketplaces,
        tipos=tipos,
        skus=skus,
        productos=productos,
        cumplimientos=cumplimientos,
        estados=estados,
        ciudades=ciudades,
        liquidaciones=liquidaciones,
        estados_transaccion=estados_transaccion,
        movimiento=movimiento,
        modo_comparacion=modo_comparacion,
        rango_personalizado=rango_personalizado,
        excluir_duplicados=excluir_duplicados,
    )
    st.session_state[CLAVE_FILTROS] = estado

    if aplicar:
        logger.debug("Filtros aplicados manualmente.")

    return estado


def _validar(seleccion: list[str], opciones: list[str]) -> list[str]:
    """Descarta los valores guardados que ya no existen en los datos actuales."""
    disponibles = set(opciones)
    return [v for v in seleccion if v in disponibles]


def _limpiar_estado_filtros() -> None:
    """Borra la selección de la barra lateral."""
    claves = [
        CLAVE_FILTROS, "filtro_fechas", "filtro_movimiento", "filtro_marketplace",
        "filtro_tipo", "filtro_cumplimiento", "filtro_sku", "filtro_producto",
        "filtro_estado", "filtro_ciudad", "filtro_liquidacion",
        "filtro_estado_transaccion", "filtro_comparacion",
        "filtro_comparacion_rango", "filtro_duplicados", "excluir_duplicados",
    ]
    for clave in claves:
        st.session_state.pop(clave, None)


# =============================================================================
# Aplicación de los filtros
# =============================================================================


def aplicar_filtros(df: pd.DataFrame, filtros: EstadoFiltros) -> pd.DataFrame:
    """Devuelve el subconjunto de datos que cumple con todos los filtros.

    La operación es vectorizada: se construye una máscara booleana única y se
    aplica una sola vez.
    """
    if df.empty:
        return df

    resultado = df

    # --- Fechas --------------------------------------------------------------
    if filtros.fecha_inicio and filtros.fecha_fin:
        resultado = filtrar_por_rango(resultado, filtros.fecha_inicio, filtros.fecha_fin)

    if resultado.empty:
        return resultado

    # --- Dimensiones ---------------------------------------------------------
    mascara = pd.Series(True, index=resultado.index)
    columnas_seleccion = (
        (COL_MARKETPLACE, filtros.marketplaces),
        (COL_TIPO, filtros.tipos),
        (COL_CUMPLIMIENTO, filtros.cumplimientos),
        (COL_SKU, filtros.skus),
        (COL_DESCRIPCION, filtros.productos),
        (COL_ESTADO, filtros.estados),
        (COL_CIUDAD, filtros.ciudades),
        (COL_LIQUIDACION, filtros.liquidaciones),
        (COL_ESTADO_TRANSACCION, filtros.estados_transaccion),
    )
    for columna, seleccion in columnas_seleccion:
        if seleccion and columna in resultado.columns:
            mascara &= resultado[columna].astype("string").isin(seleccion)

    # --- Movimiento ----------------------------------------------------------
    if COL_TIPO in resultado.columns:
        tipo = resultado[COL_TIPO].astype("string")
        if filtros.movimiento == "Solo pedidos":
            mascara &= tipo == TIPO_PEDIDO
        elif filtros.movimiento == "Solo reembolsos":
            mascara &= tipo == TIPO_REEMBOLSO
        elif filtros.movimiento == "Sin transferencias":
            from utils.constants import TIPOS_EXCLUIDOS_DEL_NETO

            mascara &= ~tipo.isin(TIPOS_EXCLUIDOS_DEL_NETO)

    # --- Duplicados ----------------------------------------------------------
    from utils.constants import COL_ES_DUPLICADO

    if filtros.excluir_duplicados and COL_ES_DUPLICADO in resultado.columns:
        mascara &= ~resultado[COL_ES_DUPLICADO].fillna(False).astype(bool)

    return resultado.loc[mascara]


def resumen_filtros(filtros: EstadoFiltros, filas_filtradas: int, filas_totales: int) -> str:
    """Frase que resume la selección activa, para mostrarla sobre el tablero."""
    partes: list[str] = []
    if filtros.fecha_inicio and filtros.fecha_fin:
        partes.append(
            f"{filtros.fecha_inicio:%d/%m/%Y} – {filtros.fecha_fin:%d/%m/%Y}"
        )
    if filtros.movimiento != "Todo":
        partes.append(filtros.movimiento.lower())
    for etiqueta, seleccion in (
        ("marketplace", filtros.marketplaces),
        ("tipo", filtros.tipos),
        ("SKU", filtros.skus),
        ("estado", filtros.estados),
        ("ciudad", filtros.ciudades),
        ("liquidación", filtros.liquidaciones),
    ):
        if seleccion:
            partes.append(
                f"{len(seleccion)} {etiqueta}" + ("s" if len(seleccion) > 1 else "")
            )

    contexto = " · ".join(partes) if partes else "sin filtros adicionales"
    return (
        f"{formato_entero(filas_filtradas)} de {formato_entero(filas_totales)} "
        f"transacciones · {contexto}"
    )

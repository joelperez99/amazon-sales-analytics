"""Comparación entre periodos.

Calcula el periodo anterior equivalente y las diferencias métrica por métrica.

Regla clave: si el periodo anterior vale cero, la variación porcentual **no** se
calcula (se devuelve ``None`` y la interfaz muestra «N/D»).  Un porcentaje sobre
una base cero no significa nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from services.metrics_service import calcular_metricas
from utils.constants import COL_FECHA, DICCIONARIO_METRICAS
from utils.formatting import variacion_absoluta, variacion_porcentual
from utils.logger import get_logger

logger = get_logger("comparison_service")

#: Modos de comparación disponibles en la barra lateral.
MODOS_COMPARACION: list[str] = [
    "Periodo anterior equivalente",
    "Mes anterior",
    "Semana anterior",
    "Año anterior",
    "Periodo personalizado",
    "Sin comparación",
]


@dataclass
class Comparacion:
    """Resultado de comparar dos periodos."""

    metricas_actual: dict[str, Any] = field(default_factory=dict)
    metricas_anterior: dict[str, Any] = field(default_factory=dict)
    diferencias: dict[str, dict[str, Any]] = field(default_factory=dict)
    rango_actual: tuple[date | None, date | None] = (None, None)
    rango_anterior: tuple[date | None, date | None] = (None, None)
    modo: str = "Sin comparación"
    hay_comparacion: bool = False

    def delta(self, clave: str) -> float | None:
        """Diferencia absoluta de una métrica."""
        return self.diferencias.get(clave, {}).get("absoluta")

    def delta_pct(self, clave: str) -> float | None:
        """Variación porcentual de una métrica (``None`` si no aplica)."""
        return self.diferencias.get(clave, {}).get("porcentual")

    def valor_anterior(self, clave: str) -> Any:
        """Valor de la métrica en el periodo anterior."""
        return self.metricas_anterior.get(clave)


# =============================================================================
# Cálculo del rango anterior
# =============================================================================


def calcular_rango_anterior(
    inicio: date,
    fin: date,
    modo: str = "Periodo anterior equivalente",
) -> tuple[date, date]:
    """Devuelve el rango del periodo con el que se compara.

    * **Periodo anterior equivalente**: los N días inmediatamente anteriores.
      Si el usuario elige del 1 al 30 de junio (30 días), compara contra el
      2 al 31 de mayo.
    * **Mes anterior**: el mismo rango desplazado un mes.
    * **Semana anterior**: el mismo rango desplazado 7 días.
    * **Año anterior**: el mismo rango desplazado un año.
    """
    inicio_ts = pd.Timestamp(inicio)
    fin_ts = pd.Timestamp(fin)
    dias = (fin_ts - inicio_ts).days + 1

    if modo == "Mes anterior":
        nuevo_inicio = inicio_ts - pd.DateOffset(months=1)
        nuevo_fin = fin_ts - pd.DateOffset(months=1)
    elif modo == "Semana anterior":
        nuevo_inicio = inicio_ts - timedelta(days=7)
        nuevo_fin = fin_ts - timedelta(days=7)
    elif modo == "Año anterior":
        nuevo_inicio = inicio_ts - pd.DateOffset(years=1)
        nuevo_fin = fin_ts - pd.DateOffset(years=1)
    else:  # Periodo anterior equivalente
        nuevo_fin = inicio_ts - timedelta(days=1)
        nuevo_inicio = nuevo_fin - timedelta(days=dias - 1)

    return nuevo_inicio.date(), nuevo_fin.date()


def filtrar_por_rango(df: pd.DataFrame, inicio: date, fin: date) -> pd.DataFrame:
    """Filtra el DataFrame por rango de fechas, incluyendo ambos extremos."""
    if df.empty or COL_FECHA not in df.columns:
        return df.iloc[0:0]
    fechas = pd.to_datetime(df[COL_FECHA], errors="coerce")
    limite_inicio = pd.Timestamp(inicio)
    # El día final se incluye completo, hasta las 23:59:59.
    limite_fin = pd.Timestamp(fin) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return df.loc[fechas.between(limite_inicio, limite_fin)]


# =============================================================================
# Comparación completa
# =============================================================================

#: Métricas donde un aumento es una buena noticia.
MAYOR_ES_MEJOR: set[str] = {
    "ventas_brutas", "ventas_con_impuestos", "pedidos_unicos", "unidades",
    "ticket_promedio", "precio_promedio_unidad", "unidades_por_pedido",
    "skus_vendidos", "productos_vendidos", "ventas_por_dia", "pedidos_por_dia",
    "unidades_por_dia", "neto", "neto_por_pedido", "neto_por_unidad",
    "neto_por_sku", "margen_neto", "pct_neto", "utilidad_antes_publicidad",
    "utilidad_despues_publicidad", "margen_bruto", "margen_contribucion", "roi",
}

#: Métricas donde un aumento es una mala noticia (cargos y devoluciones).
MENOR_ES_MEJOR: set[str] = {
    "tarifas_venta", "tarifas_fba", "tarifas_otras", "tarifa_reglamentaria",
    "retenciones", "tarifas_inventario", "tarifas_servicio", "otros_cargos",
    "total_cargos", "tarifa_por_pedido", "tarifa_por_unidad", "pct_comisiones",
    "pct_fba", "pct_cargos", "pedidos_reembolsados", "transacciones_reembolso",
    "unidades_reembolsadas", "importe_reembolsado", "pct_pedidos_reembolsados",
    "pct_unidades_reembolsadas", "tasa_reembolso", "acos", "tacos",
    "descuentos_promocionales", "costo_mercancia",
}


def comparar_metricas(
    metricas_actual: dict[str, Any], metricas_anterior: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Calcula diferencia absoluta y porcentual de cada métrica."""
    diferencias: dict[str, dict[str, Any]] = {}
    for clave, valor_actual in metricas_actual.items():
        if not isinstance(valor_actual, (int, float)) or isinstance(valor_actual, bool):
            continue
        valor_anterior = metricas_anterior.get(clave)
        if not isinstance(valor_anterior, (int, float)) or isinstance(valor_anterior, bool):
            valor_anterior = None

        diferencias[clave] = {
            "actual": valor_actual,
            "anterior": valor_anterior,
            "absoluta": variacion_absoluta(valor_actual, valor_anterior),
            "porcentual": variacion_porcentual(valor_actual, valor_anterior),
            "mayor_es_mejor": clave not in MENOR_ES_MEJOR,
        }
    return diferencias


def comparar_periodos(
    df_completo: pd.DataFrame,
    inicio: date,
    fin: date,
    modo: str = "Periodo anterior equivalente",
    rango_personalizado: tuple[date, date] | None = None,
) -> Comparacion:
    """Compara el periodo seleccionado contra el periodo de referencia.

    Args:
        df_completo: **todos** los datos cargados, sin filtro de fechas.  El
            periodo anterior necesita registros fuera del rango actual.
        inicio, fin: rango del periodo actual.
        modo: uno de :data:`MODOS_COMPARACION`.
        rango_personalizado: rango explícito cuando ``modo`` es «Periodo personalizado».
    """
    df_actual = filtrar_por_rango(df_completo, inicio, fin)
    metricas_actual = calcular_metricas(df_actual)

    if modo == "Sin comparación":
        return Comparacion(
            metricas_actual=metricas_actual,
            rango_actual=(inicio, fin),
            modo=modo,
            hay_comparacion=False,
        )

    if modo == "Periodo personalizado" and rango_personalizado:
        inicio_anterior, fin_anterior = rango_personalizado
    else:
        inicio_anterior, fin_anterior = calcular_rango_anterior(inicio, fin, modo)

    df_anterior = filtrar_por_rango(df_completo, inicio_anterior, fin_anterior)
    metricas_anterior = calcular_metricas(df_anterior)

    comparacion = Comparacion(
        metricas_actual=metricas_actual,
        metricas_anterior=metricas_anterior,
        diferencias=comparar_metricas(metricas_actual, metricas_anterior),
        rango_actual=(inicio, fin),
        rango_anterior=(inicio_anterior, fin_anterior),
        modo=modo,
        hay_comparacion=not df_anterior.empty,
    )

    if df_anterior.empty:
        logger.info(
            "El periodo de comparación %s a %s no tiene registros.",
            inicio_anterior, fin_anterior,
        )

    return comparacion


def tabla_comparativa(comparacion: Comparacion, claves: list[str] | None = None) -> pd.DataFrame:
    """Arma la tabla «actual vs anterior» que se muestra y se exporta."""
    claves = claves or [
        "ventas_brutas", "pedidos_unicos", "unidades", "ticket_promedio",
        "total_cargos", "tarifas_venta", "tarifas_fba", "importe_reembolsado",
        "neto", "margen_neto",
    ]

    filas = []
    for clave in claves:
        detalle = comparacion.diferencias.get(clave)
        info = DICCIONARIO_METRICAS.get(clave, {})
        if detalle is None:
            filas.append({
                "Métrica": info.get("nombre", clave),
                "Periodo actual": comparacion.metricas_actual.get(clave),
                "Periodo anterior": None,
                "Diferencia": None,
                "Variación %": None,
            })
            continue
        filas.append({
            "Métrica": info.get("nombre", clave),
            "Periodo actual": detalle["actual"],
            "Periodo anterior": detalle["anterior"],
            "Diferencia": detalle["absoluta"],
            "Variación %": detalle["porcentual"],
        })
    return pd.DataFrame(filas)


def serie_comparativa(
    df_completo: pd.DataFrame,
    comparacion: Comparacion,
    frecuencia: str = "Día",
) -> pd.DataFrame:
    """Series temporales de ambos periodos alineadas por número de día.

    Alinear por posición (día 1, día 2, …) en lugar de por fecha permite
    superponer periodos de meses distintos en la misma gráfica.
    """
    from services.metrics_service import serie_temporal

    inicio_a, fin_a = comparacion.rango_actual
    if inicio_a is None or fin_a is None:
        return pd.DataFrame()

    actual = serie_temporal(filtrar_por_rango(df_completo, inicio_a, fin_a), frecuencia)
    actual = actual.assign(periodo_etiqueta="Periodo actual", indice=range(1, len(actual) + 1))

    if not comparacion.hay_comparacion:
        return actual

    inicio_b, fin_b = comparacion.rango_anterior
    anterior = serie_temporal(filtrar_por_rango(df_completo, inicio_b, fin_b), frecuencia)
    anterior = anterior.assign(
        periodo_etiqueta="Periodo anterior", indice=range(1, len(anterior) + 1)
    )
    return pd.concat([actual, anterior], ignore_index=True)

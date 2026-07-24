"""Generación de hallazgos automáticos.

Un «hallazgo» es una observación redactada en lenguaje sencillo, por ejemplo:

    «Las ventas disminuyeron 18.4% frente al periodo anterior.»

Se agrupan en tres severidades: ``critico``, ``advertencia`` e ``informativo``.
Los umbrales son configurables desde el archivo ``.env``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from services.comparison_service import Comparacion
from services.metrics_service import (
    sku_sin_ventas_recientes,
    tabla_por_sku,
    tarifas_sin_pedido,
)
from utils.config import get_settings
from utils.constants import (
    COL_CANTIDAD,
    COL_ES_DUPLICADO,
    COL_FECHA,
    COL_SKU,
    COL_TIPO,
    COL_TOTAL,
    TIPO_PEDIDO,
)
from utils.formatting import formato_entero, formato_moneda, formato_porcentaje
from utils.logger import get_logger

logger = get_logger("alerts_service")

SEVERIDAD_CRITICO = "critico"
SEVERIDAD_ADVERTENCIA = "advertencia"
SEVERIDAD_INFORMATIVO = "informativo"

#: Orden de presentación: lo más grave primero.
_ORDEN_SEVERIDAD = {SEVERIDAD_CRITICO: 0, SEVERIDAD_ADVERTENCIA: 1, SEVERIDAD_INFORMATIVO: 2}


@dataclass
class Hallazgo:
    """Una observación automática sobre los datos del periodo."""

    titulo: str
    mensaje: str
    severidad: str = SEVERIDAD_INFORMATIVO
    categoria: str = "General"
    recomendacion: str = ""
    datos: dict[str, Any] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return {
            "Severidad": {
                SEVERIDAD_CRITICO: "Crítico",
                SEVERIDAD_ADVERTENCIA: "Advertencia",
                SEVERIDAD_INFORMATIVO: "Informativo",
            }[self.severidad],
            "Categoría": self.categoria,
            "Hallazgo": self.titulo,
            "Detalle": self.mensaje,
            "Recomendación": self.recomendacion,
        }


# =============================================================================
# Reglas
# =============================================================================


def _alertas_comparacion(comparacion: Comparacion) -> list[Hallazgo]:
    """Hallazgos que surgen al comparar contra el periodo anterior."""
    settings = get_settings()
    hallazgos: list[Hallazgo] = []

    if not comparacion.hay_comparacion:
        return hallazgos

    umbral = settings.alertas.caida_ventas_pct / 100

    # --- Caída de ventas ---
    variacion = comparacion.delta_pct("ventas_brutas")
    if variacion is not None:
        if variacion <= -umbral:
            hallazgos.append(Hallazgo(
                titulo="Caída de ventas",
                mensaje=(
                    f"Las ventas disminuyeron {formato_porcentaje(abs(variacion))} frente al "
                    f"periodo anterior: pasaron de "
                    f"{formato_moneda(comparacion.valor_anterior('ventas_brutas'))} a "
                    f"{formato_moneda(comparacion.metricas_actual.get('ventas_brutas'))}."
                ),
                severidad=SEVERIDAD_CRITICO,
                categoria="Ventas",
                recomendacion="Revisa el inventario disponible, el precio de venta y si algún SKU dejó de publicarse.",
                datos={"variacion": variacion},
            ))
        elif variacion >= umbral:
            hallazgos.append(Hallazgo(
                titulo="Crecimiento de ventas",
                mensaje=(
                    f"Las ventas aumentaron {formato_porcentaje(variacion)} frente al periodo anterior."
                ),
                severidad=SEVERIDAD_INFORMATIVO,
                categoria="Ventas",
                recomendacion="Verifica que el inventario alcance para sostener el ritmo.",
                datos={"variacion": variacion},
            ))

    # --- Aumento de reembolsos ---
    variacion_reembolsos = comparacion.delta_pct("importe_reembolsado")
    if variacion_reembolsos is not None and variacion_reembolsos > 0.10:
        hallazgos.append(Hallazgo(
            titulo="Aumento de reembolsos",
            mensaje=(
                f"El importe reembolsado creció {formato_porcentaje(variacion_reembolsos)}: pasó de "
                f"{formato_moneda(comparacion.valor_anterior('importe_reembolsado'))} a "
                f"{formato_moneda(comparacion.metricas_actual.get('importe_reembolsado'))}."
            ),
            severidad=SEVERIDAD_ADVERTENCIA,
            categoria="Reembolsos",
            recomendacion="Revisa la página de reembolsos para identificar los SKU responsables.",
            datos={"variacion": variacion_reembolsos},
        ))

    # --- Deterioro del margen ---
    delta_margen = comparacion.delta("margen_neto")
    if delta_margen is not None and delta_margen < -0.02:
        hallazgos.append(Hallazgo(
            titulo="Margen neto a la baja",
            mensaje=(
                f"El margen neto bajó {formato_porcentaje(abs(delta_margen))} en puntos porcentuales: de "
                f"{formato_porcentaje(comparacion.valor_anterior('margen_neto'))} a "
                f"{formato_porcentaje(comparacion.metricas_actual.get('margen_neto'))}."
            ),
            severidad=SEVERIDAD_ADVERTENCIA,
            categoria="Rentabilidad",
            recomendacion="Compara las tarifas por unidad contra el periodo anterior.",
            datos={"delta": delta_margen},
        ))

    return hallazgos


def _alertas_tarifas(metricas: dict[str, Any], comparacion: Comparacion | None) -> list[Hallazgo]:
    """Hallazgos sobre el peso de los cargos de Amazon."""
    settings = get_settings()
    hallazgos: list[Hallazgo] = []

    pct_cargos = metricas.get("pct_cargos")
    if pct_cargos is None:
        return hallazgos

    umbral = settings.alertas.pct_cargos_pct / 100
    if pct_cargos > umbral:
        hallazgos.append(Hallazgo(
            titulo="Cargos de Amazon por encima del umbral",
            mensaje=(
                f"Los cargos de Amazon representan {formato_porcentaje(pct_cargos)} de las ventas brutas "
                f"({formato_moneda(metricas.get('total_cargos'))} sobre "
                f"{formato_moneda(metricas.get('ventas_brutas'))}). "
                f"El umbral configurado es {settings.alertas.pct_cargos_pct:.0f}%."
            ),
            severidad=SEVERIDAD_ADVERTENCIA,
            categoria="Tarifas",
            recomendacion="Revisa las dimensiones y el peso de los productos: suelen ser la causa de una tarifa FBA alta.",
            datos={"pct_cargos": pct_cargos},
        ))

    if comparacion is not None and comparacion.hay_comparacion:
        anterior = comparacion.valor_anterior("pct_cargos")
        if anterior is not None and pct_cargos > anterior * 1.10 and anterior > 0:
            hallazgos.append(Hallazgo(
                titulo="Los cargos crecieron más rápido que las ventas",
                mensaje=(
                    f"El porcentaje de cargos pasó de {formato_porcentaje(anterior)} a "
                    f"{formato_porcentaje(pct_cargos)} de las ventas."
                ),
                severidad=SEVERIDAD_ADVERTENCIA,
                categoria="Tarifas",
                recomendacion="Verifica si Amazon aplicó una tarifa de almacenamiento prolongado o un cambio de categoría.",
            ))

    return hallazgos


def _alertas_reembolsos(metricas: dict[str, Any], tabla_sku: pd.DataFrame) -> list[Hallazgo]:
    """Hallazgos sobre devoluciones, generales y por SKU."""
    settings = get_settings()
    hallazgos: list[Hallazgo] = []

    tasa = metricas.get("tasa_reembolso")
    umbral = settings.alertas.tasa_reembolso_pct / 100

    if tasa is not None and tasa > umbral:
        hallazgos.append(Hallazgo(
            titulo="Tasa de reembolso elevada",
            mensaje=(
                f"Los reembolsos equivalen a {formato_porcentaje(tasa)} de las ventas brutas "
                f"({formato_moneda(metricas.get('importe_reembolsado'))}). "
                f"El umbral configurado es {settings.alertas.tasa_reembolso_pct:.0f}%."
            ),
            severidad=SEVERIDAD_CRITICO if tasa > umbral * 2 else SEVERIDAD_ADVERTENCIA,
            categoria="Reembolsos",
            recomendacion="Revisa las reseñas y la descripción de los productos con más devoluciones.",
            datos={"tasa": tasa},
        ))

    if tabla_sku.empty or "tasa_reembolso" not in tabla_sku.columns:
        return hallazgos

    # SKU con tasa de reembolso muy por encima del promedio del catálogo.
    con_ventas = tabla_sku.loc[tabla_sku["ventas"] > 0]
    if len(con_ventas) >= 2:
        promedio = float(con_ventas["tasa_reembolso"].mean())
        for _, fila in con_ventas.iterrows():
            tasa_sku = float(fila["tasa_reembolso"])
            if tasa_sku > max(promedio * 1.5, umbral) and tasa_sku > 0:
                hallazgos.append(Hallazgo(
                    titulo=f"Reembolsos altos en {fila[COL_SKU]}",
                    mensaje=(
                        f"La tasa de reembolso del SKU {fila[COL_SKU]} es "
                        f"{formato_porcentaje(tasa_sku)}, por encima del promedio del catálogo "
                        f"({formato_porcentaje(promedio)})."
                    ),
                    severidad=SEVERIDAD_ADVERTENCIA,
                    categoria="Reembolsos",
                    recomendacion="Revisa el empaque, la talla o la descripción de este producto.",
                    datos={"sku": fila[COL_SKU], "tasa": tasa_sku},
                ))

    return hallazgos


def _alertas_concentracion(tabla_sku: pd.DataFrame) -> list[Hallazgo]:
    """Detecta dependencia excesiva de un solo producto."""
    settings = get_settings()
    hallazgos: list[Hallazgo] = []
    if tabla_sku.empty or "participacion" not in tabla_sku.columns:
        return hallazgos

    umbral = settings.alertas.concentracion_sku_pct / 100
    for _, fila in tabla_sku.iterrows():
        participacion = float(fila["participacion"])
        if participacion >= umbral:
            hallazgos.append(Hallazgo(
                titulo="Concentración de ventas en un solo SKU",
                mensaje=(
                    f"El SKU {fila[COL_SKU]} representa "
                    f"{formato_porcentaje(participacion)} de las ventas del periodo."
                ),
                severidad=SEVERIDAD_ADVERTENCIA,
                categoria="Productos",
                recomendacion="Un quiebre de inventario en este producto afectaría la mayor parte del ingreso.",
                datos={"sku": fila[COL_SKU], "participacion": participacion},
            ))
    return hallazgos


def _alertas_calidad_datos(df: pd.DataFrame, metricas: dict[str, Any]) -> list[Hallazgo]:
    """Hallazgos sobre la integridad del archivo cargado."""
    settings = get_settings()
    hallazgos: list[Hallazgo] = []

    if df.empty:
        return hallazgos

    # --- Conciliación del neto ---
    diferencia = metricas.get("diferencia_conciliacion")
    if diferencia is not None and abs(diferencia) > settings.alertas.tolerancia_conciliacion:
        hallazgos.append(Hallazgo(
            titulo="El neto no concilia con el detalle",
            mensaje=(
                f"La suma de la columna «total» ({formato_moneda(metricas.get('neto'))}) difiere en "
                f"{formato_moneda(diferencia)} de la suma de los componentes "
                f"({formato_moneda(metricas.get('neto_reconstruido'))})."
            ),
            severidad=SEVERIDAD_CRITICO,
            categoria="Calidad de datos",
            recomendacion="Es probable que falte una columna monetaria en el archivo o que traiga un formato inesperado.",
            datos={"diferencia": diferencia},
        ))

    # --- Fechas inválidas ---
    if COL_FECHA in df.columns:
        sin_fecha = int(pd.to_datetime(df[COL_FECHA], errors="coerce").isna().sum())
        if sin_fecha:
            hallazgos.append(Hallazgo(
                titulo="Fechas que no se pudieron interpretar",
                mensaje=f"{formato_entero(sin_fecha)} registros no tienen una fecha válida y quedan fuera de las gráficas por día.",
                severidad=SEVERIDAD_ADVERTENCIA,
                categoria="Calidad de datos",
                recomendacion="Revisa el formato de la columna «fecha/hora» en el archivo original.",
            ))

    # --- Ventas sin SKU ---
    if COL_TIPO in df.columns and COL_SKU in df.columns:
        pedidos = df[COL_TIPO].astype("string") == TIPO_PEDIDO
        sin_sku = int((pedidos & df[COL_SKU].astype("string").isin(["", "Sin SKU"])).sum())
        if sin_sku:
            hallazgos.append(Hallazgo(
                titulo="Ventas sin SKU",
                mensaje=f"{formato_entero(sin_sku)} ventas no tienen un SKU asignado y no aparecen en el análisis por producto.",
                severidad=SEVERIDAD_ADVERTENCIA,
                categoria="Calidad de datos",
                recomendacion="Suelen ser cargos manuales o ajustes registrados como pedido.",
            ))

        # --- Pedidos sin cantidad ---
        if COL_CANTIDAD in df.columns:
            cantidades = pd.to_numeric(df[COL_CANTIDAD], errors="coerce").fillna(0)
            sin_cantidad = int((pedidos & cantidades.eq(0)).sum())
            if sin_cantidad:
                hallazgos.append(Hallazgo(
                    titulo="Pedidos sin cantidad",
                    mensaje=f"{formato_entero(sin_cantidad)} pedidos tienen cantidad cero y no suman unidades vendidas.",
                    severidad=SEVERIDAD_ADVERTENCIA,
                    categoria="Calidad de datos",
                    recomendacion="Las unidades vendidas y el precio promedio quedarán subestimados.",
                ))

    # --- Totales no numéricos ---
    if COL_TOTAL in df.columns:
        no_numericos = int(pd.to_numeric(df[COL_TOTAL], errors="coerce").isna().sum())
        if no_numericos:
            hallazgos.append(Hallazgo(
                titulo="Totales no numéricos",
                mensaje=f"{formato_entero(no_numericos)} registros tienen un «total» que no pudo convertirse a número; se tomaron como cero.",
                severidad=SEVERIDAD_ADVERTENCIA,
                categoria="Calidad de datos",
                recomendacion="Revisa si el archivo trae símbolos de moneda o texto en esa columna.",
            ))

    # --- Duplicados ---
    if COL_ES_DUPLICADO in df.columns:
        duplicados = int(df[COL_ES_DUPLICADO].fillna(False).astype(bool).sum())
        if duplicados:
            hallazgos.append(Hallazgo(
                titulo="Posibles registros duplicados",
                mensaje=(
                    f"{formato_entero(duplicados)} registros comparten pedido, tipo, SKU, fecha, total y "
                    "liquidación con otro registro."
                ),
                severidad=SEVERIDAD_ADVERTENCIA,
                categoria="Calidad de datos",
                recomendacion="Puede deberse a que subiste dos veces el mismo periodo. Puedes excluirlos desde la página de carga.",
                datos={"duplicados": duplicados},
            ))

    # --- Tarifas FBA sin pedido ---
    huerfanas = tarifas_sin_pedido(df)
    if huerfanas:
        hallazgos.append(Hallazgo(
            titulo="Tarifas FBA sin pedido relacionado",
            mensaje=f"{formato_entero(huerfanas)} registros tienen tarifa FBA pero no traen Id. del pedido.",
            severidad=SEVERIDAD_INFORMATIVO,
            categoria="Calidad de datos",
            recomendacion="Normalmente son ajustes de tarifa o cargos por eliminación de inventario.",
        ))

    return hallazgos


def _alertas_inactividad(df: pd.DataFrame) -> list[Hallazgo]:
    """SKU que dejaron de venderse dentro del periodo analizado."""
    settings = get_settings()
    dias = settings.alertas.dias_sin_venta
    inactivos = sku_sin_ventas_recientes(df, dias=dias)
    if inactivos.empty:
        return []

    listado = ", ".join(
        f"{fila[COL_SKU]} ({int(fila['dias_sin_venta'])} días)"
        for _, fila in inactivos.head(5).iterrows()
    )
    return [Hallazgo(
        titulo="SKU sin ventas recientes",
        mensaje=(
            f"{len(inactivos)} SKU llevan al menos {dias} días sin registrar una venta "
            f"dentro del periodo analizado: {listado}."
        ),
        severidad=SEVERIDAD_ADVERTENCIA,
        categoria="Productos",
        recomendacion="Verifica si el producto está sin inventario o si perdió la Buy Box.",
        datos={"skus": inactivos[COL_SKU].tolist()},
    )]


# =============================================================================
# Punto de entrada
# =============================================================================


def generar_hallazgos(
    df: pd.DataFrame,
    metricas: dict[str, Any],
    comparacion: Comparacion | None = None,
) -> list[Hallazgo]:
    """Ejecuta todas las reglas y devuelve los hallazgos ordenados por severidad.

    Args:
        df: datos ya filtrados del periodo actual.
        metricas: salida de ``calcular_metricas`` sobre ese mismo periodo.
        comparacion: resultado de ``comparar_periodos`` (opcional).
    """
    hallazgos: list[Hallazgo] = []

    if df.empty:
        return [Hallazgo(
            titulo="Sin datos en el periodo",
            mensaje="Los filtros seleccionados no dejaron ningún registro.",
            severidad=SEVERIDAD_INFORMATIVO,
            categoria="General",
            recomendacion="Amplía el rango de fechas o limpia los filtros de la barra lateral.",
        )]

    tabla_sku = tabla_por_sku(df)

    try:
        if comparacion is not None:
            hallazgos.extend(_alertas_comparacion(comparacion))
        hallazgos.extend(_alertas_tarifas(metricas, comparacion))
        hallazgos.extend(_alertas_reembolsos(metricas, tabla_sku))
        hallazgos.extend(_alertas_concentracion(tabla_sku))
        hallazgos.extend(_alertas_calidad_datos(df, metricas))
        hallazgos.extend(_alertas_inactividad(df))
    except Exception as error:  # noqa: BLE001 - un hallazgo nunca debe romper el tablero
        from utils.logger import registrar_error

        id_error = registrar_error(logger, error, "generación de hallazgos")
        hallazgos.append(Hallazgo(
            titulo="No fue posible completar el análisis de hallazgos",
            mensaje=f"Ocurrió un problema al evaluar las reglas. Referencia: {id_error}.",
            severidad=SEVERIDAD_INFORMATIVO,
            categoria="General",
        ))

    hallazgos.sort(key=lambda h: _ORDEN_SEVERIDAD.get(h.severidad, 9))
    return hallazgos


def hallazgos_a_dataframe(hallazgos: list[Hallazgo]) -> pd.DataFrame:
    """Convierte los hallazgos en una tabla exportable a Excel."""
    if not hallazgos:
        return pd.DataFrame(
            columns=["Severidad", "Categoría", "Hallazgo", "Detalle", "Recomendación"]
        )
    return pd.DataFrame([h.como_dict() for h in hallazgos])

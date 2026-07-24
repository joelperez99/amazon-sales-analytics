"""Costos y rentabilidad.

El reporte de transacciones de Amazon **no** contiene el costo de compra del
producto.  Por eso este módulo trabaja con un catálogo de costos por SKU que el
usuario captura o sube aparte.

Terminología que se respeta en toda la aplicación:

* **Neto después de tarifas Amazon**: lo que Amazon deposita.  Se calcula
  siempre, no requiere costos.
* **Utilidad**: solo se usa cuando existe el costo del producto.  Si no hay
  catálogo de costos, la aplicación jamás llama «utilidad» al neto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from services.metrics_service import tabla_por_sku
from utils.constants import COL_SKU
from utils.formatting import division_segura, division_segura_serie
from utils.logger import get_logger

logger = get_logger("profitability_service")

#: Columnas del catálogo de costos.
COLUMNAS_CATALOGO: list[str] = [
    "sku",
    "costo_unitario",
    "costo_logistico_adicional",
    "gasto_publicitario",
    "marca",
    "categoria",
]

#: Alias aceptados al subir un catálogo de costos.
ALIAS_CATALOGO: dict[str, list[str]] = {
    "sku": ["sku", "clave", "codigo", "seller sku", "msku"],
    "costo_unitario": ["costo_unitario", "costo unitario", "costo", "cost", "unit cost"],
    "costo_logistico_adicional": [
        "costo_logistico_adicional", "costo logistico adicional", "costo logistico",
        "flete", "costo adicional",
    ],
    "gasto_publicitario": [
        "gasto_publicitario", "gasto publicitario", "publicidad", "ads", "ad spend",
    ],
    "marca": ["marca", "brand"],
    "categoria": ["categoria", "category", "linea"],
}


@dataclass
class ResultadoRentabilidad:
    """Rentabilidad calculada a nivel total y a nivel SKU."""

    tabla: pd.DataFrame
    metricas: dict[str, Any]
    skus_sin_costo: list[str]
    cobertura: float
    """Proporción de las ventas que sí tiene costo capturado (0 a 1)."""

    @property
    def hay_costos(self) -> bool:
        return not self.tabla.empty and self.cobertura > 0


def catalogo_vacio() -> pd.DataFrame:
    """Catálogo de costos vacío con la estructura correcta."""
    return pd.DataFrame({
        "sku": pd.Series(dtype="string"),
        "costo_unitario": pd.Series(dtype="float64"),
        "costo_logistico_adicional": pd.Series(dtype="float64"),
        "gasto_publicitario": pd.Series(dtype="float64"),
        "marca": pd.Series(dtype="string"),
        "categoria": pd.Series(dtype="string"),
    })


def normalizar_catalogo(df: pd.DataFrame) -> pd.DataFrame:
    """Traduce los encabezados de un catálogo subido y valida sus tipos."""
    from utils.constants import normalizar_texto

    indice: dict[str, str] = {}
    for canonica, alias in ALIAS_CATALOGO.items():
        for a in alias:
            indice[normalizar_texto(a)] = canonica

    renombres = {}
    for columna in df.columns:
        canonica = indice.get(normalizar_texto(columna))
        if canonica and canonica not in renombres.values():
            renombres[columna] = canonica

    catalogo = df.rename(columns=renombres)

    for columna in COLUMNAS_CATALOGO:
        if columna not in catalogo.columns:
            catalogo[columna] = "" if columna in {"sku", "marca", "categoria"} else 0.0

    catalogo = catalogo[COLUMNAS_CATALOGO].copy()
    catalogo["sku"] = catalogo["sku"].astype("string").str.strip()

    from services.data_cleaner import convertir_a_numero

    for columna in ("costo_unitario", "costo_logistico_adicional", "gasto_publicitario"):
        catalogo[columna] = convertir_a_numero(catalogo[columna]).clip(lower=0.0)

    for columna in ("marca", "categoria"):
        catalogo[columna] = catalogo[columna].astype("string").fillna("").str.strip()

    # Un SKU no puede repetirse: se conserva la última captura.
    catalogo = catalogo.loc[catalogo["sku"].notna() & catalogo["sku"].ne("")]
    catalogo = catalogo.drop_duplicates(subset=["sku"], keep="last").reset_index(drop=True)
    return catalogo


def calcular_rentabilidad(
    df: pd.DataFrame,
    catalogo: pd.DataFrame,
    gasto_publicitario_periodo: float = 0.0,
) -> ResultadoRentabilidad:
    """Cruza las ventas del periodo con el catálogo de costos.

    Args:
        df: transacciones limpias y filtradas.
        catalogo: catálogo de costos por SKU (ya normalizado).
        gasto_publicitario_periodo: gasto publicitario global del periodo.  Si es
            mayor que cero se usa en lugar de la suma por SKU del catálogo.

    Returns:
        :class:`ResultadoRentabilidad` con la tabla por SKU y los totales.

    Notas:
        Las **unidades netas** descuentan las devoluciones: el costo de una pieza
        devuelta regresa al inventario, así que no forma parte del costo de la
        mercancía vendida.
    """
    ventas_por_sku = tabla_por_sku(df)

    if ventas_por_sku.empty:
        return ResultadoRentabilidad(pd.DataFrame(), {}, [], 0.0)

    if catalogo is None or catalogo.empty:
        catalogo = catalogo_vacio()

    tabla = ventas_por_sku.merge(
        catalogo.rename(columns={"sku": COL_SKU}), on=COL_SKU, how="left"
    )

    for columna in ("costo_unitario", "costo_logistico_adicional", "gasto_publicitario"):
        if columna not in tabla.columns:
            tabla[columna] = 0.0
        tabla[columna] = pd.to_numeric(tabla[columna], errors="coerce").fillna(0.0)

    for columna in ("marca", "categoria"):
        if columna not in tabla.columns:
            tabla[columna] = ""
        tabla[columna] = tabla[columna].astype("string").fillna("")

    tabla["tiene_costo"] = tabla["costo_unitario"] > 0

    # Unidades netas: vendidas menos devueltas (nunca negativas).
    tabla["unidades_netas"] = (
        tabla["unidades"] - tabla.get("unidades_reembolsadas", 0.0)
    ).clip(lower=0.0)

    tabla["costo_unitario_total"] = tabla["costo_unitario"] + tabla["costo_logistico_adicional"]
    tabla["costo_mercancia"] = tabla["unidades_netas"] * tabla["costo_unitario_total"]

    # Reparto de la publicidad: si el usuario capturó un gasto global, se
    # distribuye proporcional a las ventas de cada SKU.
    ventas_totales = float(tabla["ventas"].sum())
    if gasto_publicitario_periodo > 0 and ventas_totales > 0:
        tabla["publicidad"] = (
            tabla["ventas"] / ventas_totales * gasto_publicitario_periodo
        )
    else:
        tabla["publicidad"] = tabla["gasto_publicitario"]

    tabla["utilidad_antes_publicidad"] = tabla["neto"] - tabla["costo_mercancia"]
    tabla["utilidad"] = tabla["utilidad_antes_publicidad"] - tabla["publicidad"]

    tabla["margen_bruto"] = division_segura_serie(
        tabla["ventas"] - tabla["costo_mercancia"], tabla["ventas"]
    )
    tabla["margen"] = division_segura_serie(tabla["utilidad"], tabla["ventas"])
    tabla["utilidad_por_unidad"] = division_segura_serie(tabla["utilidad"], tabla["unidades_netas"])
    tabla["utilidad_por_pedido"] = division_segura_serie(tabla["utilidad"], tabla["pedidos"])
    tabla["roi"] = division_segura_serie(tabla["utilidad"], tabla["costo_mercancia"])
    tabla["acos"] = division_segura_serie(tabla["publicidad"], tabla["ventas"])

    # Sin costo capturado, la utilidad no significa nada: se anula.
    sin_costo = ~tabla["tiene_costo"]
    for columna in (
        "costo_mercancia", "utilidad_antes_publicidad", "utilidad",
        "margen_bruto", "margen", "utilidad_por_unidad", "utilidad_por_pedido", "roi",
    ):
        tabla.loc[sin_costo, columna] = pd.NA

    skus_sin_costo = tabla.loc[sin_costo, COL_SKU].astype(str).tolist()
    ventas_con_costo = float(tabla.loc[tabla["tiene_costo"], "ventas"].sum())
    cobertura = division_segura(ventas_con_costo, ventas_totales, defecto=0.0) or 0.0

    con_costo = tabla.loc[tabla["tiene_costo"]]
    costo_total = float(pd.to_numeric(con_costo["costo_mercancia"], errors="coerce").sum())
    neto_con_costo = float(con_costo["neto"].sum())
    ventas_con_costo_total = float(con_costo["ventas"].sum())
    publicidad_total = (
        gasto_publicitario_periodo
        if gasto_publicitario_periodo > 0
        else float(tabla["publicidad"].sum())
    )
    utilidad_antes = neto_con_costo - costo_total
    utilidad_final = utilidad_antes - publicidad_total

    metricas = {
        "costo_mercancia": costo_total,
        "utilidad_antes_publicidad": utilidad_antes,
        "utilidad_despues_publicidad": utilidad_final,
        "gasto_publicitario": publicidad_total,
        "margen_bruto": division_segura(
            ventas_con_costo_total - costo_total, ventas_con_costo_total
        ),
        "margen_contribucion": division_segura(utilidad_final, ventas_con_costo_total),
        "utilidad_por_pedido": division_segura(utilidad_final, float(con_costo["pedidos"].sum())),
        "utilidad_por_unidad": division_segura(
            utilidad_final, float(con_costo["unidades_netas"].sum())
        ),
        "roi": division_segura(utilidad_final, costo_total),
        "acos": division_segura(publicidad_total, ventas_con_costo_total),
        "tacos": division_segura(publicidad_total, ventas_totales),
        "cobertura_costos": cobertura,
        "skus_sin_costo": len(skus_sin_costo),
    }

    logger.info(
        "Rentabilidad calculada: %d SKU, cobertura %.1f%%", len(tabla), cobertura * 100
    )

    return ResultadoRentabilidad(
        tabla=tabla,
        metricas=metricas,
        skus_sin_costo=skus_sin_costo,
        cobertura=cobertura,
    )


def plantilla_catalogo(skus: list[str]) -> pd.DataFrame:
    """Plantilla de captura precargada con los SKU vendidos en el periodo."""
    return pd.DataFrame({
        "sku": pd.Series(skus, dtype="string"),
        "costo_unitario": 0.0,
        "costo_logistico_adicional": 0.0,
        "gasto_publicitario": 0.0,
        "marca": pd.Series([""] * len(skus), dtype="string"),
        "categoria": pd.Series([""] * len(skus), dtype="string"),
    })


def combinar_catalogos(existente: pd.DataFrame, nuevo: pd.DataFrame) -> pd.DataFrame:
    """Fusiona dos catálogos: los SKU del nuevo sobrescriben a los del existente."""
    if existente is None or existente.empty:
        return normalizar_catalogo(nuevo)
    if nuevo is None or nuevo.empty:
        return normalizar_catalogo(existente)
    unido = pd.concat([normalizar_catalogo(existente), normalizar_catalogo(nuevo)], ignore_index=True)
    return unido.drop_duplicates(subset=["sku"], keep="last").reset_index(drop=True)

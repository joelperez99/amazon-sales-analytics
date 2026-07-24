"""Motor de métricas.

Aquí viven **todas** las fórmulas del tablero.  Ninguna página calcula por su
cuenta: todas piden los números a este módulo, de modo que una tarjeta, una
gráfica y una hoja de Excel siempre muestran el mismo valor.

Reglas de cálculo que se respetan en todo el módulo
---------------------------------------------------
1. Los pedidos se cuentan con ``nunique(id_pedido)``, nunca con el número de
   filas: un pedido con varias líneas o varios SKU cuenta una sola vez.
2. Las unidades vienen de la columna ``cantidad``, no del conteo de filas.
3. Solo las filas de tipo **Pedido** generan ventas y unidades.
4. Las **transferencias** se excluyen de todos los importes: representan el
   retiro del dinero a la cuenta bancaria y contarlas duplicaría la salida.
5. Los cargos conservan su signo negativo durante el cálculo; el valor absoluto
   se usa **solo** para presentar.
6. Toda división pasa por ``division_segura``: nunca hay división entre cero.
7. Se redondea únicamente al presentar, jamás durante el cálculo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from utils.constants import (
    COL_CANTIDAD,
    COL_CIUDAD,
    COL_DESCRIPCION,
    COL_ESTADO,
    COL_FECHA,
    COL_FECHA_DIA,
    COL_FECHA_LIBERACION,
    COL_LIQUIDACION,
    COL_OTRO,
    COL_PEDIDO,
    COL_RETENCIONES,
    COL_SKU,
    COL_TARIFA_REGLAMENTARIA,
    COL_TARIFAS_FBA,
    COL_TARIFAS_OTRAS,
    COL_TARIFAS_VENTA,
    COL_TIPO,
    COL_TOTAL,
    COL_VENTAS,
    COL_DESCUENTOS,
    COLUMNAS_COMPONENTES_NETO,
    COLUMNAS_IMPUESTOS,
    TIPO_AJUSTE,
    TIPO_PEDIDO,
    TIPO_REEMBOLSO,
    TIPO_TARIFA_INVENTARIO,
    TIPO_TARIFA_SERVICIO,
    TIPOS_EXCLUIDOS_DEL_NETO,
)
from utils.formatting import division_segura, division_segura_serie
from utils.logger import get_logger

logger = get_logger("metrics_service")


# =============================================================================
# Particiones del DataFrame por tipo de transacción
# =============================================================================


@dataclass
class Particiones:
    """El mismo periodo visto por tipo de transacción.

    Separar el DataFrame una sola vez evita repetir el filtrado en cada métrica.
    """

    completo: pd.DataFrame
    financiero: pd.DataFrame       # todo menos transferencias
    pedidos: pd.DataFrame
    reembolsos: pd.DataFrame
    ajustes: pd.DataFrame
    inventario: pd.DataFrame
    servicio: pd.DataFrame
    transferencias: pd.DataFrame


def particionar(df: pd.DataFrame) -> Particiones:
    """Divide el DataFrame por tipo de transacción."""
    if df.empty or COL_TIPO not in df.columns:
        vacio = df.iloc[0:0] if not df.empty else df
        return Particiones(df, df, vacio, vacio, vacio, vacio, vacio, vacio)

    tipo = df[COL_TIPO].astype("string")
    es_transferencia = tipo.isin(TIPOS_EXCLUIDOS_DEL_NETO)

    return Particiones(
        completo=df,
        financiero=df.loc[~es_transferencia],
        pedidos=df.loc[tipo == TIPO_PEDIDO],
        reembolsos=df.loc[tipo == TIPO_REEMBOLSO],
        ajustes=df.loc[tipo == TIPO_AJUSTE],
        inventario=df.loc[tipo == TIPO_TARIFA_INVENTARIO],
        servicio=df.loc[tipo == TIPO_TARIFA_SERVICIO],
        transferencias=df.loc[es_transferencia],
    )


def _suma(df: pd.DataFrame, columna: str) -> float:
    """Suma una columna aunque no exista (devuelve 0.0)."""
    if df.empty or columna not in df.columns:
        return 0.0
    valor = pd.to_numeric(df[columna], errors="coerce").sum()
    return float(valor) if pd.notna(valor) else 0.0


def _suma_varias(df: pd.DataFrame, columnas: list[str]) -> float:
    """Suma varias columnas de una sola vez."""
    return float(sum(_suma(df, c) for c in columnas))


def _nunique(df: pd.DataFrame, columna: str) -> int:
    """Cuenta valores distintos no vacíos de una columna."""
    if df.empty or columna not in df.columns:
        return 0
    serie = df[columna].astype("string").str.strip()
    serie = serie[serie.notna() & serie.ne("") & ~serie.isin(["Sin SKU", "Sin descripción"])]
    return int(serie.nunique())


# =============================================================================
# Cálculo de KPI
# =============================================================================


def calcular_metricas(df: pd.DataFrame) -> dict[str, Any]:
    """Calcula el conjunto completo de indicadores del periodo.

    Args:
        df: DataFrame limpio y ya filtrado por el usuario.

    Returns:
        Diccionario ``clave -> valor``.  Las claves coinciden con las del
        ``DICCIONARIO_METRICAS`` para poder mostrar la fórmula en un tooltip.
        Las métricas que no pueden calcularse valen ``None`` (se muestran «N/D»).
    """
    p = particionar(df)
    m: dict[str, Any] = {}

    # -------------------------------------------------------------- Ventas ---
    ventas_brutas = _suma(p.pedidos, COL_VENTAS)
    impuestos = _suma_varias(p.pedidos, COLUMNAS_IMPUESTOS)
    pedidos_unicos = _nunique(p.pedidos, COL_PEDIDO)
    unidades = _suma(p.pedidos, COL_CANTIDAD)

    m["ventas_brutas"] = ventas_brutas
    m["impuestos_cobrados"] = impuestos
    m["ventas_con_impuestos"] = ventas_brutas + impuestos
    m["pedidos_unicos"] = pedidos_unicos
    m["transacciones"] = int(len(p.financiero))
    m["unidades"] = unidades
    m["ticket_promedio"] = division_segura(ventas_brutas, pedidos_unicos)
    m["precio_promedio_unidad"] = division_segura(ventas_brutas, unidades)
    m["unidades_por_pedido"] = division_segura(unidades, pedidos_unicos)
    m["skus_vendidos"] = _nunique(p.pedidos, COL_SKU)
    m["productos_vendidos"] = _nunique(p.pedidos, COL_DESCRIPCION)

    dias = _dias_del_periodo(df)
    m["dias_periodo"] = dias
    m["ventas_por_dia"] = division_segura(ventas_brutas, dias)
    m["pedidos_por_dia"] = division_segura(pedidos_unicos, dias)
    m["unidades_por_dia"] = division_segura(unidades, dias)

    # ------------------------------------------------------------- Tarifas ---
    # Los cargos son negativos en el archivo. Se conserva el signo para sumar y
    # se presenta el valor absoluto. Los reembolsos devuelven parte de la
    # comisión (valor positivo) y quedan netados de forma natural.
    tarifas_venta_neto = _suma(p.financiero, COL_TARIFAS_VENTA)
    tarifas_fba_neto = _suma(p.financiero, COL_TARIFAS_FBA)
    tarifas_otras_neto = _suma(p.financiero, COL_TARIFAS_OTRAS)
    tarifa_reglamentaria_neto = _suma(p.financiero, COL_TARIFA_REGLAMENTARIA)
    retenciones_neto = _suma(p.financiero, COL_RETENCIONES)
    descuentos_neto = _suma(p.financiero, COL_DESCUENTOS)

    m["tarifas_venta"] = abs(tarifas_venta_neto)
    m["tarifas_fba"] = abs(tarifas_fba_neto)
    m["tarifas_otras"] = abs(tarifas_otras_neto)
    m["tarifa_reglamentaria"] = abs(tarifa_reglamentaria_neto)
    m["retenciones"] = abs(retenciones_neto)
    m["descuentos_promocionales"] = abs(descuentos_neto)
    m["tarifas_inventario"] = abs(_suma(p.inventario, COL_TOTAL))
    m["tarifas_servicio"] = abs(_suma(p.servicio, COL_TOTAL))
    m["ajustes"] = _suma(p.ajustes, COL_TOTAL)

    # «Otros cargos»: solo la parte negativa de la columna «otro».  Es donde
    # Amazon deposita el almacenamiento, la suscripción y los ajustes, así que
    # capturarla aquí evita contarlos dos veces con las métricas por tipo.
    otros_cargos = _suma_negativos(p.financiero, COL_OTRO)
    m["otros_cargos"] = abs(otros_cargos)

    cargos_columnas = (
        tarifas_venta_neto + tarifas_fba_neto + tarifas_otras_neto + tarifa_reglamentaria_neto
    )
    # Cargos que llegaron solo en «total» y no aparecen en ninguna columna de
    # detalle: se recuperan para que no se pierdan del total de cargos.
    cargos_residuales = _cargos_no_capturados(p.financiero)
    total_cargos = abs(cargos_columnas) + abs(otros_cargos) + abs(cargos_residuales)

    m["total_cargos"] = total_cargos
    m["cargos_residuales"] = abs(cargos_residuales)
    m["tarifa_por_pedido"] = division_segura(total_cargos, pedidos_unicos)
    m["tarifa_por_unidad"] = division_segura(total_cargos, unidades)
    m["pct_comisiones"] = division_segura(abs(tarifas_venta_neto), ventas_brutas)
    m["pct_fba"] = division_segura(abs(tarifas_fba_neto), ventas_brutas)
    m["pct_cargos"] = division_segura(total_cargos, ventas_brutas)

    # ----------------------------------------------------------- Reembolsos ---
    importe_reembolsado = abs(_suma(p.reembolsos, COL_TOTAL))
    unidades_reembolsadas = abs(_suma(p.reembolsos, COL_CANTIDAD))
    pedidos_reembolsados = _nunique(p.reembolsos, COL_PEDIDO)

    m["pedidos_reembolsados"] = pedidos_reembolsados
    m["transacciones_reembolso"] = int(len(p.reembolsos))
    m["unidades_reembolsadas"] = unidades_reembolsadas
    m["importe_reembolsado"] = importe_reembolsado
    m["ventas_reembolsadas"] = abs(_suma(p.reembolsos, COL_VENTAS))
    m["pct_pedidos_reembolsados"] = division_segura(pedidos_reembolsados, pedidos_unicos)
    m["pct_unidades_reembolsadas"] = division_segura(unidades_reembolsadas, unidades)
    m["tasa_reembolso"] = division_segura(importe_reembolsado, ventas_brutas)

    # --------------------------------------------------------------- Neto ----
    neto = _suma(p.financiero, COL_TOTAL)
    neto_reconstruido = _suma_varias(p.financiero, COLUMNAS_COMPONENTES_NETO)

    m["neto"] = neto
    m["neto_reconstruido"] = neto_reconstruido
    m["diferencia_conciliacion"] = neto - neto_reconstruido
    m["neto_por_pedido"] = division_segura(neto, pedidos_unicos)
    m["neto_por_unidad"] = division_segura(neto, unidades)
    m["neto_por_sku"] = division_segura(neto, m["skus_vendidos"])
    m["neto_por_producto"] = division_segura(neto, m["productos_vendidos"])
    m["margen_neto"] = division_segura(neto, ventas_brutas)
    m["pct_neto"] = m["margen_neto"]

    # ------------------------------------------------------ Transferencias ---
    m["transferencias"] = abs(_suma(p.transferencias, COL_TOTAL))
    m["num_transferencias"] = int(len(p.transferencias))

    # ------------------------------------------------------------ Periodo ----
    m["fecha_inicio"], m["fecha_fin"] = _rango_fechas(df)

    return m


def _suma_negativos(df: pd.DataFrame, columna: str) -> float:
    """Suma únicamente los valores negativos de una columna."""
    if df.empty or columna not in df.columns:
        return 0.0
    serie = pd.to_numeric(df[columna], errors="coerce").fillna(0.0)
    return float(serie.where(serie < 0, 0.0).sum())


def _cargos_no_capturados(df: pd.DataFrame) -> float:
    """Cargos negativos que no aparecen en ninguna columna de detalle.

    Algunos reportes registran una tarifa solo en la columna ``total``, dejando
    en cero todas las columnas de detalle.  Esas filas se recuperan aquí para
    que el «Total de cargos Amazon» no se quede corto, y se excluyen las que ya
    quedaron contadas en ``otro`` o en las columnas de tarifas.
    """
    if df.empty or COL_TOTAL not in df.columns:
        return 0.0

    columnas_detalle = [
        c for c in COLUMNAS_COMPONENTES_NETO if c in df.columns
    ]
    if not columnas_detalle:
        return 0.0

    detalle = df[columnas_detalle].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    total = pd.to_numeric(df[COL_TOTAL], errors="coerce").fillna(0.0)

    sin_detalle = detalle.abs().sum(axis=1).eq(0.0)
    negativo = total < 0
    return float(total.where(sin_detalle & negativo, 0.0).sum())


def _dias_del_periodo(df: pd.DataFrame) -> int:
    """Días naturales cubiertos por el periodo (mínimo 1)."""
    if df.empty or COL_FECHA not in df.columns:
        return 1
    fechas = pd.to_datetime(df[COL_FECHA], errors="coerce").dropna()
    if fechas.empty:
        return 1
    dias = (fechas.max().normalize() - fechas.min().normalize()).days + 1
    return max(int(dias), 1)


def _rango_fechas(df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Primera y última fecha del periodo."""
    if df.empty or COL_FECHA not in df.columns:
        return None, None
    fechas = pd.to_datetime(df[COL_FECHA], errors="coerce").dropna()
    if fechas.empty:
        return None, None
    return fechas.min(), fechas.max()


# =============================================================================
# Series temporales
# =============================================================================

#: Etiqueta de agrupación -> regla de resample de pandas.
FRECUENCIAS: dict[str, str] = {"Día": "D", "Semana": "W-MON", "Mes": "MS"}


def serie_temporal(df: pd.DataFrame, frecuencia: str = "Día") -> pd.DataFrame:
    """Evolución de los indicadores por día, semana o mes.

    Returns:
        DataFrame con una fila por periodo y las columnas ``periodo``, ``ventas``,
        ``pedidos``, ``unidades``, ``impuestos``, ``tarifas``, ``reembolsos``,
        ``neto`` y ``ticket_promedio``.
    """
    columnas = [
        "periodo", "ventas", "pedidos", "unidades", "impuestos",
        "tarifas", "reembolsos", "neto", "ticket_promedio",
    ]
    if df.empty or COL_FECHA not in df.columns:
        return pd.DataFrame(columns=columnas)

    regla = FRECUENCIAS.get(frecuencia, "D")
    p = particionar(df)

    base = df.copy()
    base[COL_FECHA] = pd.to_datetime(base[COL_FECHA], errors="coerce")
    base = base.dropna(subset=[COL_FECHA])
    if base.empty:
        return pd.DataFrame(columns=columnas)

    periodo = base[COL_FECHA].dt.to_period(_periodo_pandas(regla)).dt.start_time
    base = base.assign(_periodo=periodo)

    tipo = base[COL_TIPO].astype("string") if COL_TIPO in base.columns else pd.Series("", index=base.index)
    es_pedido = tipo == TIPO_PEDIDO
    es_reembolso = tipo == TIPO_REEMBOLSO
    es_transferencia = tipo.isin(TIPOS_EXCLUIDOS_DEL_NETO)

    # Columnas auxiliares: cada métrica se calcula en su propia columna para
    # poder agregarlas todas en una sola pasada de groupby (vectorizado).
    aux = pd.DataFrame({"_periodo": base["_periodo"]}, index=base.index)
    aux["ventas"] = base[COL_VENTAS].where(es_pedido, 0.0) if COL_VENTAS in base else 0.0
    aux["unidades"] = base[COL_CANTIDAD].where(es_pedido, 0.0) if COL_CANTIDAD in base else 0.0
    aux["impuestos"] = sum(
        base[c].where(es_pedido, 0.0) for c in COLUMNAS_IMPUESTOS if c in base.columns
    )
    aux["tarifas"] = -sum(
        base[c].where(~es_transferencia, 0.0)
        for c in (COL_TARIFAS_VENTA, COL_TARIFAS_FBA, COL_TARIFAS_OTRAS, COL_TARIFA_REGLAMENTARIA)
        if c in base.columns
    )
    aux["reembolsos"] = (
        -base[COL_TOTAL].where(es_reembolso, 0.0) if COL_TOTAL in base else 0.0
    )
    aux["neto"] = base[COL_TOTAL].where(~es_transferencia, 0.0) if COL_TOTAL in base else 0.0
    aux["_pedido_id"] = (
        base[COL_PEDIDO].astype("string").where(es_pedido, pd.NA)
        if COL_PEDIDO in base.columns
        else pd.NA
    )

    agrupado = aux.groupby("_periodo", observed=True).agg(
        ventas=("ventas", "sum"),
        unidades=("unidades", "sum"),
        impuestos=("impuestos", "sum"),
        tarifas=("tarifas", "sum"),
        reembolsos=("reembolsos", "sum"),
        neto=("neto", "sum"),
        pedidos=("_pedido_id", "nunique"),
    )

    # Rellena los periodos sin movimiento para que la línea no tenga huecos.
    if not agrupado.empty and regla == "D":
        rango = pd.date_range(agrupado.index.min(), agrupado.index.max(), freq="D")
        agrupado = agrupado.reindex(rango, fill_value=0)

    agrupado = agrupado.reset_index().rename(columns={"index": "_periodo"})
    agrupado = agrupado.rename(columns={"_periodo": "periodo"})
    agrupado["ticket_promedio"] = division_segura_serie(
        agrupado["ventas"], agrupado["pedidos"]
    )
    return agrupado[columnas]


def _periodo_pandas(regla: str) -> str:
    """Traduce la regla de resample al código de ``to_period``."""
    return {"D": "D", "W-MON": "W-MON", "MS": "M"}.get(regla, "D")


# =============================================================================
# Agregados por dimensión
# =============================================================================


def _agregado_por_dimension(df: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Motor común de los resúmenes por SKU, estado, ciudad o liquidación.

    Todo se resuelve con un solo ``groupby``: nunca se recorre el DataFrame.
    """
    if df.empty or dimension not in df.columns:
        return pd.DataFrame()

    base = df.copy()
    tipo = base[COL_TIPO].astype("string") if COL_TIPO in base.columns else pd.Series("", index=base.index)
    es_pedido = tipo == TIPO_PEDIDO
    es_reembolso = tipo == TIPO_REEMBOLSO
    es_transferencia = tipo.isin(TIPOS_EXCLUIDOS_DEL_NETO)

    aux = pd.DataFrame(index=base.index)
    aux[dimension] = base[dimension].astype("string").fillna("Sin dato")
    aux["ventas"] = base[COL_VENTAS].where(es_pedido, 0.0)
    aux["unidades"] = base[COL_CANTIDAD].where(es_pedido, 0.0)
    aux["impuestos"] = sum(base[c].where(es_pedido, 0.0) for c in COLUMNAS_IMPUESTOS if c in base.columns)
    aux["descuentos"] = -base[COL_DESCUENTOS].where(~es_transferencia, 0.0)
    aux["tarifas_venta"] = -base[COL_TARIFAS_VENTA].where(~es_transferencia, 0.0)
    aux["tarifas_fba"] = -base[COL_TARIFAS_FBA].where(~es_transferencia, 0.0)
    aux["retenciones"] = -base[COL_RETENCIONES].where(~es_transferencia, 0.0)
    aux["otros_cargos"] = -(
        base[COL_TARIFAS_OTRAS].where(~es_transferencia, 0.0)
        + base[COL_TARIFA_REGLAMENTARIA].where(~es_transferencia, 0.0)
        + base[COL_OTRO].where(~es_transferencia, 0.0).clip(upper=0.0)
    )
    aux["reembolsos"] = -base[COL_TOTAL].where(es_reembolso, 0.0)
    # La cantidad de un reembolso puede venir positiva (1 pieza devuelta) o
    # negativa según el reporte: se toma la magnitud para no invertir el signo.
    aux["unidades_reembolsadas"] = base[COL_CANTIDAD].where(es_reembolso, 0.0).abs()
    aux["neto"] = base[COL_TOTAL].where(~es_transferencia, 0.0)
    aux["_pedido"] = (
        base[COL_PEDIDO].astype("string").where(es_pedido, pd.NA)
        if COL_PEDIDO in base.columns
        else pd.NA
    )
    aux["_pedido_reembolso"] = (
        base[COL_PEDIDO].astype("string").where(es_reembolso, pd.NA)
        if COL_PEDIDO in base.columns
        else pd.NA
    )
    aux["transacciones"] = 1

    resumen = aux.groupby(dimension, observed=True).agg(
        pedidos=("_pedido", "nunique"),
        pedidos_reembolsados=("_pedido_reembolso", "nunique"),
        transacciones=("transacciones", "sum"),
        ventas=("ventas", "sum"),
        unidades=("unidades", "sum"),
        impuestos=("impuestos", "sum"),
        descuentos=("descuentos", "sum"),
        tarifas_venta=("tarifas_venta", "sum"),
        tarifas_fba=("tarifas_fba", "sum"),
        retenciones=("retenciones", "sum"),
        otros_cargos=("otros_cargos", "sum"),
        reembolsos=("reembolsos", "sum"),
        unidades_reembolsadas=("unidades_reembolsadas", "sum"),
        neto=("neto", "sum"),
    )

    resumen["total_cargos"] = (
        resumen["tarifas_venta"] + resumen["tarifas_fba"] + resumen["otros_cargos"]
    )
    ventas_totales = float(resumen["ventas"].sum())
    resumen["precio_promedio"] = division_segura_serie(resumen["ventas"], resumen["unidades"])
    resumen["ticket_promedio"] = division_segura_serie(resumen["ventas"], resumen["pedidos"])
    resumen["tarifa_por_unidad"] = division_segura_serie(resumen["total_cargos"], resumen["unidades"])
    resumen["neto_por_unidad"] = division_segura_serie(resumen["neto"], resumen["unidades"])
    resumen["neto_por_pedido"] = division_segura_serie(resumen["neto"], resumen["pedidos"])
    resumen["pct_cargos"] = division_segura_serie(resumen["total_cargos"], resumen["ventas"])
    resumen["margen_neto"] = division_segura_serie(resumen["neto"], resumen["ventas"])
    resumen["participacion"] = resumen["ventas"] / ventas_totales if ventas_totales else 0.0
    resumen["tasa_reembolso"] = division_segura_serie(resumen["reembolsos"], resumen["ventas"])

    return resumen.reset_index().sort_values("ventas", ascending=False)


def tabla_por_sku(df: pd.DataFrame) -> pd.DataFrame:
    """Resumen por SKU con todas las columnas de la tabla de productos."""
    resumen = _agregado_por_dimension(df, COL_SKU)
    if resumen.empty:
        return resumen

    # Agrega la descripción más frecuente de cada SKU.
    if COL_DESCRIPCION in df.columns:
        descripciones = (
            df.loc[df[COL_SKU].notna(), [COL_SKU, COL_DESCRIPCION]]
            .astype("string")
            .groupby(COL_SKU, observed=True)[COL_DESCRIPCION]
            .agg(lambda s: s.mode().iat[0] if not s.mode().empty else "")
            .rename("descripcion")
        )
        resumen = resumen.merge(descripciones, on=COL_SKU, how="left")
        resumen["descripcion"] = resumen["descripcion"].fillna("Sin descripción")

    # Curva de Pareto: participación acumulada ordenada de mayor a menor venta.
    resumen = resumen.sort_values("ventas", ascending=False).reset_index(drop=True)
    resumen["participacion_acumulada"] = resumen["participacion"].cumsum()
    return resumen


def tabla_por_estado(df: pd.DataFrame) -> pd.DataFrame:
    """Resumen geográfico por estado."""
    return _agregado_por_dimension(df, COL_ESTADO)


def tabla_por_ciudad(df: pd.DataFrame) -> pd.DataFrame:
    """Resumen geográfico por ciudad."""
    return _agregado_por_dimension(df, COL_CIUDAD)


def tabla_por_producto(df: pd.DataFrame) -> pd.DataFrame:
    """Resumen agrupado por descripción del producto."""
    return _agregado_por_dimension(df, COL_DESCRIPCION)


def tabla_por_tipo(df: pd.DataFrame) -> pd.DataFrame:
    """Importe y número de transacciones por tipo (incluye transferencias)."""
    if df.empty or COL_TIPO not in df.columns:
        return pd.DataFrame(columns=["tipo", "transacciones", "importe", "participacion"])

    resumen = (
        df.assign(_uno=1)
        .groupby(COL_TIPO, observed=True)
        .agg(transacciones=("_uno", "sum"), importe=(COL_TOTAL, "sum"))
        .reset_index()
        .rename(columns={COL_TIPO: "tipo"})
    )
    total = resumen["importe"].abs().sum()
    resumen["participacion"] = resumen["importe"].abs() / total if total else 0.0
    return resumen.sort_values("importe", ascending=False)


def tabla_liquidaciones(df: pd.DataFrame) -> pd.DataFrame:
    """Conciliación por Id. de liquidación.

    Cada liquidación muestra su ventana de fechas, importes por concepto, número
    de transacciones y la fecha de liberación más reciente.
    """
    if df.empty or COL_LIQUIDACION not in df.columns:
        return pd.DataFrame()

    base = df.copy()
    tipo = base[COL_TIPO].astype("string") if COL_TIPO in base.columns else pd.Series("", index=base.index)
    es_pedido = tipo == TIPO_PEDIDO
    es_reembolso = tipo == TIPO_REEMBOLSO
    es_ajuste = tipo == TIPO_AJUSTE
    es_transferencia = tipo.isin(TIPOS_EXCLUIDOS_DEL_NETO)

    aux = pd.DataFrame(index=base.index)
    aux[COL_LIQUIDACION] = base[COL_LIQUIDACION].astype("string").fillna("Sin liquidación")
    aux["fecha"] = pd.to_datetime(base[COL_FECHA], errors="coerce")
    aux["fecha_liberacion"] = (
        pd.to_datetime(base[COL_FECHA_LIBERACION], errors="coerce")
        if COL_FECHA_LIBERACION in base.columns
        else pd.NaT
    )
    aux["ventas"] = base[COL_VENTAS].where(es_pedido, 0.0)
    aux["reembolsos"] = -base[COL_TOTAL].where(es_reembolso, 0.0)
    aux["ajustes"] = base[COL_TOTAL].where(es_ajuste, 0.0)
    aux["tarifas"] = -(
        base[COL_TARIFAS_VENTA].where(~es_transferencia, 0.0)
        + base[COL_TARIFAS_FBA].where(~es_transferencia, 0.0)
        + base[COL_TARIFAS_OTRAS].where(~es_transferencia, 0.0)
    )
    aux["neto"] = base[COL_TOTAL].where(~es_transferencia, 0.0)
    aux["transferido"] = -base[COL_TOTAL].where(es_transferencia, 0.0)
    aux["_pedido"] = (
        base[COL_PEDIDO].astype("string").where(es_pedido, pd.NA)
        if COL_PEDIDO in base.columns
        else pd.NA
    )
    aux["_uno"] = 1

    resumen = (
        aux.groupby(COL_LIQUIDACION, observed=True)
        .agg(
            fecha_inicial=("fecha", "min"),
            fecha_final=("fecha", "max"),
            fecha_liberacion=("fecha_liberacion", "max"),
            pedidos=("_pedido", "nunique"),
            transacciones=("_uno", "sum"),
            ventas=("ventas", "sum"),
            reembolsos=("reembolsos", "sum"),
            tarifas=("tarifas", "sum"),
            ajustes=("ajustes", "sum"),
            neto=("neto", "sum"),
            transferido=("transferido", "sum"),
        )
        .reset_index()
    )

    if "estado_transaccion" in base.columns:
        # ``astype("string")`` es indispensable: la columna puede venir como
        # ``category`` y entonces no acepta el relleno "Sin estado".
        estados = (
            base.assign(
                _liq=base[COL_LIQUIDACION].astype("string").fillna("Sin liquidación"),
                _estado=base["estado_transaccion"].astype("string"),
            )
            .groupby("_liq", observed=True)["_estado"]
            .agg(lambda s: s.mode().iat[0] if not s.mode().empty else "Sin estado")
            .rename("estado")
        )
        resumen = resumen.merge(
            estados, left_on=COL_LIQUIDACION, right_index=True, how="left"
        )
        resumen["estado"] = resumen["estado"].astype("string").fillna("Sin estado")

    return resumen.sort_values("fecha_inicial")


def tabla_reembolsos(df: pd.DataFrame) -> pd.DataFrame:
    """Detalle de los reembolsos del periodo."""
    if df.empty or COL_TIPO not in df.columns:
        return pd.DataFrame()
    reembolsos = df.loc[df[COL_TIPO].astype("string") == TIPO_REEMBOLSO]
    if reembolsos.empty:
        return pd.DataFrame()
    columnas = [
        c for c in (
            COL_FECHA, COL_PEDIDO, COL_SKU, COL_DESCRIPCION, COL_CANTIDAD,
            COL_ESTADO, COL_CIUDAD, COL_VENTAS, COL_TARIFAS_VENTA, COL_TOTAL,
            COL_LIQUIDACION,
        ) if c in reembolsos.columns
    ]
    return reembolsos[columnas].sort_values(COL_FECHA, ascending=False)


def detalle_pedidos(df: pd.DataFrame) -> pd.DataFrame:
    """Vista de detalle a nivel transacción para la tabla de pedidos."""
    columnas = [
        c for c in (
            COL_FECHA, COL_PEDIDO, COL_TIPO, COL_SKU, COL_DESCRIPCION, COL_CANTIDAD,
            COL_ESTADO, COL_CIUDAD, COL_VENTAS, COL_TARIFAS_VENTA, COL_TARIFAS_FBA,
            COL_RETENCIONES, COL_TOTAL, "estado_transaccion", COL_FECHA_LIBERACION,
            COL_LIQUIDACION,
        ) if c in df.columns
    ]
    # Los impuestos se agregan en una sola columna para no saturar la tabla.
    vista = df[columnas].copy()
    impuestos = [c for c in COLUMNAS_IMPUESTOS if c in df.columns]
    vista.insert(
        min(len(vista.columns), 9),
        "impuestos",
        df[impuestos].sum(axis=1) if impuestos else 0.0,
    )
    return vista.sort_values(COL_FECHA, ascending=False)


def resumen_pedidos(df: pd.DataFrame) -> pd.DataFrame:
    """Un renglón por pedido, con sus líneas consolidadas."""
    if df.empty or COL_PEDIDO not in df.columns:
        return pd.DataFrame()

    base = df.loc[df[COL_PEDIDO].astype("string").fillna("").ne("")].copy()
    if base.empty:
        return pd.DataFrame()

    tipo = base[COL_TIPO].astype("string")
    es_pedido = tipo == TIPO_PEDIDO
    es_reembolso = tipo == TIPO_REEMBOLSO

    aux = pd.DataFrame(index=base.index)
    aux[COL_PEDIDO] = base[COL_PEDIDO].astype("string")
    aux["fecha"] = pd.to_datetime(base[COL_FECHA], errors="coerce")
    aux["ventas"] = base[COL_VENTAS].where(es_pedido, 0.0)
    aux["unidades"] = base[COL_CANTIDAD].where(es_pedido, 0.0)
    aux["reembolsado"] = -base[COL_TOTAL].where(es_reembolso, 0.0)
    aux["neto"] = base[COL_TOTAL]
    aux["_sku"] = base[COL_SKU].astype("string")
    aux["_lineas"] = 1
    aux["estado"] = base[COL_ESTADO].astype("string")
    aux["ciudad"] = base[COL_CIUDAD].astype("string")

    resumen = (
        aux.groupby(COL_PEDIDO, observed=True)
        .agg(
            fecha=("fecha", "min"),
            lineas=("_lineas", "sum"),
            skus=("_sku", "nunique"),
            unidades=("unidades", "sum"),
            ventas=("ventas", "sum"),
            reembolsado=("reembolsado", "sum"),
            neto=("neto", "sum"),
            estado=("estado", "first"),
            ciudad=("ciudad", "first"),
        )
        .reset_index()
    )
    return resumen.sort_values("fecha", ascending=False)


def curva_pareto(tabla_sku: pd.DataFrame) -> pd.DataFrame:
    """Prepara los datos de la curva 80/20 a partir de la tabla por SKU."""
    if tabla_sku.empty:
        return pd.DataFrame(columns=[COL_SKU, "ventas", "participacion_acumulada", "rango"])
    orden = tabla_sku.sort_values("ventas", ascending=False).reset_index(drop=True)
    total = float(orden["ventas"].sum())
    orden["participacion_acumulada"] = (
        orden["ventas"].cumsum() / total if total else 0.0
    )
    orden["rango"] = np.arange(1, len(orden) + 1)
    return orden[[COL_SKU, "ventas", "participacion_acumulada", "rango"]]


def desglose_cascada(df: pd.DataFrame) -> pd.DataFrame:
    """Datos de la gráfica waterfall: de las ventas al neto depositable.

    Se construye sumando **columnas**, no métricas ya agregadas, de modo que los
    escalones cierran exactamente en el neto.  Cada escalón incluye ya el efecto
    de los reembolsos: una devolución resta en «Ventas de productos» y devuelve
    parte de la comisión en «Tarifas de venta».  Poner además un escalón
    «Reembolsos» contaría dos veces el mismo dinero.
    """
    conceptos: list[tuple[str, list[str]]] = [
        ("Ventas de productos", [COL_VENTAS]),
        ("Impuestos cobrados", COLUMNAS_IMPUESTOS),
        ("Créditos de envío y envoltorio", ["creditos_envio", "creditos_envoltorio"]),
        ("Descuentos promocionales", [COL_DESCUENTOS, "impuesto_descuentos_promocionales"]),
        ("Retenciones de impuestos", [COL_RETENCIONES]),
        ("Tarifas de venta", [COL_TARIFAS_VENTA]),
        ("Tarifas FBA", [COL_TARIFAS_FBA]),
        ("Otras tarifas", [COL_TARIFAS_OTRAS, COL_TARIFA_REGLAMENTARIA]),
        ("Otros cargos y ajustes", [COL_OTRO]),
    ]

    financiero = particionar(df).financiero
    filas: list[tuple[str, float, str]] = []
    for indice, (etiqueta, columnas) in enumerate(conceptos):
        importe = _suma_varias(financiero, columnas)
        # El primer escalón es la base absoluta; el resto son incrementos.
        filas.append((etiqueta, importe, "absoluto" if indice == 0 else "relativo"))

    filas.append(("Neto depositable", _suma(financiero, COL_TOTAL), "total"))
    return pd.DataFrame(filas, columns=["concepto", "importe", "tipo"])


def desglose_tarifas(metricas: dict[str, Any]) -> pd.DataFrame:
    """Composición de los cargos de Amazon, ordenada de mayor a menor."""
    filas = [
        ("Tarifas de venta", metricas.get("tarifas_venta", 0.0)),
        ("Tarifas FBA", metricas.get("tarifas_fba", 0.0)),
        ("Tarifas de inventario FBA", metricas.get("tarifas_inventario", 0.0)),
        ("Tarifas de servicio", metricas.get("tarifas_servicio", 0.0)),
        ("Tarifas de otras transacciones", metricas.get("tarifas_otras", 0.0)),
        ("Tarifa reglamentaria", metricas.get("tarifa_reglamentaria", 0.0)),
        ("Descuentos promocionales", metricas.get("descuentos_promocionales", 0.0)),
    ]
    tabla = pd.DataFrame(filas, columns=["concepto", "importe"])
    tabla = tabla.loc[tabla["importe"] > 0].sort_values("importe", ascending=False)
    total = float(tabla["importe"].sum())
    tabla["participacion"] = tabla["importe"] / total if total else 0.0
    return tabla.reset_index(drop=True)


def sku_sin_ventas_recientes(df: pd.DataFrame, dias: int = 7) -> pd.DataFrame:
    """SKU que dejaron de venderse en los últimos ``dias`` del periodo."""
    if df.empty or COL_SKU not in df.columns or COL_FECHA not in df.columns:
        return pd.DataFrame(columns=[COL_SKU, "ultima_venta", "dias_sin_venta"])

    pedidos = df.loc[df[COL_TIPO].astype("string") == TIPO_PEDIDO] if COL_TIPO in df.columns else df
    if pedidos.empty:
        return pd.DataFrame(columns=[COL_SKU, "ultima_venta", "dias_sin_venta"])

    fechas = pd.to_datetime(pedidos[COL_FECHA], errors="coerce")
    ultima_global = fechas.max()
    if pd.isna(ultima_global):
        return pd.DataFrame(columns=[COL_SKU, "ultima_venta", "dias_sin_venta"])

    ultima_por_sku = (
        pedidos.assign(_fecha=fechas)
        .groupby(pedidos[COL_SKU].astype("string"), observed=True)["_fecha"]
        .max()
        .rename("ultima_venta")
        .reset_index()
        .rename(columns={pedidos[COL_SKU].name: COL_SKU})
    )
    ultima_por_sku.columns = [COL_SKU, "ultima_venta"]
    ultima_por_sku["dias_sin_venta"] = (
        (ultima_global.normalize() - ultima_por_sku["ultima_venta"].dt.normalize()).dt.days
    )
    return (
        ultima_por_sku.loc[ultima_por_sku["dias_sin_venta"] >= dias]
        .sort_values("dias_sin_venta", ascending=False)
        .reset_index(drop=True)
    )


def tarifas_sin_pedido(df: pd.DataFrame) -> int:
    """Cuenta las filas con tarifa FBA que no tienen un Id. de pedido asociado."""
    if df.empty or COL_TARIFAS_FBA not in df.columns or COL_PEDIDO not in df.columns:
        return 0
    tarifa = pd.to_numeric(df[COL_TARIFAS_FBA], errors="coerce").fillna(0.0)
    sin_pedido = df[COL_PEDIDO].astype("string").fillna("").str.strip().eq("")
    return int((tarifa.ne(0.0) & sin_pedido).sum())

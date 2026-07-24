"""Exportación a Excel y CSV.

Genera desde una tabla suelta hasta el reporte ejecutivo completo de doce hojas,
con formato profesional: encabezados, autofiltro, formato monetario y de
porcentaje, columnas ajustadas, paneles congelados y formato condicional.

Todas las funciones devuelven ``bytes`` listos para ``st.download_button``.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import pandas as pd

from services.alerts_service import Hallazgo, hallazgos_a_dataframe
from services.comparison_service import Comparacion, tabla_comparativa
from services.metrics_service import (
    calcular_metricas,
    desglose_tarifas,
    detalle_pedidos,
    serie_temporal,
    tabla_liquidaciones,
    tabla_por_ciudad,
    tabla_por_estado,
    tabla_por_sku,
    tabla_por_tipo,
    tabla_reembolsos,
)
from utils.constants import (
    COLOR_CRITICO,
    COLOR_EXITO_TEXTO,
    DICCIONARIO_METRICAS,
    ENCABEZADOS_ORIGINALES,
    ETIQUETAS_COLUMNAS,
    ORDEN_COLUMNAS,
)
from utils.logger import get_logger

logger = get_logger("export_service")

# =============================================================================
# Estilos de Excel
# =============================================================================

_FORMATO_ENCABEZADO = {
    "bold": True,
    "font_color": "#FFFFFF",
    "bg_color": "#2a78d6",
    "border": 1,
    "border_color": "#1c5cab",
    "align": "center",
    "valign": "vcenter",
    "text_wrap": True,
}
_FORMATO_MONEDA = {"num_format": '$#,##0.00', "align": "right"}
_FORMATO_ENTERO = {"num_format": "#,##0", "align": "right"}
_FORMATO_PORCENTAJE = {"num_format": "0.0%", "align": "right"}
_FORMATO_FECHA = {"num_format": "dd/mm/yyyy", "align": "center"}
_FORMATO_FECHA_HORA = {"num_format": "dd/mm/yyyy hh:mm", "align": "center"}
_FORMATO_TITULO = {"bold": True, "font_size": 16, "font_color": "#0b0b0b"}
_FORMATO_SUBTITULO = {"italic": True, "font_size": 10, "font_color": "#52514e"}

#: Fragmentos que identifican el tipo de dato de una columna por su nombre.
_PISTAS_MONEDA = (
    "venta", "importe", "neto", "tarifa", "cargo", "reembolso", "impuesto",
    "descuento", "retencion", "total", "costo", "utilidad", "ticket", "precio",
    "publicidad", "ajuste", "transferido", "credito",
)
_PISTAS_PORCENTAJE = ("pct", "porcentaje", "margen", "participacion", "tasa", "roi", "acos", "tacos", "variación %")
_PISTAS_ENTERO = ("pedido", "unidad", "transaccion", "cantidad", "sku vendidos", "lineas", "dias", "rango")


def _tipo_de_columna(nombre: str, serie: pd.Series) -> str:
    """Adivina el formato de una columna a partir de su nombre y su contenido."""
    minusculas = str(nombre).lower()

    if pd.api.types.is_datetime64_any_dtype(serie):
        tiene_hora = False
        try:
            sin_nulos = serie.dropna()
            tiene_hora = bool(len(sin_nulos)) and bool(
                (sin_nulos.dt.hour.ne(0) | sin_nulos.dt.minute.ne(0)).any()
            )
        except (AttributeError, TypeError):
            tiene_hora = False
        return "fecha_hora" if tiene_hora else "fecha"

    if not pd.api.types.is_numeric_dtype(serie):
        return "texto"

    if any(p in minusculas for p in _PISTAS_PORCENTAJE):
        return "porcentaje"
    if any(p in minusculas for p in _PISTAS_MONEDA):
        return "moneda"
    if any(p in minusculas for p in _PISTAS_ENTERO):
        return "entero"
    return "moneda" if serie.dtype.kind == "f" else "entero"


def _ancho_columna(nombre: str, serie: pd.Series) -> float:
    """Ancho razonable para una columna, acotado entre 10 y 55 caracteres."""
    largo_titulo = len(str(nombre))
    try:
        muestra = serie.dropna().astype(str).head(200)
        largo_datos = int(muestra.str.len().max()) if not muestra.empty else 0
    except (AttributeError, TypeError, ValueError):
        largo_datos = 0
    return float(min(max(largo_titulo + 4, largo_datos + 2, 10), 55))


def escribir_hoja(
    writer: pd.ExcelWriter,
    df: pd.DataFrame,
    nombre_hoja: str,
    titulo: str = "",
    subtitulo: str = "",
    formato_condicional: str | None = None,
    congelar: bool = True,
) -> None:
    """Escribe un DataFrame en una hoja con formato profesional.

    Args:
        writer: escritor de pandas con motor ``xlsxwriter``.
        df: datos a escribir.
        nombre_hoja: nombre de la pestaña (máximo 31 caracteres, sin ``[]:*?/\\``).
        titulo: título que se pinta en la fila 1.
        subtitulo: texto de contexto bajo el título.
        formato_condicional: nombre de la columna a la que se aplica una barra
            de datos (por ejemplo ``"ventas"``).
        congelar: si se congela el encabezado.
    """
    libro = writer.book
    hoja_limpia = _nombre_hoja_valido(nombre_hoja)

    fila_inicio = 0
    if titulo:
        fila_inicio = 3 if subtitulo else 2

    if df.empty:
        df = pd.DataFrame({"Sin datos": ["No hay registros para este reporte."]})

    df.to_excel(writer, sheet_name=hoja_limpia, startrow=fila_inicio, index=False)
    hoja = writer.sheets[hoja_limpia]

    # --- Título ---
    if titulo:
        hoja.write(0, 0, titulo, libro.add_format(_FORMATO_TITULO))
        if subtitulo:
            hoja.write(1, 0, subtitulo, libro.add_format(_FORMATO_SUBTITULO))

    # --- Encabezados ---
    formato_encabezado = libro.add_format(_FORMATO_ENCABEZADO)
    for indice, columna in enumerate(df.columns):
        hoja.write(fila_inicio, indice, str(columna), formato_encabezado)

    # --- Formato por columna ---
    formatos = {
        "moneda": libro.add_format(_FORMATO_MONEDA),
        "entero": libro.add_format(_FORMATO_ENTERO),
        "porcentaje": libro.add_format(_FORMATO_PORCENTAJE),
        "fecha": libro.add_format(_FORMATO_FECHA),
        "fecha_hora": libro.add_format(_FORMATO_FECHA_HORA),
        "texto": None,
    }
    for indice, columna in enumerate(df.columns):
        tipo = _tipo_de_columna(columna, df[columna])
        hoja.set_column(indice, indice, _ancho_columna(columna, df[columna]), formatos[tipo])

    # --- Autofiltro y paneles congelados ---
    if len(df) > 0:
        hoja.autofilter(fila_inicio, 0, fila_inicio + len(df), max(len(df.columns) - 1, 0))
    if congelar:
        hoja.freeze_panes(fila_inicio + 1, 0)

    # --- Formato condicional ---
    if formato_condicional and formato_condicional in df.columns and len(df) > 0:
        indice = list(df.columns).index(formato_condicional)
        hoja.conditional_format(
            fila_inicio + 1, indice, fila_inicio + len(df), indice,
            {"type": "data_bar", "bar_color": "#86b6ef", "bar_solid": False},
        )

    # Resalta en rojo los valores negativos de las columnas de resultado.
    for nombre in ("neto", "utilidad", "Diferencia", "importe", "Variación %"):
        if nombre in df.columns and len(df) > 0:
            indice = list(df.columns).index(nombre)
            hoja.conditional_format(
                fila_inicio + 1, indice, fila_inicio + len(df), indice,
                {
                    "type": "cell", "criteria": "<", "value": 0,
                    "format": libro.add_format({"font_color": COLOR_CRITICO}),
                },
            )
            hoja.conditional_format(
                fila_inicio + 1, indice, fila_inicio + len(df), indice,
                {
                    "type": "cell", "criteria": ">", "value": 0,
                    "format": libro.add_format({"font_color": COLOR_EXITO_TEXTO}),
                },
            )


def _nombre_hoja_valido(nombre: str) -> str:
    """Recorta y limpia el nombre de una hoja según las reglas de Excel."""
    limpio = str(nombre)
    for caracter in "[]:*?/\\":
        limpio = limpio.replace(caracter, "-")
    return limpio[:31] or "Hoja"


# =============================================================================
# Exportaciones sencillas
# =============================================================================


def exportar_csv(df: pd.DataFrame, usar_encabezados_originales: bool = False) -> bytes:
    """Exporta a CSV con codificación UTF-8 con BOM (Excel lo abre bien)."""
    salida = df.copy()
    if usar_encabezados_originales:
        salida = salida.rename(columns=ENCABEZADOS_ORIGINALES)
    else:
        salida = salida.rename(columns=ETIQUETAS_COLUMNAS)
    return salida.to_csv(index=False).encode("utf-8-sig")


def exportar_excel_simple(
    df: pd.DataFrame, nombre_hoja: str = "Datos", titulo: str = ""
) -> bytes:
    """Exporta un solo DataFrame a un archivo de Excel con formato."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="dd/mm/yyyy hh:mm") as writer:
        escribir_hoja(writer, df, nombre_hoja, titulo=titulo)
    buffer.seek(0)
    return buffer.getvalue()


def exportar_datos_originales(df: pd.DataFrame) -> bytes:
    """Exporta los datos conservando los encabezados originales de Amazon."""
    columnas = [c for c in ORDEN_COLUMNAS if c in df.columns]
    salida = df[columnas].rename(columns=ENCABEZADOS_ORIGINALES)
    return exportar_excel_simple(salida, "Datos originales", "Reporte de transacciones de Amazon")


# =============================================================================
# Tablas auxiliares del reporte completo
# =============================================================================


def tabla_resumen_ejecutivo(
    metricas: dict[str, Any], comparacion: Comparacion | None = None
) -> pd.DataFrame:
    """Tabla de indicadores para la hoja «Resumen»."""
    grupos = ["Ventas", "Tarifas", "Reembolsos", "Resultado"]
    filas = []
    for clave, info in DICCIONARIO_METRICAS.items():
        if info["grupo"] not in grupos or clave not in metricas:
            continue
        valor = metricas.get(clave)
        fila: dict[str, Any] = {
            "Grupo": info["grupo"],
            "Métrica": info["nombre"],
            "Valor": valor,
            "Fórmula": info["formula"],
        }
        if comparacion is not None and comparacion.hay_comparacion:
            detalle = comparacion.diferencias.get(clave, {})
            fila["Periodo anterior"] = detalle.get("anterior")
            fila["Diferencia"] = detalle.get("absoluta")
            fila["Variación %"] = detalle.get("porcentual")
        filas.append(fila)
    return pd.DataFrame(filas)


def tabla_diccionario_metricas() -> pd.DataFrame:
    """Hoja «Diccionario de métricas»: qué significa y cómo se calcula cada cifra."""
    return pd.DataFrame([
        {
            "Grupo": info["grupo"],
            "Métrica": info["nombre"],
            "Fórmula": info["formula"],
            "Qué significa": info["descripcion"],
        }
        for info in DICCIONARIO_METRICAS.values()
    ])


def _preparar_para_excel(df: pd.DataFrame, etiquetas: dict[str, str] | None = None) -> pd.DataFrame:
    """Renombra columnas y elimina las de uso interno antes de exportar."""
    if df.empty:
        return df
    salida = df.drop(
        columns=[c for c in ("row_hash", "es_duplicado") if c in df.columns],
        errors="ignore",
    ).copy()
    # Las columnas categóricas dan problemas al escribir en Excel.
    for columna in salida.columns:
        if isinstance(salida[columna].dtype, pd.CategoricalDtype):
            salida[columna] = salida[columna].astype("string")
    mapa = {**ETIQUETAS_COLUMNAS, **_ETIQUETAS_AGREGADOS, **(etiquetas or {})}
    return salida.rename(columns={c: mapa[c] for c in salida.columns if c in mapa})


#: Etiquetas de las columnas que produce el motor de métricas.
_ETIQUETAS_AGREGADOS: dict[str, str] = {
    "periodo": "Periodo",
    "ventas": "Ventas",
    "pedidos": "Pedidos",
    "unidades": "Unidades",
    "impuestos": "Impuestos",
    "tarifas": "Tarifas",
    "reembolsos": "Reembolsos",
    "neto": "Neto",
    "ticket_promedio": "Ticket promedio",
    "precio_promedio": "Precio promedio",
    "tarifas_venta": "Tarifas de venta",
    "tarifas_fba": "Tarifas FBA",
    "retenciones": "Retenciones",
    "otros_cargos": "Otros cargos",
    "total_cargos": "Total de cargos",
    "descuentos": "Descuentos",
    "unidades_reembolsadas": "Unidades reembolsadas",
    "pedidos_reembolsados": "Pedidos reembolsados",
    "transacciones": "Transacciones",
    "tarifa_por_unidad": "Tarifa por unidad",
    "neto_por_unidad": "Neto por unidad",
    "neto_por_pedido": "Neto por pedido",
    "pct_cargos": "% de cargos",
    "margen_neto": "Margen neto",
    "participacion": "Participación en ventas",
    "participacion_acumulada": "Participación acumulada",
    "tasa_reembolso": "Tasa de reembolso",
    "descripcion": "Descripción",
    "concepto": "Concepto",
    "importe": "Importe",
    "tipo": "Tipo",
    "fecha_inicial": "Fecha inicial",
    "fecha_final": "Fecha final",
    "fecha_liberacion": "Fecha de liberación",
    "ajustes": "Ajustes",
    "transferido": "Transferido",
    "estado": "Estado",
    "ciudad": "Ciudad",
    "lineas": "Líneas",
    "skus": "SKU distintos",
    "reembolsado": "Reembolsado",
    "costo_unitario": "Costo unitario",
    "costo_mercancia": "Costo de mercancía",
    "utilidad": "Utilidad",
    "utilidad_por_unidad": "Utilidad por unidad",
    "margen": "Margen",
    "roi": "ROI",
    "publicidad": "Publicidad",
    "unidades_netas": "Unidades netas",
    "acos": "ACOS",
    "marca": "Marca",
    "categoria": "Categoría",
}


# =============================================================================
# Reporte completo
# =============================================================================


def exportar_reporte_completo(
    df: pd.DataFrame,
    metricas: dict[str, Any] | None = None,
    comparacion: Comparacion | None = None,
    hallazgos: list[Hallazgo] | None = None,
    rentabilidad: pd.DataFrame | None = None,
    frecuencia: str = "Día",
    incluir_datos: bool = True,
) -> bytes:
    """Genera el libro de Excel con todas las hojas del análisis.

    Hojas: Resumen · Ventas por día · Productos · Pedidos · Reembolsos · Tarifas ·
    Estados · Ciudades · Liquidaciones · Datos procesados · Alertas ·
    Diccionario de métricas (y Rentabilidad si hay costos capturados).
    """
    metricas = metricas or calcular_metricas(df)
    generado = datetime.now().strftime("%d/%m/%Y %H:%M")
    inicio, fin = metricas.get("fecha_inicio"), metricas.get("fecha_fin")
    periodo = (
        f"Periodo analizado: {inicio:%d/%m/%Y} al {fin:%d/%m/%Y}"
        if inicio is not None and fin is not None
        else "Periodo analizado: sin fechas válidas"
    )
    subtitulo = f"{periodo} · Generado el {generado}"

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="dd/mm/yyyy hh:mm") as writer:
        writer.book.set_properties({
            "title": "Amazon Sales Analytics",
            "subject": "Análisis de transacciones de Amazon Seller Central",
            "comments": subtitulo,
        })

        # 1. Resumen -----------------------------------------------------------
        escribir_hoja(
            writer, tabla_resumen_ejecutivo(metricas, comparacion), "Resumen",
            titulo="Resumen ejecutivo", subtitulo=subtitulo,
        )

        # Comparación de periodos como bloque adicional.
        if comparacion is not None and comparacion.hay_comparacion:
            escribir_hoja(
                writer, tabla_comparativa(comparacion), "Comparación",
                titulo="Comparación entre periodos",
                subtitulo=(
                    f"Actual: {comparacion.rango_actual[0]:%d/%m/%Y} a {comparacion.rango_actual[1]:%d/%m/%Y} · "
                    f"Anterior: {comparacion.rango_anterior[0]:%d/%m/%Y} a {comparacion.rango_anterior[1]:%d/%m/%Y}"
                ),
            )

        # 2. Ventas por día ----------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(serie_temporal(df, frecuencia)), "Ventas por día",
            titulo=f"Evolución por {frecuencia.lower()}", subtitulo=subtitulo,
            formato_condicional="Ventas",
        )

        # 3. Productos ---------------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(tabla_por_sku(df)), "Productos",
            titulo="Desempeño por SKU", subtitulo=subtitulo,
            formato_condicional="Ventas",
        )

        # 4. Pedidos -----------------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(detalle_pedidos(df)), "Pedidos",
            titulo="Detalle de transacciones", subtitulo=subtitulo,
        )

        # 5. Reembolsos --------------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(tabla_reembolsos(df)), "Reembolsos",
            titulo="Detalle de reembolsos", subtitulo=subtitulo,
        )

        # 6. Tarifas -----------------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(desglose_tarifas(metricas)), "Tarifas",
            titulo="Composición de los cargos de Amazon", subtitulo=subtitulo,
            formato_condicional="Importe",
        )

        # 7. Estados -----------------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(tabla_por_estado(df)), "Estados",
            titulo="Distribución por estado", subtitulo=subtitulo,
            formato_condicional="Ventas",
        )

        # 8. Ciudades ----------------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(tabla_por_ciudad(df)), "Ciudades",
            titulo="Distribución por ciudad", subtitulo=subtitulo,
            formato_condicional="Ventas",
        )

        # 9. Liquidaciones -----------------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(tabla_liquidaciones(df)), "Liquidaciones",
            titulo="Conciliación de liquidaciones", subtitulo=subtitulo,
        )

        # 9b. Tipos de transacción --------------------------------------------
        escribir_hoja(
            writer, _preparar_para_excel(tabla_por_tipo(df)), "Tipos de transacción",
            titulo="Importe por tipo de transacción", subtitulo=subtitulo,
        )

        # 10. Rentabilidad (opcional) -----------------------------------------
        if rentabilidad is not None and not rentabilidad.empty:
            escribir_hoja(
                writer, _preparar_para_excel(rentabilidad), "Rentabilidad",
                titulo="Costos y rentabilidad por SKU", subtitulo=subtitulo,
                formato_condicional="Utilidad",
            )

        # 11. Datos procesados -------------------------------------------------
        if incluir_datos:
            columnas = [c for c in ORDEN_COLUMNAS if c in df.columns]
            escribir_hoja(
                writer, _preparar_para_excel(df[columnas]), "Datos procesados",
                titulo="Transacciones limpias", subtitulo=subtitulo,
            )

        # 12. Alertas ----------------------------------------------------------
        escribir_hoja(
            writer, hallazgos_a_dataframe(hallazgos or []), "Alertas",
            titulo="Hallazgos automáticos", subtitulo=subtitulo,
        )

        # 13. Diccionario ------------------------------------------------------
        escribir_hoja(
            writer, tabla_diccionario_metricas(), "Diccionario de métricas",
            titulo="Diccionario de métricas",
            subtitulo="Cómo se calcula cada indicador de este reporte.",
        )

    buffer.seek(0)
    logger.info("Reporte completo generado (%d filas de origen).", len(df))
    return buffer.getvalue()


def nombre_archivo_exportacion(prefijo: str, extension: str = "xlsx") -> str:
    """Nombre de archivo con marca de tiempo: ``resumen_20260724_1530.xlsx``."""
    marca = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{prefijo}_{marca}.{extension}"

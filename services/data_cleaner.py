"""Limpieza y normalización del reporte de Amazon.

Convierte el DataFrame crudo (todo texto) en un DataFrame tipado y coherente:

* fechas en español -> ``datetime64``
* columnas monetarias -> ``float64`` (nulos como cero)
* SKU, pedidos y códigos postales -> texto, conservando ceros a la izquierda
* tipos de transacción, marketplace, estados y ciudades -> valores canónicos
* llave de duplicados y marca de duplicado

Todas las operaciones son vectorizadas.  El limpiador nunca lanza una excepción
por un dato mal formado: lo corrige, lo marca y lo reporta.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from utils.constants import (
    ALIAS_TIPOS,
    COL_CANTIDAD,
    COL_CIUDAD,
    COL_CP,
    COL_DESCRIPCION,
    COL_ES_DUPLICADO,
    COL_ESTADO,
    COL_ESTADO_TRANSACCION,
    COL_FECHA,
    COL_FECHA_LIBERACION,
    COL_HASH,
    COL_MARKETPLACE,
    COL_PEDIDO,
    COL_SKU,
    COL_TIPO,
    COLUMNAS_FECHA,
    COLUMNAS_MONETARIAS,
    COLUMNAS_TEXTO,
    ESTADOS_MEXICO,
    TIPO_OTROS,
    normalizar_texto,
)
from utils.date_parser import enriquecer_columnas_fecha, parsear_serie_fechas
from utils.logger import get_logger
from utils.validations import construir_llave_duplicados

logger = get_logger("data_cleaner")


@dataclass
class ReporteLimpieza:
    """Resumen de lo que hizo el limpiador, para mostrarlo al usuario."""

    filas_entrada: int = 0
    filas_salida: int = 0
    filas_descartadas: int = 0
    fechas_invalidas: int = 0
    valores_monetarios_corregidos: int = 0
    duplicados_detectados: int = 0
    columnas_agregadas: list[str] = field(default_factory=list)
    columnas_faltantes: list[str] = field(default_factory=list)
    tipos_desconocidos: list[str] = field(default_factory=list)
    mensajes: list[str] = field(default_factory=list)

    def resumen(self) -> str:
        """Frase corta para la interfaz."""
        partes = [f"{self.filas_salida:,} registros listos"]
        if self.filas_descartadas:
            partes.append(f"{self.filas_descartadas:,} descartados")
        if self.fechas_invalidas:
            partes.append(f"{self.fechas_invalidas:,} fechas ilegibles")
        if self.duplicados_detectados:
            partes.append(f"{self.duplicados_detectados:,} posibles duplicados")
        return " · ".join(partes)


# =============================================================================
# Conversión de importes
# =============================================================================


def convertir_a_numero(serie: pd.Series) -> pd.Series:
    """Convierte una columna monetaria en texto a ``float64``.

    Maneja de forma vectorizada:

    * símbolos de moneda, espacios y espacios duros (``$``, ``MXN``, ``\\xa0``)
    * separador de miles con coma (``1,234.56``) o con punto (``1.234,56``)
    * negativos con signo (``-1,234.56``) o entre paréntesis (``(1,234.56)``)
    * vacíos, guiones y textos no numéricos -> ``0.0``
    """
    if serie.empty:
        return pd.Series([], dtype="float64")

    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce").fillna(0.0).astype("float64")

    texto = serie.astype("string").str.strip()
    # Elimina todo lo que no sea dígito, separador, signo o paréntesis.
    texto = texto.str.replace(r"[^\d,.\-()]", "", regex=True)

    # Negativo por notación contable: (1,234.56)
    negativo_parentesis = texto.str.startswith("(", na=False) & texto.str.endswith(")", na=False)
    texto = texto.str.replace(r"[()]", "", regex=True)

    # Conserva un solo signo menos al inicio.
    negativo_signo = texto.str.startswith("-", na=False)
    texto = texto.str.replace("-", "", regex=False)

    tiene_coma = texto.str.contains(",", na=False)
    tiene_punto = texto.str.contains(".", regex=False, na=False)
    pos_coma = texto.str.rfind(",")
    pos_punto = texto.str.rfind(".")

    # Caso A: ambos separadores. El último que aparece es el decimal.
    ambos = tiene_coma & tiene_punto
    coma_es_decimal = ambos & (pos_coma > pos_punto)   # 1.234,56  (europeo)
    punto_es_decimal = ambos & (pos_punto > pos_coma)  # 1,234.56  (México / EE. UU.)

    # Caso B: solo coma. Es decimal si van 1 o 2 dígitos después; si no, es millar.
    solo_coma = tiene_coma & ~tiene_punto
    coma_decimal_sola = solo_coma & texto.str.contains(r",\d{1,2}$", regex=True, na=False)

    # Caso C: solo punto. Es millar si el patrón es 1.234 / 1.234.567.
    solo_punto = tiene_punto & ~tiene_coma
    punto_millar_solo = solo_punto & texto.str.contains(
        r"^\d{1,3}(?:\.\d{3})+$", regex=True, na=False
    )

    limpio = texto.copy()
    # Formato europeo: quita puntos de millar y convierte la coma en punto.
    mascara_eu = coma_es_decimal | coma_decimal_sola
    limpio = limpio.where(
        ~mascara_eu,
        limpio.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
    )
    # Formato mexicano/estadounidense: la coma solo es separador de millares.
    mascara_mx = punto_es_decimal | (solo_coma & ~coma_decimal_sola)
    limpio = limpio.where(~mascara_mx, limpio.str.replace(",", "", regex=False))
    # Punto usado como millar: se elimina.
    limpio = limpio.where(~punto_millar_solo, limpio.str.replace(".", "", regex=False))

    numeros = pd.to_numeric(limpio, errors="coerce")
    numeros = numeros.where(~(negativo_signo | negativo_parentesis), -numeros)
    return numeros.fillna(0.0).astype("float64")


def contar_valores_corregidos(original: pd.Series, convertido: pd.Series) -> int:
    """Cuenta cuántas celdas tenían texto no numérico y se resolvieron como cero."""
    if original.empty:
        return 0
    tenia_contenido = original.astype("string").str.strip().fillna("").ne("")
    quedo_en_cero = convertido.eq(0.0)
    era_cero_legitimo = original.astype("string").str.strip().isin(["0", "0.0", "0.00", "$0.00"])
    return int((tenia_contenido & quedo_en_cero & ~era_cero_legitimo).sum())


# =============================================================================
# Normalización de campos categóricos
# =============================================================================


def normalizar_tipo(serie: pd.Series) -> tuple[pd.Series, list[str]]:
    """Convierte el campo «tipo» a los valores canónicos del proyecto.

    Returns:
        ``(serie_normalizada, valores_no_reconocidos)``.  Lo no reconocido cae en
        «Otros cargos» pero se reporta para que el usuario lo sepa.
    """
    normalizado = serie.astype("string").fillna("").map(normalizar_texto)
    resultado = normalizado.map(ALIAS_TIPOS)

    # Segunda pasada: coincidencia por prefijo ("tarifa de servicio mensual").
    pendientes = resultado.isna() & normalizado.ne("")
    if pendientes.any():
        alias_ordenados = sorted(ALIAS_TIPOS.keys(), key=len, reverse=True)

        def _buscar(valor: str) -> str | None:
            for alias in alias_ordenados:
                if valor.startswith(alias) or alias in valor:
                    return ALIAS_TIPOS[alias]
            return None

        resultado.loc[pendientes] = normalizado[pendientes].map(_buscar)

    desconocidos = sorted(
        {
            original
            for original, canonico in zip(serie.astype("string").fillna(""), resultado)
            if pd.isna(canonico) and str(original).strip()
        }
    )
    return resultado.fillna(TIPO_OTROS).astype("string"), desconocidos


def normalizar_marketplace(serie: pd.Series) -> pd.Series:
    """Unifica ``amazon.com.mx`` y ``Amazon.com.mx`` en un solo valor."""
    limpio = serie.astype("string").str.strip().str.lower()
    limpio = limpio.str.replace(r"\s+", " ", regex=True)
    return limpio.replace({"": pd.NA}).fillna("Sin marketplace").astype("string")


def normalizar_estado(serie: pd.Series) -> pd.Series:
    """Convierte el estado a su nombre oficial (``NUEVO LEON`` -> ``Nuevo León``)."""
    normalizado = serie.astype("string").fillna("").map(normalizar_texto)
    oficial = normalizado.map(ESTADOS_MEXICO)
    # Lo que no está en el catálogo conserva su texto en formato título, pero se
    # reconstruye a partir del texto ya normalizado para no arrastrar espacios
    # dobles ni caracteres invisibles que crearían duplicados.
    sin_catalogo = oficial.isna() & normalizado.ne("")
    if sin_catalogo.any():
        oficial.loc[sin_catalogo] = normalizado[sin_catalogo].str.title()
    return oficial.fillna("Sin estado").astype("string")


def normalizar_ciudad(serie: pd.Series) -> pd.Series:
    """Quita espacios duplicados y aplica formato título a la ciudad."""
    limpio = serie.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    limpio = limpio.str.title()
    return limpio.replace({"": pd.NA}).fillna("Sin ciudad").astype("string")


def normalizar_texto_simple(serie: pd.Series, relleno: str = "") -> pd.Series:
    """Recorta y colapsa espacios sin cambiar mayúsculas ni acentos."""
    limpio = serie.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    if relleno:
        return limpio.replace({"": pd.NA}).fillna(relleno).astype("string")
    return limpio.fillna("").astype("string")


def normalizar_codigo_postal(serie: pd.Series) -> pd.Series:
    """Conserva el código postal como texto de 5 dígitos con ceros a la izquierda."""
    limpio = serie.astype("string").str.strip()
    # Quita decimales que introduce Excel al leer "03020" como número (3020.0).
    limpio = limpio.str.replace(r"\.0+$", "", regex=True)
    solo_digitos = limpio.str.replace(r"\D", "", regex=True)
    # Solo se rellena a 5 si el valor cabe en 5 dígitos (formato mexicano).
    cabe = solo_digitos.str.len().le(5) & solo_digitos.ne("")
    resultado = solo_digitos.where(~cabe, solo_digitos.str.zfill(5))
    return resultado.fillna("").astype("string")


# =============================================================================
# Limpieza principal
# =============================================================================


def limpiar_dataframe(
    df: pd.DataFrame, marcar_duplicados: bool = True
) -> tuple[pd.DataFrame, ReporteLimpieza]:
    """Aplica todas las reglas de limpieza y devuelve el DataFrame listo para analizar.

    Args:
        df: DataFrame con las columnas ya renombradas a nombres canónicos.
        marcar_duplicados: si se calcula la llave y la marca de duplicado.

    Returns:
        ``(df_limpio, reporte)``.  El DataFrame original no se modifica.
    """
    reporte = ReporteLimpieza(filas_entrada=len(df))

    if df.empty:
        reporte.mensajes.append("El archivo no contiene registros.")
        return df.copy(), reporte

    limpio = df.copy()

    # --- 1. Fechas -----------------------------------------------------------
    for columna in COLUMNAS_FECHA:
        if columna in limpio.columns:
            antes_nulos = limpio[columna].astype("string").str.strip().fillna("").eq("").sum()
            limpio[columna] = parsear_serie_fechas(limpio[columna])
            if columna == COL_FECHA:
                invalidas = int(limpio[columna].isna().sum()) - int(antes_nulos)
                reporte.fechas_invalidas = max(invalidas, 0)
        else:
            reporte.columnas_faltantes.append(columna)

    # --- 2. Importes ---------------------------------------------------------
    corregidos = 0
    for columna in COLUMNAS_MONETARIAS:
        if columna in limpio.columns:
            original = limpio[columna]
            convertido = convertir_a_numero(original)
            corregidos += contar_valores_corregidos(original, convertido)
            limpio[columna] = convertido
        else:
            # Columna ausente: se crea en cero para que las métricas no fallen.
            limpio[columna] = 0.0
            reporte.columnas_faltantes.append(columna)
            reporte.columnas_agregadas.append(columna)
    reporte.valores_monetarios_corregidos = corregidos

    # --- 3. Cantidad ---------------------------------------------------------
    if COL_CANTIDAD in limpio.columns:
        limpio[COL_CANTIDAD] = (
            pd.to_numeric(limpio[COL_CANTIDAD], errors="coerce").fillna(0).astype("float64")
        )
    else:
        limpio[COL_CANTIDAD] = 0.0
        reporte.columnas_faltantes.append(COL_CANTIDAD)
        reporte.columnas_agregadas.append(COL_CANTIDAD)

    # --- 4. Campos de texto --------------------------------------------------
    for columna in COLUMNAS_TEXTO:
        if columna not in limpio.columns:
            limpio[columna] = pd.NA
            reporte.columnas_agregadas.append(columna)

    if COL_TIPO in limpio.columns:
        limpio[COL_TIPO], desconocidos = normalizar_tipo(limpio[COL_TIPO])
        reporte.tipos_desconocidos = desconocidos
        if desconocidos:
            reporte.mensajes.append(
                "Tipos de transacción no reconocidos (se clasificaron como «Otros cargos»): "
                + ", ".join(f"«{t}»" for t in desconocidos[:8])
            )

    limpio[COL_MARKETPLACE] = normalizar_marketplace(limpio[COL_MARKETPLACE])
    limpio[COL_ESTADO] = normalizar_estado(limpio[COL_ESTADO])
    limpio[COL_CIUDAD] = normalizar_ciudad(limpio[COL_CIUDAD])
    limpio[COL_CP] = normalizar_codigo_postal(limpio[COL_CP])
    limpio[COL_SKU] = normalizar_texto_simple(limpio[COL_SKU], relleno="Sin SKU")
    limpio[COL_PEDIDO] = normalizar_texto_simple(limpio[COL_PEDIDO])
    limpio[COL_DESCRIPCION] = normalizar_texto_simple(limpio[COL_DESCRIPCION], relleno="Sin descripción")
    limpio[COL_ESTADO_TRANSACCION] = normalizar_texto_simple(
        limpio[COL_ESTADO_TRANSACCION], relleno="Sin estado"
    )
    for columna in ("cumplimiento", "modelo_impuestos", "id_liquidacion"):
        if columna in limpio.columns:
            limpio[columna] = normalizar_texto_simple(limpio[columna], relleno="Sin dato")

    # --- 5. Descarta filas sin información utilizable ------------------------
    # Una fila sirve si tiene fecha o algún importe distinto de cero.
    tiene_fecha = limpio[COL_FECHA].notna() if COL_FECHA in limpio.columns else False
    tiene_importe = limpio[COLUMNAS_MONETARIAS].abs().sum(axis=1) > 0
    utilizable = tiene_fecha | tiene_importe
    descartadas = int((~utilizable).sum())
    if descartadas:
        limpio = limpio.loc[utilizable].copy()
        reporte.mensajes.append(
            f"Se descartaron {descartadas:,} filas sin fecha ni importes (renglones vacíos del archivo)."
        )
    reporte.filas_descartadas = descartadas

    # --- 6. Columnas derivadas de la fecha -----------------------------------
    if COL_FECHA in limpio.columns:
        limpio = enriquecer_columnas_fecha(limpio, COL_FECHA)

    # --- 7. Llave y marca de duplicados --------------------------------------
    if marcar_duplicados and not limpio.empty:
        limpio[COL_HASH] = construir_llave_duplicados(limpio)
        limpio[COL_ES_DUPLICADO] = limpio[COL_HASH].duplicated(keep="first").fillna(False)
        reporte.duplicados_detectados = int(limpio[COL_ES_DUPLICADO].sum())
        if reporte.duplicados_detectados:
            reporte.mensajes.append(
                f"Se detectaron {reporte.duplicados_detectados:,} registros con la misma llave "
                "(pedido, tipo, SKU, fecha, total y liquidación). No se eliminaron: "
                "decide en la página de carga si deseas excluirlos."
            )
    elif not limpio.empty:
        limpio[COL_HASH] = pd.NA
        limpio[COL_ES_DUPLICADO] = False

    # --- 8. Optimización de memoria ------------------------------------------
    limpio = optimizar_tipos(limpio)

    reporte.filas_salida = len(limpio)
    logger.info("Limpieza terminada: %s", reporte.resumen())
    return limpio, reporte


def optimizar_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Reduce el uso de memoria convirtiendo a ``category`` los campos repetitivos.

    Solo se convierten las columnas cuya cardinalidad es baja (menos del 50 % de
    valores distintos); convertir una columna casi única gastaría más memoria.
    """
    candidatas = [
        COL_TIPO, COL_MARKETPLACE, COL_ESTADO, COL_ESTADO_TRANSACCION,
        "cumplimiento", "modelo_impuestos",
    ]
    for columna in candidatas:
        if columna in df.columns and len(df) > 0:
            distintos = df[columna].nunique(dropna=False)
            if distintos > 0 and distintos / len(df) < 0.5:
                df[columna] = df[columna].astype("category")
    return df


def concatenar_reportes(
    dataframes: list[pd.DataFrame], marcar_duplicados: bool = True
) -> tuple[pd.DataFrame, int]:
    """Une varios reportes ya limpios en un solo conjunto.

    Recalcula la marca de duplicados sobre el conjunto completo, de modo que un
    registro que aparece en dos archivos distintos también se detecta.

    Returns:
        ``(df_unido, duplicados_detectados)``.
    """
    validos = [d for d in dataframes if d is not None and not d.empty]
    if not validos:
        return pd.DataFrame(), 0

    # ``category`` con categorías distintas rompe la concatenación: se revierte a texto.
    normalizados = []
    for d in validos:
        copia = d.copy()
        for columna in copia.columns:
            if isinstance(copia[columna].dtype, pd.CategoricalDtype):
                copia[columna] = copia[columna].astype("string")
        normalizados.append(copia)

    unido = pd.concat(normalizados, ignore_index=True, sort=False)

    duplicados = 0
    if marcar_duplicados and COL_HASH in unido.columns:
        unido[COL_HASH] = construir_llave_duplicados(unido)
        unido[COL_ES_DUPLICADO] = unido[COL_HASH].duplicated(keep="first").fillna(False)
        duplicados = int(unido[COL_ES_DUPLICADO].sum())

    if COL_FECHA in unido.columns:
        unido = unido.sort_values(COL_FECHA, na_position="last").reset_index(drop=True)

    return optimizar_tipos(unido), duplicados


def aplicar_exclusion_duplicados(df: pd.DataFrame, excluir: bool) -> pd.DataFrame:
    """Devuelve el DataFrame sin los duplicados marcados, si el usuario lo pidió."""
    if not excluir or COL_ES_DUPLICADO not in df.columns:
        return df
    return df.loc[~df[COL_ES_DUPLICADO].fillna(False).astype(bool)].copy()


def resumen_columnas_faltantes(df: pd.DataFrame) -> list[str]:
    """Lista de columnas canónicas que no venían en el archivo original."""
    esperadas = set(COLUMNAS_MONETARIAS) | set(COLUMNAS_TEXTO) | {COL_CANTIDAD, COL_FECHA}
    return sorted(c for c in esperadas if c not in df.columns)


def convertir_columna_a_numero_seguro(df: pd.DataFrame, columna: str) -> pd.Series:
    """Devuelve una columna como ``float64``, creándola en cero si no existe."""
    if columna not in df.columns:
        return pd.Series(np.zeros(len(df)), index=df.index, dtype="float64")
    return pd.to_numeric(df[columna], errors="coerce").fillna(0.0).astype("float64")

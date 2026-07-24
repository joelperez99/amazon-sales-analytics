"""Pruebas de limpieza: fechas en español, importes y normalización."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.data_cleaner import (
    concatenar_reportes,
    convertir_a_numero,
    limpiar_dataframe,
    normalizar_ciudad,
    normalizar_codigo_postal,
    normalizar_estado,
    normalizar_marketplace,
    normalizar_tipo,
)
from utils.constants import (
    COL_CANTIDAD,
    COL_CP,
    COL_ES_DUPLICADO,
    COL_FECHA,
    COL_HASH,
    COL_SKU,
    COL_TIPO,
    COL_TOTAL,
    COLUMNAS_MONETARIAS,
    TIPO_OTROS,
    TIPO_PEDIDO,
    TIPO_REEMBOLSO,
    TIPO_TRANSFERENCIA,
)
from utils.date_parser import parsear_fecha_es, parsear_serie_fechas
from utils.validations import detectar_duplicados


class TestFechasEnEspanol:
    """Conversión del formato de fecha que emite Amazon México."""

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("1 jun 2026 12:41:59 a.m. GMT-7", (2026, 6, 1, 0, 41, 59)),
            ("1 jun 2026 12:41:59 p.m. GMT-7", (2026, 6, 1, 12, 41, 59)),
            ("8 jun 2026 6:40:46 p.m. GMT-7", (2026, 6, 8, 18, 40, 46)),
            ("12 jun 2026 7:35:06 a.m. GMT-7", (2026, 6, 12, 7, 35, 6)),
            ("31 dic 2025 11:59:00 p.m. GMT-6", (2025, 12, 31, 23, 59, 0)),
            ("1 ene 2026 12:00:00 a.m. GMT-7", (2026, 1, 1, 0, 0, 0)),
            ("15 sept 2026 3:05:00 a.m. GMT-7", (2026, 9, 15, 3, 5, 0)),
        ],
    )
    def test_convierte_fechas_individuales(self, texto: str, esperado: tuple) -> None:
        resultado = parsear_fecha_es(texto)
        assert (
            resultado.year, resultado.month, resultado.day,
            resultado.hour, resultado.minute, resultado.second,
        ) == esperado

    def test_medianoche_y_mediodia(self) -> None:
        """``12 a.m.`` es la medianoche (0 h) y ``12 p.m.`` el mediodía (12 h)."""
        assert parsear_fecha_es("1 jun 2026 12:00:00 a.m. GMT-7").hour == 0
        assert parsear_fecha_es("1 jun 2026 12:00:00 p.m. GMT-7").hour == 12

    def test_conversion_vectorizada_equivale_a_la_individual(self) -> None:
        textos = [
            "1 jun 2026 12:41:59 a.m. GMT-7",
            "8 jun 2026 6:40:46 p.m. GMT-7",
            "31 dic 2025 11:59:00 p.m. GMT-6",
        ]
        serie = parsear_serie_fechas(pd.Series(textos))
        for texto, resultado in zip(textos, serie):
            assert resultado == parsear_fecha_es(texto)

    def test_fecha_invalida_produce_nat(self) -> None:
        serie = parsear_serie_fechas(pd.Series(["no es una fecha", "", None]))
        assert serie.isna().all()

    def test_acepta_formato_iso_como_respaldo(self) -> None:
        assert parsear_fecha_es("2026-06-01 10:30:00").day == 1

    def test_serie_vacia(self) -> None:
        assert parsear_serie_fechas(pd.Series([], dtype="object")).empty

    def test_conserva_columnas_ya_convertidas(self) -> None:
        original = pd.Series(pd.to_datetime(["2026-06-01", "2026-06-02"]))
        assert parsear_serie_fechas(original).equals(original)


class TestImportes:
    """Conversión de texto a número con distintos formatos monetarios."""

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("342.24", 342.24),
            ("1,234.56", 1234.56),         # separador de miles mexicano
            ("-15,874.01", -15874.01),     # negativo con miles
            ("$1,234.56", 1234.56),        # símbolo de moneda
            ("$ 1,234.56 MXN", 1234.56),   # con divisa y espacios
            ("(1,234.56)", -1234.56),      # negativo contable
            ("1.234,56", 1234.56),         # formato europeo
            ("1.234", 1234.0),             # punto como separador de miles
            ("0", 0.0),
            ("", 0.0),
            ("-", 0.0),
            ("texto", 0.0),
            ("  57.90  ", 57.90),
        ],
    )
    def test_convierte_importes(self, texto: str, esperado: float) -> None:
        resultado = convertir_a_numero(pd.Series([texto]))
        assert resultado.iloc[0] == pytest.approx(esperado)

    def test_nulos_se_convierten_en_cero(self) -> None:
        resultado = convertir_a_numero(pd.Series([None, np.nan, ""]))
        assert (resultado == 0.0).all()

    def test_columna_ya_numerica_se_conserva(self) -> None:
        resultado = convertir_a_numero(pd.Series([1.5, -2.5, 0.0]))
        assert resultado.tolist() == [1.5, -2.5, 0.0]

    def test_serie_vacia(self) -> None:
        assert convertir_a_numero(pd.Series([], dtype="object")).empty


class TestNormalizacionCategorias:
    """Unificación de tipo, marketplace, estado, ciudad y código postal."""

    @pytest.mark.parametrize(
        "original,esperado",
        [
            ("Pedido", TIPO_PEDIDO),
            ("PEDIDO", TIPO_PEDIDO),
            ("Reembolso", TIPO_REEMBOLSO),
            ("Trasferir", TIPO_TRANSFERENCIA),   # errata del reporte original
            ("Transferir", TIPO_TRANSFERENCIA),
            ("Transferencia", TIPO_TRANSFERENCIA),
        ],
    )
    def test_normaliza_tipos(self, original: str, esperado: str) -> None:
        resultado, _ = normalizar_tipo(pd.Series([original]))
        assert resultado.iloc[0] == esperado

    def test_tipo_desconocido_cae_en_otros_cargos_y_se_reporta(self) -> None:
        resultado, desconocidos = normalizar_tipo(pd.Series(["Concepto inventado"]))
        assert resultado.iloc[0] == TIPO_OTROS
        assert "Concepto inventado" in desconocidos

    def test_marketplace_ignora_mayusculas(self) -> None:
        resultado = normalizar_marketplace(pd.Series(["amazon.com.mx", "Amazon.com.MX"]))
        assert resultado.nunique() == 1

    def test_estados_usan_el_nombre_oficial(self) -> None:
        resultado = normalizar_estado(pd.Series(["NUEVO LEON", "Nuevo León", "nuevo leon"]))
        assert resultado.nunique() == 1
        assert resultado.iloc[0] == "Nuevo León"

    def test_cdmx_y_distrito_federal_son_el_mismo_estado(self) -> None:
        resultado = normalizar_estado(pd.Series(["CIUDAD DE MEXICO", "CDMX", "Distrito Federal"]))
        assert resultado.nunique() == 1

    def test_ciudad_colapsa_espacios(self) -> None:
        resultado = normalizar_ciudad(pd.Series(["  MONTERREY  ", "monterrey", "MONTE  RREY"]))
        assert resultado.iloc[0] == resultado.iloc[1] == "Monterrey"
        assert resultado.iloc[2] == "Monte Rrey"

    def test_codigo_postal_conserva_ceros_iniciales(self) -> None:
        resultado = normalizar_codigo_postal(pd.Series(["3020", "03020", "3020.0"]))
        assert (resultado == "03020").all()


class TestLimpiezaCompleta:
    """El limpiador de punta a punta sobre el conjunto de prueba."""

    def test_tipos_de_datos_resultantes(self, df_limpio: pd.DataFrame) -> None:
        assert pd.api.types.is_datetime64_any_dtype(df_limpio[COL_FECHA])
        for columna in COLUMNAS_MONETARIAS:
            assert pd.api.types.is_numeric_dtype(df_limpio[columna])
        assert pd.api.types.is_numeric_dtype(df_limpio[COL_CANTIDAD])

    def test_agrega_columnas_derivadas_de_la_fecha(self, df_limpio: pd.DataFrame) -> None:
        for columna in ("fecha", "anio", "mes", "semana", "dia_semana", "hora"):
            assert columna in df_limpio.columns
        assert int(df_limpio["anio"].iloc[0]) == 2026

    def test_sku_y_pedido_siguen_siendo_texto(self, df_limpio: pd.DataFrame) -> None:
        assert not pd.api.types.is_numeric_dtype(df_limpio[COL_SKU])
        assert df_limpio[COL_CP].iloc[0] == "64840"

    def test_calcula_la_llave_y_marca_duplicados(self, df_limpio: pd.DataFrame) -> None:
        assert COL_HASH in df_limpio.columns
        assert COL_ES_DUPLICADO in df_limpio.columns
        # Las ocho filas del conjunto base son distintas entre sí.
        assert not df_limpio[COL_ES_DUPLICADO].any()

    def test_columnas_faltantes_se_crean_en_cero(self) -> None:
        parcial = pd.DataFrame({
            COL_FECHA: ["1 jun 2026 12:00:00 a.m. GMT-7"],
            COL_TIPO: ["Pedido"],
            COL_TOTAL: ["100.00"],
        })
        limpio, reporte = limpiar_dataframe(parcial)
        assert "ventas_productos" in limpio.columns
        assert limpio["ventas_productos"].iloc[0] == 0.0
        assert "ventas_productos" in reporte.columnas_agregadas

    def test_dataframe_vacio_no_lanza_excepcion(self) -> None:
        limpio, reporte = limpiar_dataframe(pd.DataFrame())
        assert limpio.empty
        assert reporte.filas_salida == 0

    def test_descarta_filas_sin_fecha_ni_importe(self) -> None:
        datos = pd.DataFrame({
            COL_FECHA: ["1 jun 2026 12:00:00 a.m. GMT-7", ""],
            COL_TIPO: ["Pedido", ""],
            COL_TOTAL: ["100.00", ""],
        })
        limpio, reporte = limpiar_dataframe(datos)
        assert len(limpio) == 1
        assert reporte.filas_descartadas == 1

    def test_valores_nulos_no_detienen_la_limpieza(self) -> None:
        datos = pd.DataFrame({
            COL_FECHA: ["1 jun 2026 12:00:00 a.m. GMT-7", None],
            COL_TIPO: ["Pedido", None],
            COL_TOTAL: ["100.00", "50.00"],
            COL_SKU: [None, "SKU9"],
        })
        limpio, _ = limpiar_dataframe(datos)
        assert len(limpio) == 2
        assert limpio[COL_SKU].iloc[0] == "Sin SKU"


class TestDuplicados:
    """Detección de registros repetidos con la llave compuesta."""

    def test_detecta_una_fila_repetida(self, df_limpio: pd.DataFrame) -> None:
        duplicado = pd.concat([df_limpio, df_limpio.head(1)], ignore_index=True)
        marca, cantidad = detectar_duplicados(duplicado)
        assert cantidad == 1
        # La primera aparición nunca se marca: solo la repetición.
        assert not marca.iloc[0]
        assert marca.iloc[-1]

    def test_concatenar_detecta_duplicados_entre_archivos(self, df_limpio: pd.DataFrame) -> None:
        unido, duplicados = concatenar_reportes([df_limpio, df_limpio])
        assert len(unido) == len(df_limpio) * 2
        assert duplicados == len(df_limpio)

    def test_concatenar_ordena_por_fecha(self, df_limpio: pd.DataFrame) -> None:
        unido, _ = concatenar_reportes([df_limpio.tail(4), df_limpio.head(4)])
        fechas = unido[COL_FECHA].dropna()
        assert fechas.is_monotonic_increasing

    def test_concatenar_lista_vacia(self) -> None:
        unido, duplicados = concatenar_reportes([])
        assert unido.empty
        assert duplicados == 0

    def test_no_se_elimina_ningun_duplicado_automaticamente(self, df_limpio: pd.DataFrame) -> None:
        unido, _ = concatenar_reportes([df_limpio, df_limpio])
        assert len(unido) == 16  # se marcan, no se borran

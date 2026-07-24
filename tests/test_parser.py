"""Pruebas de lectura de archivos y normalización de encabezados."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from services.amazon_parser import (
    detectar_delimitador,
    detectar_encoding,
    detectar_fila_encabezado,
    leer_archivo,
    mapear_columnas,
    sugerir_columna,
)
from utils.constants import (
    COL_ESTADO,
    COL_ESTADO_TRANSACCION,
    COL_FECHA,
    COL_PEDIDO,
    COL_SKU,
    COL_TARIFAS_FBA,
    COL_TOTAL,
    COLUMNAS_REQUERIDAS,
)

from tests.conftest import ENCABEZADOS


class TestDeteccionFormato:
    """Detección de codificación, delimitador y fila de encabezado."""

    def test_detecta_utf8_con_bom(self) -> None:
        assert detectar_encoding("fecha/hora,tipo\n".encode("utf-8-sig")) == "utf-8-sig"

    def test_detecta_latin1_con_acentos(self) -> None:
        contenido = "descripción,tarifas fba\nCría,10\n".encode("cp1252")
        # Basta con que devuelva una codificación capaz de decodificar el archivo.
        codificacion = detectar_encoding(contenido)
        assert contenido.decode(codificacion)

    @pytest.mark.parametrize("separador", [",", ";", "\t", "|"])
    def test_detecta_delimitadores(self, separador: str) -> None:
        texto = separador.join(["fecha/hora", "tipo", "total"]) + "\n"
        texto += separador.join(["1 jun 2026", "Pedido", "100"]) + "\n"
        texto += separador.join(["2 jun 2026", "Pedido", "200"]) + "\n"
        assert detectar_delimitador(texto) == separador

    def test_localiza_encabezado_tras_un_preambulo(self) -> None:
        filas = [
            ["Informe de transacciones"],
            ["Cuenta: 12345"],
            [],
            ["fecha/hora", "tipo", "Id. del pedido", "sku", "total"],
            ["1 jun 2026", "Pedido", "701-A", "SKU1", "100"],
        ]
        assert detectar_fila_encabezado(filas) == 3

    def test_encabezado_en_la_primera_fila(self) -> None:
        filas = [ENCABEZADOS, ["1 jun 2026"] + [""] * 30]
        assert detectar_fila_encabezado(filas) == 0


class TestMapeoColumnas:
    """Traducción de encabezados originales a nombres canónicos."""

    def test_reconoce_todos_los_encabezados_de_amazon(self) -> None:
        mapeo, sin_reconocer = mapear_columnas(ENCABEZADOS)
        assert sin_reconocer == []
        assert len(mapeo) == len(ENCABEZADOS)

    @pytest.mark.parametrize(
        "encabezado,esperado",
        [
            ("FECHA/HORA", COL_FECHA),
            ("  Fecha/Hora  ", COL_FECHA),
            ("Id. del Pedido", COL_PEDIDO),
            ("ID DEL PEDIDO", COL_PEDIDO),
            ("SKU", COL_SKU),
            ("Tarifas FBA", COL_TARIFAS_FBA),
            ("TARIFAS  FBA", COL_TARIFAS_FBA),
            ("Total", COL_TOTAL),
        ],
    )
    def test_tolera_mayusculas_acentos_y_espacios(self, encabezado: str, esperado: str) -> None:
        mapeo, _ = mapear_columnas([encabezado])
        assert mapeo[encabezado] == esperado

    def test_distingue_estado_del_pedido_de_estado_de_la_transaccion(self) -> None:
        mapeo, _ = mapear_columnas(["estado del pedido", "Estado de la transacción"])
        assert mapeo["estado del pedido"] == COL_ESTADO
        assert mapeo["Estado de la transacción"] == COL_ESTADO_TRANSACCION

    def test_no_asigna_dos_encabezados_a_la_misma_columna(self) -> None:
        mapeo, sin_reconocer = mapear_columnas(["total", "Total"])
        assert list(mapeo.values()).count(COL_TOTAL) == 1
        assert len(sin_reconocer) == 1

    def test_columna_desconocida_queda_sin_reconocer(self) -> None:
        _, sin_reconocer = mapear_columnas(["campo_inventado_xyz"])
        assert sin_reconocer == ["campo_inventado_xyz"]

    def test_sugiere_columnas_parecidas(self) -> None:
        assert COL_TARIFAS_FBA in sugerir_columna("tarifa fba")


class TestLecturaArchivos:
    """Lectura de CSV y Excel de punta a punta."""

    def test_lee_csv_y_normaliza_encabezados(self, csv_bytes: bytes) -> None:
        resultado = leer_archivo(csv_bytes, "reporte.csv")
        assert resultado.filas == 8
        assert resultado.columnas == 31
        assert resultado.columnas_sin_reconocer == []
        for columna in COLUMNAS_REQUERIDAS:
            assert columna in resultado.df.columns

    def test_lee_csv_con_punto_y_coma(self, df_crudo: pd.DataFrame) -> None:
        contenido = df_crudo.to_csv(index=False, sep=";").encode("utf-8")
        resultado = leer_archivo(contenido, "reporte.csv")
        assert resultado.delimitador == ";"
        assert resultado.filas == 8

    def test_lee_excel(self, df_crudo: pd.DataFrame) -> None:
        buffer = io.BytesIO()
        df_crudo.to_excel(buffer, index=False, engine="openpyxl")
        resultado = leer_archivo(buffer.getvalue(), "reporte.xlsx")
        assert resultado.filas == 8
        assert COL_TOTAL in resultado.df.columns

    def test_rechaza_extension_no_compatible(self) -> None:
        with pytest.raises(ValueError, match="no compatible"):
            leer_archivo(b"contenido", "reporte.txt")

    def test_rechaza_archivo_vacio(self) -> None:
        with pytest.raises(ValueError, match="vac"):
            leer_archivo(b"", "reporte.csv")

    def test_csv_sin_filas_de_datos(self) -> None:
        contenido = ",".join(ENCABEZADOS).encode("utf-8")
        resultado = leer_archivo(contenido, "vacio.csv")
        assert resultado.filas == 0
        assert resultado.mensajes

    def test_mapeo_manual_tiene_prioridad(self) -> None:
        contenido = b"columna_rara,tipo,total\n1 jun 2026,Pedido,100\n"
        resultado = leer_archivo(
            contenido, "raro.csv", mapeo_manual={"columna_rara": COL_FECHA}
        )
        assert COL_FECHA in resultado.df.columns

    def test_ignora_columnas_sin_nombre(self) -> None:
        contenido = b"fecha/hora,tipo,total,\n1 jun 2026,Pedido,100,\n"
        resultado = leer_archivo(contenido, "extra.csv")
        assert "" not in resultado.df.columns

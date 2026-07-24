"""Pruebas de exportación a Excel y CSV, y de validación de archivos."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from services.alerts_service import generar_hallazgos, hallazgos_a_dataframe
from services.export_service import (
    exportar_csv,
    exportar_datos_originales,
    exportar_excel_simple,
    exportar_reporte_completo,
    nombre_archivo_exportacion,
    tabla_diccionario_metricas,
    tabla_resumen_ejecutivo,
)
from services.metrics_service import calcular_metricas, tabla_por_sku
from utils.constants import DICCIONARIO_METRICAS, ENCABEZADOS_ORIGINALES
from utils.formatting import (
    formato_entero,
    formato_moneda,
    formato_porcentaje,
    NO_DISPONIBLE,
)
from utils.validations import sanear_nombre_archivo, validar_archivo_subido, validar_columnas


class TestExportacionCSV:
    """Descargas en CSV."""

    def test_csv_usa_utf8_con_bom(self, df_limpio: pd.DataFrame) -> None:
        contenido = exportar_csv(df_limpio)
        assert contenido.startswith(b"\xef\xbb\xbf")   # Excel lo abre con acentos correctos

    def test_csv_con_etiquetas_legibles(self, df_limpio: pd.DataFrame) -> None:
        texto = exportar_csv(df_limpio).decode("utf-8-sig")
        assert "Id. del pedido" in texto or "SKU" in texto

    def test_csv_con_encabezados_originales(self, df_limpio: pd.DataFrame) -> None:
        texto = exportar_csv(df_limpio, usar_encabezados_originales=True).decode("utf-8-sig")
        assert "ventas de productos" in texto
        assert "tarifas fba" in texto

    def test_csv_de_un_dataframe_vacio(self) -> None:
        assert exportar_csv(pd.DataFrame()) is not None


class TestExportacionExcel:
    """Descargas en Excel."""

    def test_excel_simple_se_abre_correctamente(self, df_limpio: pd.DataFrame) -> None:
        contenido = exportar_excel_simple(tabla_por_sku(df_limpio), "Productos", "Prueba")
        libro = pd.ExcelFile(io.BytesIO(contenido))
        assert "Productos" in libro.sheet_names

    def test_excel_de_una_tabla_vacia_no_falla(self) -> None:
        contenido = exportar_excel_simple(pd.DataFrame(), "Vacía")
        assert pd.ExcelFile(io.BytesIO(contenido)).sheet_names == ["Vacía"]

    def test_datos_originales_conservan_los_encabezados_de_amazon(
        self, df_limpio: pd.DataFrame
    ) -> None:
        contenido = exportar_datos_originales(df_limpio)
        leido = pd.read_excel(io.BytesIO(contenido), sheet_name="Datos originales", skiprows=2)
        assert ENCABEZADOS_ORIGINALES["ventas_productos"] in leido.columns

    def test_reporte_completo_incluye_todas_las_hojas(self, df_limpio: pd.DataFrame) -> None:
        metricas = calcular_metricas(df_limpio)
        hallazgos = generar_hallazgos(df_limpio, metricas)
        contenido = exportar_reporte_completo(df_limpio, metricas, hallazgos=hallazgos)

        hojas = pd.ExcelFile(io.BytesIO(contenido)).sheet_names
        esperadas = [
            "Resumen", "Ventas por día", "Productos", "Pedidos", "Reembolsos",
            "Tarifas", "Estados", "Ciudades", "Liquidaciones", "Datos procesados",
            "Alertas", "Diccionario de métricas",
        ]
        for hoja in esperadas:
            assert hoja in hojas, f"Falta la hoja «{hoja}»"

    def test_reporte_completo_sin_la_hoja_de_datos(self, df_limpio: pd.DataFrame) -> None:
        contenido = exportar_reporte_completo(df_limpio, incluir_datos=False)
        assert "Datos procesados" not in pd.ExcelFile(io.BytesIO(contenido)).sheet_names

    def test_reporte_completo_de_un_periodo_vacio(self, df_limpio: pd.DataFrame) -> None:
        # No debe lanzar excepción aunque no haya un solo registro.
        contenido = exportar_reporte_completo(df_limpio.iloc[0:0])
        assert "Resumen" in pd.ExcelFile(io.BytesIO(contenido)).sheet_names

    def test_incluye_la_hoja_de_comparacion_cuando_hay_periodo_previo(
        self, df_limpio: pd.DataFrame
    ) -> None:
        from datetime import date

        from services.comparison_service import comparar_periodos

        comparacion = comparar_periodos(df_limpio, date(2026, 6, 5), date(2026, 6, 9))
        contenido = exportar_reporte_completo(df_limpio, comparacion=comparacion)
        assert "Comparación" in pd.ExcelFile(io.BytesIO(contenido)).sheet_names

    def test_nombre_de_archivo_lleva_marca_de_tiempo(self) -> None:
        nombre = nombre_archivo_exportacion("reporte")
        assert nombre.startswith("reporte_") and nombre.endswith(".xlsx")


class TestTablasDeReporte:
    """Tablas que alimentan las hojas del libro."""

    def test_resumen_ejecutivo_trae_las_metricas_clave(self, df_limpio: pd.DataFrame) -> None:
        tabla = tabla_resumen_ejecutivo(calcular_metricas(df_limpio))
        assert "Ventas brutas" in tabla["Métrica"].tolist()
        assert "Neto después de tarifas" in tabla["Métrica"].tolist()
        assert tabla["Fórmula"].notna().all()

    def test_el_diccionario_documenta_todas_las_metricas(self) -> None:
        tabla = tabla_diccionario_metricas()
        assert len(tabla) == len(DICCIONARIO_METRICAS)
        assert tabla["Fórmula"].str.len().gt(0).all()
        assert tabla["Qué significa"].str.len().gt(0).all()

    def test_alertas_en_tabla(self, df_limpio: pd.DataFrame) -> None:
        hallazgos = generar_hallazgos(df_limpio, calcular_metricas(df_limpio))
        tabla = hallazgos_a_dataframe(hallazgos)
        assert list(tabla.columns) == [
            "Severidad", "Categoría", "Hallazgo", "Detalle", "Recomendación"
        ]

    def test_alertas_vacias_conservan_las_columnas(self) -> None:
        assert not hallazgos_a_dataframe([]).columns.empty


class TestFormatoDePresentacion:
    """Formato monetario y porcentual con convención de México."""

    @pytest.mark.parametrize(
        "valor,esperado",
        [
            (1234.56, "$1,234.56 MXN"),
            (-1234.56, "-$1,234.56 MXN"),
            (0, "$0.00 MXN"),
            (1000000, "$1,000,000.00 MXN"),
            (None, NO_DISPONIBLE),
        ],
    )
    def test_formato_moneda(self, valor, esperado) -> None:
        assert formato_moneda(valor) == esperado

    @pytest.mark.parametrize(
        "valor,esperado",
        [(0.184, "18.4%"), (-0.05, "-5.0%"), (1.0, "100.0%"), (None, NO_DISPONIBLE)],
    )
    def test_formato_porcentaje(self, valor, esperado) -> None:
        assert formato_porcentaje(valor) == esperado

    def test_formato_entero(self) -> None:
        assert formato_entero(1234567) == "1,234,567"
        assert formato_entero(None) == NO_DISPONIBLE


class TestValidacionArchivos:
    """Seguridad de la carga de archivos."""

    @pytest.mark.parametrize(
        "entrada,prohibido",
        [
            ("../../etc/passwd", ".."),
            ("..\\..\\windows\\system32.csv", ".."),
            ("C:\\datos\\reporte.csv", ":"),
            ("/var/www/reporte.csv", "/"),
        ],
    )
    def test_sanea_rutas_maliciosas(self, entrada: str, prohibido: str) -> None:
        limpio = sanear_nombre_archivo(entrada)
        assert prohibido not in limpio
        assert "\\" not in limpio and "/" not in limpio

    def test_sanea_acentos_y_espacios(self) -> None:
        assert sanear_nombre_archivo("reporte junio ñ á.csv") == "reporte_junio_n_a.csv"

    def test_nombre_vacio_recibe_un_valor_por_defecto(self) -> None:
        assert sanear_nombre_archivo("") == "archivo_sin_nombre"

    def test_acepta_extensiones_validas(self) -> None:
        for extension in (".csv", ".xlsx", ".xls"):
            resultado = validar_archivo_subido(f"reporte{extension}", 1024)
            assert resultado.valido

    def test_rechaza_extension_no_permitida(self) -> None:
        resultado = validar_archivo_subido("reporte.exe", 1024)
        assert not resultado.valido
        assert "no está permitida" in resultado.errores[0]

    def test_rechaza_archivo_vacio(self) -> None:
        assert not validar_archivo_subido("reporte.csv", 0).valido

    def test_rechaza_archivo_demasiado_grande(self) -> None:
        resultado = validar_archivo_subido("reporte.csv", 999 * 1024 * 1024)
        assert not resultado.valido
        assert "límite" in resultado.errores[0]


class TestValidacionColumnas:
    """Comprobación de las columnas mínimas."""

    def test_acepta_el_conjunto_completo(self) -> None:
        from utils.constants import COLUMNAS_RECOMENDADAS, COLUMNAS_REQUERIDAS

        resultado = validar_columnas(set(COLUMNAS_REQUERIDAS) | set(COLUMNAS_RECOMENDADAS))
        assert resultado.valido
        assert not resultado.advertencias

    def test_rechaza_si_falta_una_columna_obligatoria(self) -> None:
        resultado = validar_columnas({"tipo", "total"})   # falta la fecha
        assert not resultado.valido
        assert "Fecha/hora" in resultado.errores[0]

    def test_advierte_si_faltan_columnas_recomendadas(self) -> None:
        from utils.constants import COLUMNAS_REQUERIDAS

        resultado = validar_columnas(set(COLUMNAS_REQUERIDAS))
        assert resultado.valido
        assert resultado.advertencias

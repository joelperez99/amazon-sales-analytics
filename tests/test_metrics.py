"""Pruebas del motor de métricas y de la comparación entre periodos.

Los valores esperados están calculados a mano a partir del conjunto de prueba
definido en ``conftest.py``:

======================  ==========  ======  =====  ========  ======  =====  =====
tipo                    pedido      ventas  imp.   retención com.    FBA    total
======================  ==========  ======  =====  ========  ======  =====  =====
Pedido (SKU1, 2 uds)    701-A        200.00  32.00   -16.00  -16.00 -30.00 170.00
Pedido (SKU2, 1 ud)     701-A        100.00  16.00    -8.00   -8.00 -15.00  85.00
Pedido (SKU1, 1 ud)     702-B       1100.00 176.00   -88.00  -88.00 -30.00 1070.00
Reembolso (1 ud)        702-B      -1100.00 -176.00    0.00   88.00   0.00 -1188.00
Ajuste                  —              0.00    0.00    0.00    0.00   0.00 -100.00
Tarifa inventario FBA   —              0.00    0.00    0.00    0.00   0.00  -50.00
Tarifa de servicio      —              0.00    0.00    0.00    0.00   0.00 -600.00
Transferencia           —              0.00    0.00    0.00    0.00   0.00 -5000.00
======================  ==========  ======  =====  ========  ======  =====  =====
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from services.comparison_service import (
    calcular_rango_anterior,
    comparar_periodos,
    filtrar_por_rango,
    tabla_comparativa,
)
from services.metrics_service import (
    calcular_metricas,
    curva_pareto,
    desglose_cascada,
    desglose_tarifas,
    detalle_pedidos,
    particionar,
    resumen_pedidos,
    serie_temporal,
    tabla_liquidaciones,
    tabla_por_estado,
    tabla_por_sku,
    tabla_por_tipo,
    tabla_reembolsos,
)
from utils.constants import COL_SKU, TIPO_PEDIDO
from utils.formatting import division_segura, variacion_porcentual


class TestParticiones:
    """Separación del reporte por tipo de transacción."""

    def test_cuenta_cada_tipo(self, df_limpio: pd.DataFrame) -> None:
        p = particionar(df_limpio)
        assert len(p.pedidos) == 3
        assert len(p.reembolsos) == 1
        assert len(p.ajustes) == 1
        assert len(p.inventario) == 1
        assert len(p.servicio) == 1
        assert len(p.transferencias) == 1

    def test_el_conjunto_financiero_excluye_transferencias(self, df_limpio: pd.DataFrame) -> None:
        p = particionar(df_limpio)
        assert len(p.financiero) == len(df_limpio) - 1


class TestVentas:
    """Ventas, pedidos y unidades."""

    def test_ventas_brutas_solo_cuentan_los_pedidos(self, df_limpio: pd.DataFrame) -> None:
        # El reembolso de −1,100 NO resta aquí: se reporta por separado.
        assert calcular_metricas(df_limpio)["ventas_brutas"] == pytest.approx(1400.00)

    def test_impuestos_y_venta_con_impuestos(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["impuestos_cobrados"] == pytest.approx(224.00)
        assert m["ventas_con_impuestos"] == pytest.approx(1624.00)

    def test_un_pedido_con_dos_lineas_cuenta_una_sola_vez(self, df_limpio: pd.DataFrame) -> None:
        """Regla central: los pedidos se cuentan por Id., no por número de filas."""
        m = calcular_metricas(df_limpio)
        assert m["pedidos_unicos"] == 2      # 701-A y 702-B
        assert len(particionar(df_limpio).pedidos) == 3  # pero son 3 líneas

    def test_unidades_vienen_de_la_columna_cantidad(self, df_limpio: pd.DataFrame) -> None:
        assert calcular_metricas(df_limpio)["unidades"] == pytest.approx(4.0)

    def test_promedios_de_venta(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["ticket_promedio"] == pytest.approx(700.00)          # 1400 / 2
        assert m["precio_promedio_unidad"] == pytest.approx(350.00)   # 1400 / 4
        assert m["unidades_por_pedido"] == pytest.approx(2.0)         # 4 / 2

    def test_cuenta_skus_y_productos(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["skus_vendidos"] == 2
        assert m["productos_vendidos"] == 2

    def test_transferencias_no_cuentan_como_transacciones(self, df_limpio: pd.DataFrame) -> None:
        assert calcular_metricas(df_limpio)["transacciones"] == 7  # 8 filas − 1 transferencia


class TestTarifas:
    """Cargos de Amazon."""

    def test_comision_neta_de_la_devolucion(self, df_limpio: pd.DataFrame) -> None:
        # −16 −8 −88 + 88 (comisión devuelta en el reembolso) = −24
        assert calcular_metricas(df_limpio)["tarifas_venta"] == pytest.approx(24.00)

    def test_tarifas_fba(self, df_limpio: pd.DataFrame) -> None:
        assert calcular_metricas(df_limpio)["tarifas_fba"] == pytest.approx(75.00)

    def test_retenciones_se_reportan_aparte(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["retenciones"] == pytest.approx(112.00)
        # Las retenciones NO forman parte del total de cargos de Amazon.
        assert m["total_cargos"] == pytest.approx(849.00)

    def test_cargos_operativos_por_tipo(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["tarifas_inventario"] == pytest.approx(50.00)
        assert m["tarifas_servicio"] == pytest.approx(600.00)

    def test_otros_cargos_no_incluyen_la_transferencia(self, df_limpio: pd.DataFrame) -> None:
        # 100 (ajuste) + 50 (inventario) + 600 (servicio); los 5,000 del retiro quedan fuera.
        assert calcular_metricas(df_limpio)["otros_cargos"] == pytest.approx(750.00)

    def test_los_cargos_se_presentan_en_positivo(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        for clave in ("tarifas_venta", "tarifas_fba", "total_cargos", "otros_cargos"):
            assert m[clave] >= 0

    def test_porcentajes_sobre_ventas(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["pct_cargos"] == pytest.approx(849.00 / 1400.00)
        assert m["pct_comisiones"] == pytest.approx(24.00 / 1400.00)
        assert m["pct_fba"] == pytest.approx(75.00 / 1400.00)


class TestReembolsos:
    """Devoluciones."""

    def test_importe_y_unidades(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["importe_reembolsado"] == pytest.approx(1188.00)
        assert m["unidades_reembolsadas"] == pytest.approx(1.0)
        assert m["pedidos_reembolsados"] == 1
        assert m["transacciones_reembolso"] == 1

    def test_tasa_de_reembolso(self, df_limpio: pd.DataFrame) -> None:
        assert calcular_metricas(df_limpio)["tasa_reembolso"] == pytest.approx(1188.00 / 1400.00)


class TestNeto:
    """Resultado neto y conciliación."""

    def test_neto_es_la_suma_de_total_sin_transferencias(self, df_limpio: pd.DataFrame) -> None:
        # 170 + 85 + 1070 − 1188 − 100 − 50 − 600 = −613
        assert calcular_metricas(df_limpio)["neto"] == pytest.approx(-613.00)

    def test_el_neto_reconstruido_coincide_con_la_columna_total(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["neto_reconstruido"] == pytest.approx(m["neto"])
        assert abs(m["diferencia_conciliacion"]) < 0.01

    def test_detecta_un_descuadre_de_conciliacion(self, df_limpio: pd.DataFrame) -> None:
        alterado = df_limpio.copy()
        alterado.loc[alterado.index[0], "total"] = 999.99
        assert abs(calcular_metricas(alterado)["diferencia_conciliacion"]) > 1

    def test_netos_unitarios(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["neto_por_pedido"] == pytest.approx(-613.00 / 2)
        assert m["neto_por_unidad"] == pytest.approx(-613.00 / 4)
        assert m["margen_neto"] == pytest.approx(-613.00 / 1400.00)

    def test_las_transferencias_se_reportan_por_separado(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio)
        assert m["transferencias"] == pytest.approx(5000.00)
        assert m["num_transferencias"] == 1


class TestDivisionEntreCero:
    """Ninguna métrica puede reventar por un denominador en cero."""

    def test_dataframe_vacio_devuelve_ceros_y_nd(self, df_limpio: pd.DataFrame) -> None:
        m = calcular_metricas(df_limpio.iloc[0:0])
        assert m["ventas_brutas"] == 0
        assert m["pedidos_unicos"] == 0
        assert m["ticket_promedio"] is None       # 0 / 0 -> N/D, no una excepción
        assert m["margen_neto"] is None

    def test_periodo_sin_pedidos_pero_con_cargos(self) -> None:
        from services.data_cleaner import limpiar_dataframe
        from utils.constants import COL_FECHA, COL_TIPO, COL_TOTAL

        solo_cargos = pd.DataFrame({
            COL_FECHA: ["1 jun 2026 12:00:00 a.m. GMT-7"],
            COL_TIPO: ["Tarifa de servicio"],
            COL_TOTAL: ["-600.00"],
            "otro": ["-600.00"],
        })
        limpio, _ = limpiar_dataframe(solo_cargos)
        m = calcular_metricas(limpio)
        assert m["ventas_brutas"] == 0
        assert m["pct_cargos"] is None            # no hay base contra la cual dividir
        assert m["neto"] == pytest.approx(-600.00)

    @pytest.mark.parametrize(
        "numerador,denominador,esperado",
        [(10, 2, 5.0), (10, 0, None), (0, 0, None), (None, 5, None), (10, None, None)],
    )
    def test_division_segura(self, numerador, denominador, esperado) -> None:
        assert division_segura(numerador, denominador) == esperado


class TestAgregados:
    """Series temporales y tablas por dimensión."""

    def test_serie_diaria_rellena_los_dias_sin_movimiento(self, df_limpio: pd.DataFrame) -> None:
        serie = serie_temporal(df_limpio, "Día")
        # Del 1 al 20 de junio hay 20 días, aunque solo 6 tengan transacciones.
        assert len(serie) == 20
        assert serie["ventas"].sum() == pytest.approx(1400.00)

    @pytest.mark.parametrize("frecuencia", ["Día", "Semana", "Mes"])
    def test_la_venta_total_no_cambia_con_la_agrupacion(
        self, df_limpio: pd.DataFrame, frecuencia: str
    ) -> None:
        serie = serie_temporal(df_limpio, frecuencia)
        assert serie["ventas"].sum() == pytest.approx(1400.00)
        assert serie["neto"].sum() == pytest.approx(-613.00)

    def test_los_pedidos_de_la_serie_no_se_duplican(self, df_limpio: pd.DataFrame) -> None:
        serie = serie_temporal(df_limpio, "Mes")
        assert serie["pedidos"].sum() == 2

    def test_tabla_por_sku(self, df_limpio: pd.DataFrame) -> None:
        tabla = tabla_por_sku(df_limpio)
        sku1 = tabla.loc[tabla[COL_SKU] == "SKU1"].iloc[0]
        assert sku1["ventas"] == pytest.approx(1300.00)   # 200 + 1100
        assert sku1["unidades"] == pytest.approx(3.0)
        assert sku1["pedidos"] == 2
        assert tabla["participacion"].sum() == pytest.approx(1.0)

    def test_tabla_por_estado(self, df_limpio: pd.DataFrame) -> None:
        tabla = tabla_por_estado(df_limpio)
        nl = tabla.loc[tabla["estado"] == "Nuevo León"].iloc[0]
        assert nl["ventas"] == pytest.approx(300.00)
        assert nl["pedidos"] == 1

    def test_tabla_por_tipo_incluye_transferencias(self, df_limpio: pd.DataFrame) -> None:
        tabla = tabla_por_tipo(df_limpio)
        assert len(tabla) == 6
        assert tabla["transacciones"].sum() == 8

    def test_liquidaciones(self, df_limpio: pd.DataFrame) -> None:
        tabla = tabla_liquidaciones(df_limpio)
        assert len(tabla) == 1
        assert tabla.iloc[0]["neto"] == pytest.approx(-613.00)
        assert tabla.iloc[0]["transferido"] == pytest.approx(5000.00)

    def test_resumen_de_pedidos_agrupa_las_lineas(self, df_limpio: pd.DataFrame) -> None:
        resumen = resumen_pedidos(df_limpio)
        pedido_a = resumen.loc[resumen["id_pedido"] == "701-A"].iloc[0]
        assert pedido_a["lineas"] == 2
        assert pedido_a["skus"] == 2
        assert pedido_a["unidades"] == pytest.approx(3.0)

    def test_detalle_de_pedidos_conserva_todas_las_filas(self, df_limpio: pd.DataFrame) -> None:
        assert len(detalle_pedidos(df_limpio)) == len(df_limpio)

    def test_reembolsos(self, df_limpio: pd.DataFrame) -> None:
        assert len(tabla_reembolsos(df_limpio)) == 1

    def test_pareto_acumula_hasta_uno(self, df_limpio: pd.DataFrame) -> None:
        pareto = curva_pareto(tabla_por_sku(df_limpio))
        assert pareto["participacion_acumulada"].iloc[-1] == pytest.approx(1.0)


class TestDesgloses:
    """Cascada y composición de tarifas."""

    def test_la_cascada_cierra_exactamente_en_el_neto(self, df_limpio: pd.DataFrame) -> None:
        cascada = desglose_cascada(df_limpio)
        escalones = cascada.loc[cascada["tipo"] != "total", "importe"].sum()
        total = cascada.loc[cascada["tipo"] == "total", "importe"].iloc[0]
        assert escalones == pytest.approx(total)
        assert total == pytest.approx(-613.00)

    def test_desglose_de_tarifas_suma_uno(self, df_limpio: pd.DataFrame) -> None:
        tarifas = desglose_tarifas(calcular_metricas(df_limpio))
        assert tarifas["participacion"].sum() == pytest.approx(1.0)
        assert (tarifas["importe"] > 0).all()


class TestComparacionPeriodos:
    """Comparación contra el periodo anterior."""

    def test_periodo_anterior_equivalente(self) -> None:
        inicio, fin = calcular_rango_anterior(date(2026, 6, 1), date(2026, 6, 30))
        # Junio tiene 30 días, así que compara contra los 30 días previos:
        # del 2 al 31 de mayo, ambos incluidos.
        assert (inicio, fin) == (date(2026, 5, 2), date(2026, 5, 31))
        assert (fin - inicio).days + 1 == 30

    def test_mes_anterior(self) -> None:
        inicio, fin = calcular_rango_anterior(date(2026, 6, 1), date(2026, 6, 30), "Mes anterior")
        assert (inicio, fin) == (date(2026, 5, 1), date(2026, 5, 30))

    def test_semana_anterior(self) -> None:
        inicio, fin = calcular_rango_anterior(date(2026, 6, 8), date(2026, 6, 14), "Semana anterior")
        assert (inicio, fin) == (date(2026, 6, 1), date(2026, 6, 7))

    def test_anio_anterior(self) -> None:
        inicio, fin = calcular_rango_anterior(date(2026, 6, 1), date(2026, 6, 30), "Año anterior")
        assert (inicio, fin) == (date(2025, 6, 1), date(2025, 6, 30))

    def test_el_rango_incluye_ambos_extremos(self, df_limpio: pd.DataFrame) -> None:
        # La fila del 1 de junio es de las 00:41; el filtro debe incluirla.
        recorte = filtrar_por_rango(df_limpio, date(2026, 6, 1), date(2026, 6, 1))
        assert len(recorte) == 2

    def test_compara_dos_periodos_con_datos(self, df_limpio: pd.DataFrame) -> None:
        comparacion = comparar_periodos(
            df_limpio, date(2026, 6, 5), date(2026, 6, 9), "Periodo anterior equivalente"
        )
        assert comparacion.hay_comparacion
        # Periodo actual: solo el pedido 702-B (1,100). Anterior: 701-A (300).
        assert comparacion.metricas_actual["ventas_brutas"] == pytest.approx(1100.00)
        assert comparacion.valor_anterior("ventas_brutas") == pytest.approx(300.00)
        assert comparacion.delta("ventas_brutas") == pytest.approx(800.00)
        assert comparacion.delta_pct("ventas_brutas") == pytest.approx(800.00 / 300.00)

    def test_sin_datos_previos_la_variacion_es_nd(self, df_limpio: pd.DataFrame) -> None:
        """Regla: nunca se calcula un porcentaje sobre una base de cero."""
        comparacion = comparar_periodos(
            df_limpio, date(2026, 6, 1), date(2026, 6, 30), "Año anterior"
        )
        assert not comparacion.hay_comparacion
        assert comparacion.valor_anterior("ventas_brutas") == 0
        assert comparacion.delta_pct("ventas_brutas") is None

    def test_modo_sin_comparacion(self, df_limpio: pd.DataFrame) -> None:
        comparacion = comparar_periodos(
            df_limpio, date(2026, 6, 1), date(2026, 6, 30), "Sin comparación"
        )
        assert not comparacion.hay_comparacion
        assert comparacion.metricas_actual["ventas_brutas"] == pytest.approx(1400.00)

    def test_periodo_personalizado(self, df_limpio: pd.DataFrame) -> None:
        comparacion = comparar_periodos(
            df_limpio, date(2026, 6, 5), date(2026, 6, 30), "Periodo personalizado",
            rango_personalizado=(date(2026, 6, 1), date(2026, 6, 4)),
        )
        assert comparacion.rango_anterior == (date(2026, 6, 1), date(2026, 6, 4))
        assert comparacion.valor_anterior("ventas_brutas") == pytest.approx(300.00)

    def test_tabla_comparativa(self, df_limpio: pd.DataFrame) -> None:
        comparacion = comparar_periodos(df_limpio, date(2026, 6, 5), date(2026, 6, 9))
        tabla = tabla_comparativa(comparacion)
        assert "Métrica" in tabla.columns
        assert len(tabla) == 10

    @pytest.mark.parametrize(
        "actual,anterior,esperado",
        [(120, 100, 0.20), (80, 100, -0.20), (100, 0, None), (100, None, None)],
    )
    def test_variacion_porcentual(self, actual, anterior, esperado) -> None:
        resultado = variacion_porcentual(actual, anterior)
        if esperado is None:
            assert resultado is None
        else:
            assert resultado == pytest.approx(esperado)


class TestRentabilidad:
    """Costos y utilidad."""

    def test_sin_costos_no_se_reporta_utilidad(self, df_limpio: pd.DataFrame) -> None:
        from services.profitability_service import calcular_rentabilidad, catalogo_vacio

        resultado = calcular_rentabilidad(df_limpio, catalogo_vacio())
        assert not resultado.hay_costos
        assert resultado.cobertura == 0

    def test_calcula_utilidad_con_costos(self, df_limpio: pd.DataFrame) -> None:
        from services.profitability_service import calcular_rentabilidad, normalizar_catalogo

        catalogo = normalizar_catalogo(pd.DataFrame({
            "sku": ["SKU1", "SKU2"],
            "costo_unitario": [100.0, 40.0],
        }))
        resultado = calcular_rentabilidad(df_limpio, catalogo)
        assert resultado.hay_costos
        # SKU1: 3 vendidas − 1 devuelta = 2 netas × 100 = 200. SKU2: 1 × 40 = 40.
        assert resultado.metricas["costo_mercancia"] == pytest.approx(240.00)

    def test_las_unidades_devueltas_no_cuestan(self, df_limpio: pd.DataFrame) -> None:
        from services.profitability_service import calcular_rentabilidad, normalizar_catalogo

        catalogo = normalizar_catalogo(pd.DataFrame({"sku": ["SKU1"], "costo_unitario": [100.0]}))
        tabla = calcular_rentabilidad(df_limpio, catalogo).tabla
        sku1 = tabla.loc[tabla[COL_SKU] == "SKU1"].iloc[0]
        assert sku1["unidades"] == pytest.approx(3.0)
        assert sku1["unidades_netas"] == pytest.approx(2.0)

    def test_reparte_la_publicidad_por_ventas(self, df_limpio: pd.DataFrame) -> None:
        from services.profitability_service import calcular_rentabilidad, normalizar_catalogo

        catalogo = normalizar_catalogo(pd.DataFrame({
            "sku": ["SKU1", "SKU2"], "costo_unitario": [100.0, 40.0],
        }))
        resultado = calcular_rentabilidad(df_limpio, catalogo, gasto_publicitario_periodo=140.0)
        assert resultado.metricas["gasto_publicitario"] == pytest.approx(140.0)
        # SKU1 tiene 1,300 de 1,400 en ventas: le toca el 92.86% del gasto.
        tabla = resultado.tabla
        sku1 = tabla.loc[tabla[COL_SKU] == "SKU1"].iloc[0]
        assert sku1["publicidad"] == pytest.approx(140.0 * 1300 / 1400)


class TestHallazgos:
    """Generación de alertas automáticas."""

    def test_genera_hallazgos_sin_lanzar_excepciones(self, df_limpio: pd.DataFrame) -> None:
        from services.alerts_service import generar_hallazgos

        m = calcular_metricas(df_limpio)
        comparacion = comparar_periodos(df_limpio, date(2026, 6, 5), date(2026, 6, 9))
        hallazgos = generar_hallazgos(df_limpio, m, comparacion)
        assert isinstance(hallazgos, list)
        # Con una tasa de reembolso del 85% y cargos del 61%, debe haber alertas.
        assert any(h.categoria == "Reembolsos" for h in hallazgos)
        assert any(h.categoria == "Tarifas" for h in hallazgos)

    def test_dataframe_vacio_produce_un_solo_hallazgo(self, df_limpio: pd.DataFrame) -> None:
        from services.alerts_service import generar_hallazgos

        hallazgos = generar_hallazgos(df_limpio.iloc[0:0], {})
        assert len(hallazgos) == 1
        assert "Sin datos" in hallazgos[0].titulo

    def test_detecta_la_concentracion_de_ventas(self, df_limpio: pd.DataFrame) -> None:
        from services.alerts_service import generar_hallazgos

        hallazgos = generar_hallazgos(df_limpio, calcular_metricas(df_limpio))
        # SKU1 concentra el 92.9% de la venta.
        assert any("Concentración" in h.titulo for h in hallazgos)

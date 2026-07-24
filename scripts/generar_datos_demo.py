"""Generador de datos simulados con el formato exacto del reporte de Amazon MX.

Produce un CSV con los encabezados en español, fechas escritas como
``1 jun 2026 12:41:59 a.m. GMT-7`` e importes con separador de miles, incluyendo
pedidos, reembolsos, ajustes, tarifas de inventario, tarifas de servicio y
transferencias.

Uso desde la terminal::

    python scripts/generar_datos_demo.py
    python scripts/generar_datos_demo.py --meses 3 --salida data/demo/mi_demo.csv
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# La raíz del proyecto debe estar en el path si el script se ejecuta directamente.
if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MESES_ABREVIADOS = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

#: Catálogo simulado: (sku, descripción, precio sin impuesto, tarifa FBA).
CATALOGO: list[tuple[str, str, float, float]] = [
    ("EC000001", "Super Cria Sustituto De Leche para Cachorros 450g", 255.17, 39.00),
    ("EC000002", "Super Cria Sustituto de Leche Vitaminado para Gatos Kitten", 342.24, 52.54),
    ("EC000003", "Super Cria Alimento Premium para Perro Adulto 2kg", 489.66, 68.20),
    ("EC000004", "Super Cria Suplemento Vitamínico Multiespecie 250ml", 189.66, 31.40),
    ("EC000005", "SUPER-CRIA MASCOTA DENTAL-LINE, Premios Dentales para Perro", 165.52, 38.20),
    ("EC000006", "Super Cria Arena Aglutinante para Gato 5kg", 218.10, 45.80),
    ("EC000007", "Super Cria Shampoo Hipoalergénico para Mascotas 500ml", 142.24, 29.60),
]

#: (ciudad, estado) con el peso de cada plaza en la venta nacional.
UBICACIONES: list[tuple[str, str, float]] = [
    ("CIUDAD DE MEXICO", "CIUDAD DE MEXICO", 0.20),
    ("MONTERREY", "NUEVO LEON", 0.13),
    ("GUADALAJARA", "JALISCO", 0.12),
    ("PUEBLA", "PUEBLA", 0.07),
    ("QUERETARO", "QUERETARO", 0.06),
    ("MERIDA", "YUCATAN", 0.06),
    ("TIJUANA", "BAJA CALIFORNIA", 0.06),
    ("LEON", "GUANAJUATO", 0.05),
    ("TOLUCA", "MEXICO", 0.05),
    ("CANCUN", "QUINTANA ROO", 0.04),
    ("SAN LUIS POTOSI", "SAN LUIS POTOSI", 0.04),
    ("HERMOSILLO", "SONORA", 0.04),
    ("CULIACAN", "SINALOA", 0.03),
    ("VERACRUZ", "VERACRUZ", 0.03),
    ("MORELIA", "MICHOACAN", 0.02),
]

CODIGOS_POSTALES = [
    "03020", "14700", "64840", "44360", "72023", "76000", "97219",
    "22454", "37000", "50000", "77500", "78397", "83000", "80000",
]

#: Tasa de IVA aplicada por el facilitador del marketplace.
IVA = 0.16
#: Comisión por referencia de Amazon México.
COMISION = 0.08

ENCABEZADOS = [
    "fecha/hora", "Id. de liquidación", "tipo", "Id. del pedido", "sku", "descripción",
    "cantidad", "marketplace", "cumplimiento", "ciudad del pedido", "estado del pedido",
    "código postal del pedido", "modelo de recaudación de impuestos", "ventas de productos",
    "impuesto de ventas de productos", "créditos de envío", "impuesto de abono de envío",
    "créditos por envoltorio de regalo", "impuesto de créditos de envoltura",
    "Tarifa reglamentaria", "Impuesto sobre tarifa reglamentaria", "descuentos promocionales",
    "impuesto de reembolsos promocionales", "impuesto de retenciones en la plataforma",
    "tarifas de venta", "tarifas fba", "tarifas de otra transacción", "otro", "total",
    "Estado de la transacción", "Fecha de liberación de la transacción",
]


def formato_fecha_amazon(momento: datetime) -> str:
    """``1 jun 2026 12:41:59 a.m. GMT-7`` (el mismo formato del reporte real)."""
    hora_12 = momento.hour % 12 or 12
    meridiano = "a.m." if momento.hour < 12 else "p.m."
    return (
        f"{momento.day} {MESES_ABREVIADOS[momento.month]} {momento.year} "
        f"{hora_12}:{momento.minute:02d}:{momento.second:02d} {meridiano} GMT-7"
    )


def formato_importe(valor: float) -> str:
    """Importe con separador de miles, como lo escribe Amazon: ``-15,874.01``."""
    if valor == 0:
        return "0"
    return f"{valor:,.2f}"


def _fila_vacia() -> dict[str, str]:
    """Fila con todos los campos monetarios en cero."""
    return {columna: "" for columna in ENCABEZADOS} | {
        columna: "0" for columna in ENCABEZADOS[13:29]
    }


def generar_transacciones(
    inicio: datetime, dias: int, semilla: int = 42
) -> list[dict[str, str]]:
    """Genera la lista de transacciones simuladas del periodo."""
    aleatorio = random.Random(semilla)
    filas: list[dict[str, str]] = []
    pedidos_realizados: list[tuple[str, tuple, datetime, str, str, str]] = []

    ciudades = [(c, e) for c, e, _ in UBICACIONES]
    pesos = [p for _, _, p in UBICACIONES]

    # Una liquidación nueva cada 14 días, como el ciclo real de Amazon.
    liquidacion_base = 26_500_000_000
    liquidaciones: list[tuple[str, datetime, datetime]] = []
    for indice in range(dias // 14 + 1):
        inicio_liq = inicio + timedelta(days=indice * 14)
        liquidaciones.append((
            str(liquidacion_base + indice * 123_457),
            inicio_liq,
            inicio_liq + timedelta(days=14),
        ))

    def liquidacion_de(momento: datetime) -> str:
        for identificador, desde, hasta in liquidaciones:
            if desde <= momento < hasta:
                return identificador
        return liquidaciones[-1][0]

    # --- Pedidos -------------------------------------------------------------
    for dia in range(dias):
        fecha = inicio + timedelta(days=dia)
        # Fin de semana con menos movimiento; tendencia ligeramente creciente.
        base = 9 if fecha.weekday() < 5 else 6
        pedidos_del_dia = max(1, int(aleatorio.gauss(base + dia * 0.05, 2.2)))

        for _ in range(pedidos_del_dia):
            momento = fecha + timedelta(
                hours=aleatorio.randint(0, 23),
                minutes=aleatorio.randint(0, 59),
                seconds=aleatorio.randint(0, 59),
            )
            id_pedido = (
                f"{aleatorio.choice(['701', '702'])}-"
                f"{aleatorio.randint(1000000, 9999999)}-{aleatorio.randint(1000000, 9999999)}"
            )
            ciudad, estado = aleatorio.choices(ciudades, weights=pesos, k=1)[0]
            codigo_postal = aleatorio.choice(CODIGOS_POSTALES)
            liquidacion = liquidacion_de(momento)
            liberacion = momento + timedelta(days=aleatorio.randint(7, 12))

            # Un 12% de los pedidos lleva dos SKU distintos: así se prueba que el
            # conteo de pedidos únicos no dependa del número de líneas.
            productos = aleatorio.sample(CATALOGO, k=2 if aleatorio.random() < 0.12 else 1)

            for sku, descripcion, precio, tarifa_fba in productos:
                cantidad = 1 if aleatorio.random() < 0.85 else 2
                ventas = round(precio * cantidad, 2)
                impuesto = round(ventas * IVA, 2)
                comision = -round(ventas * COMISION, 2)
                fba = -round(tarifa_fba * cantidad, 2)
                retencion = -impuesto
                total = round(ventas + impuesto + comision + fba + retencion, 2)

                fila = _fila_vacia()
                fila.update({
                    "fecha/hora": formato_fecha_amazon(momento),
                    "Id. de liquidación": liquidacion,
                    "tipo": "Pedido",
                    "Id. del pedido": id_pedido,
                    "sku": sku,
                    "descripción": descripcion,
                    "cantidad": str(cantidad),
                    "marketplace": "amazon.com.mx",
                    "cumplimiento": "Amazon",
                    "ciudad del pedido": ciudad,
                    "estado del pedido": estado,
                    "código postal del pedido": codigo_postal,
                    "modelo de recaudación de impuestos": "MarketplaceFacilitator",
                    "ventas de productos": formato_importe(ventas),
                    "impuesto de ventas de productos": formato_importe(impuesto),
                    "impuesto de retenciones en la plataforma": formato_importe(retencion),
                    "tarifas de venta": formato_importe(comision),
                    "tarifas fba": formato_importe(fba),
                    "total": formato_importe(total),
                    "Estado de la transacción": "Lanzado",
                    "Fecha de liberación de la transacción": formato_fecha_amazon(liberacion),
                })
                filas.append(fila)
                pedidos_realizados.append(
                    (id_pedido, (sku, descripcion, precio, tarifa_fba), momento,
                     ciudad, estado, codigo_postal)
                )

    # --- Reembolsos (≈3% de los pedidos, algunos días después) ---------------
    for id_pedido, producto, momento, ciudad, estado, codigo_postal in pedidos_realizados:
        if aleatorio.random() >= 0.03:
            continue
        sku, descripcion, precio, _ = producto
        momento_reembolso = momento + timedelta(days=aleatorio.randint(3, 20))
        if momento_reembolso > inicio + timedelta(days=dias):
            continue

        ventas = -round(precio, 2)
        impuesto = round(ventas * IVA, 2)
        comision_devuelta = round(abs(ventas) * COMISION * 0.8, 2)
        retencion = -impuesto
        total = round(ventas + impuesto + comision_devuelta + retencion, 2)

        fila = _fila_vacia()
        fila.update({
            "fecha/hora": formato_fecha_amazon(momento_reembolso),
            "Id. de liquidación": liquidacion_de(momento_reembolso),
            "tipo": "Reembolso",
            "Id. del pedido": id_pedido,
            "sku": sku,
            "descripción": descripcion,
            "cantidad": "1",
            "marketplace": "amazon.com.mx",
            "cumplimiento": "Amazon",
            "ciudad del pedido": ciudad,
            "estado del pedido": estado,
            "código postal del pedido": codigo_postal,
            "ventas de productos": formato_importe(ventas),
            "impuesto de ventas de productos": formato_importe(impuesto),
            "impuesto de retenciones en la plataforma": formato_importe(retencion),
            "tarifas de venta": formato_importe(comision_devuelta),
            "total": formato_importe(total),
            "Estado de la transacción": "Lanzado",
            "Fecha de liberación de la transacción": formato_fecha_amazon(momento_reembolso),
        })
        filas.append(fila)

    # --- Cargos operativos ---------------------------------------------------
    def cargo(momento: datetime, tipo: str, descripcion: str, importe: float) -> dict[str, str]:
        fila = _fila_vacia()
        fila.update({
            "fecha/hora": formato_fecha_amazon(momento),
            "Id. de liquidación": liquidacion_de(momento),
            "tipo": tipo,
            "descripción": descripcion,
            "marketplace": "Amazon.com.mx",
            "otro": formato_importe(importe),
            "total": formato_importe(importe),
            "Estado de la transacción": "Lanzado",
            "Fecha de liberación de la transacción": formato_fecha_amazon(momento),
        })
        return fila

    for indice in range(dias // 30 + 1):
        mes = inicio + timedelta(days=indice * 30)
        filas.append(cargo(
            mes + timedelta(days=6, hours=5),
            "Tarifa de inventario FBA",
            "Tarifas de almacenamiento de Logística de Amazon",
            -round(aleatorio.uniform(120, 260), 2),
        ))
        filas.append(cargo(
            mes + timedelta(days=15, hours=0, minutes=8),
            "Tarifa de servicio", "Suscripción", -600.00,
        ))
        filas.append(cargo(
            mes + timedelta(days=18, hours=0, minutes=8),
            "Tarifa de inventario FBA", "Tarifa por almacenamiento prolongado",
            -round(aleatorio.uniform(3, 40), 2),
        ))
        filas.append(cargo(
            mes + timedelta(days=11, hours=7, minutes=35),
            "Ajuste", "", -round(aleatorio.uniform(200, 1200), 2),
        ))

    # --- Transferencias al banco (cierre de cada liquidación) ----------------
    # El importe transferido es el neto acumulado de esa liquidación, con signo
    # invertido: es dinero que sale de la cuenta de Amazon hacia el banco.
    for identificador, desde, hasta in liquidaciones:
        momento_transferencia = hasta - timedelta(days=1, hours=11)
        if momento_transferencia > inicio + timedelta(days=dias):
            continue
        neto = sum(
            float(str(f["total"]).replace(",", "") or 0)
            for f in filas
            if f["Id. de liquidación"] == identificador
        )
        if abs(neto) < 1:
            continue
        fila = _fila_vacia()
        fila.update({
            "fecha/hora": formato_fecha_amazon(momento_transferencia),
            "Id. de liquidación": identificador,
            "tipo": "Trasferir",
            "descripción": "Para la cuenta que termina en 553",
            "otro": formato_importe(-round(neto, 2)),
            "total": formato_importe(-round(neto, 2)),
            "Estado de la transacción": "Lanzado",
            "Fecha de liberación de la transacción": formato_fecha_amazon(momento_transferencia),
        })
        filas.append(fila)

    return filas


def generar_archivo_demo(
    salida: Path | str | None = None, meses: int = 2, semilla: int = 42
) -> Path:
    """Escribe el CSV de demostración y devuelve su ruta.

    Args:
        salida: ruta destino.  Por omisión ``data/demo/transacciones_demo.csv``.
        meses: cuántos meses de historia generar.
        semilla: semilla del generador (misma semilla, mismos datos).
    """
    from utils.config import get_settings

    settings = get_settings()
    destino = Path(salida) if salida else settings.ruta_datos / "demo" / "transacciones_demo.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)

    dias = meses * 30
    # Se generan datos que terminan "ayer" para que el rango se vea vigente.
    inicio = (datetime.now() - timedelta(days=dias)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    filas = generar_transacciones(inicio, dias, semilla)
    df = pd.DataFrame(filas, columns=ENCABEZADOS)

    # Se ordena por fecha real para que el archivo se parezca al de Amazon.
    from utils.date_parser import parsear_serie_fechas

    orden = parsear_serie_fechas(df["fecha/hora"])
    df = df.iloc[orden.argsort(kind="stable").values].reset_index(drop=True)

    df.to_csv(destino, index=False, encoding="utf-8-sig")
    return destino


def main() -> None:
    """Punto de entrada de la línea de comandos."""
    analizador = argparse.ArgumentParser(
        description="Genera un reporte de transacciones simulado de Amazon México."
    )
    analizador.add_argument("--salida", type=str, default=None, help="Ruta del archivo CSV.")
    analizador.add_argument("--meses", type=int, default=2, help="Meses de historia (por omisión 2).")
    analizador.add_argument("--semilla", type=int, default=42, help="Semilla aleatoria.")
    argumentos = analizador.parse_args()

    ruta = generar_archivo_demo(argumentos.salida, argumentos.meses, argumentos.semilla)
    df = pd.read_csv(ruta, dtype=str)
    print(f"Archivo generado: {ruta}")
    print(f"Transacciones: {len(df):,}")
    print(df["tipo"].value_counts().to_string())


if __name__ == "__main__":
    main()

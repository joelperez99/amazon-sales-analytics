"""Configuración compartida de las pruebas y datos simulados."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# La raíz del proyecto debe estar en el path para importar los módulos.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from services.data_cleaner import limpiar_dataframe  # noqa: E402

#: Encabezados exactos del reporte de transacciones de Amazon México.
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


def fila(
    fecha: str,
    tipo: str,
    id_pedido: str = "",
    sku: str = "",
    descripcion: str = "",
    cantidad: str = "",
    ventas: str = "0",
    impuesto: str = "0",
    retencion: str = "0",
    comision: str = "0",
    fba: str = "0",
    otro: str = "0",
    total: str = "0",
    liquidacion: str = "26665888231",
    ciudad: str = "",
    estado: str = "",
    cp: str = "",
    marketplace: str = "amazon.com.mx",
    liberacion: str = "",
) -> dict[str, str]:
    """Construye una fila con los encabezados originales de Amazon."""
    valores = dict.fromkeys(ENCABEZADOS, "")
    valores.update(dict.fromkeys(ENCABEZADOS[13:29], "0"))
    valores.update({
        "fecha/hora": fecha,
        "Id. de liquidación": liquidacion,
        "tipo": tipo,
        "Id. del pedido": id_pedido,
        "sku": sku,
        "descripción": descripcion,
        "cantidad": cantidad,
        "marketplace": marketplace,
        "cumplimiento": "Amazon" if tipo in {"Pedido", "Reembolso"} else "",
        "ciudad del pedido": ciudad,
        "estado del pedido": estado,
        "código postal del pedido": cp,
        "modelo de recaudación de impuestos": "MarketplaceFacilitator" if tipo == "Pedido" else "",
        "ventas de productos": ventas,
        "impuesto de ventas de productos": impuesto,
        "impuesto de retenciones en la plataforma": retencion,
        "tarifas de venta": comision,
        "tarifas fba": fba,
        "otro": otro,
        "total": total,
        "Estado de la transacción": "Lanzado",
        "Fecha de liberación de la transacción": liberacion or fecha,
    })
    return valores


#: Conjunto de prueba con todos los tipos de transacción.
#:
#: Composición pensada para verificar las reglas de negocio:
#:  * el pedido ``701-A`` tiene **dos líneas** (dos SKU): debe contar como 1 pedido
#:  * hay un reembolso, un ajuste, una tarifa de inventario, una de servicio y una
#:    transferencia
FILAS_BASE: list[dict[str, str]] = [
    # Pedido con dos líneas: 1 pedido, 3 unidades.
    fila("1 jun 2026 12:41:59 a.m. GMT-7", "Pedido", "701-A", "SKU1", "Producto uno",
         "2", ventas="200.00", impuesto="32.00", retencion="-16.00",
         comision="-16.00", fba="-30.00", total="170.00",
         ciudad="MONTERREY", estado="NUEVO LEON", cp="64840"),
    fila("1 jun 2026 12:41:59 a.m. GMT-7", "Pedido", "701-A", "SKU2", "Producto dos",
         "1", ventas="100.00", impuesto="16.00", retencion="-8.00",
         comision="-8.00", fba="-15.00", total="85.00",
         ciudad="MONTERREY", estado="NUEVO LEON", cp="64840"),
    # Pedido sencillo, con importe que trae separador de miles.
    fila("5 jun 2026 3:42:32 p.m. GMT-7", "Pedido", "702-B", "SKU1", "Producto uno",
         "1", ventas="1,100.00", impuesto="176.00", retencion="-88.00",
         comision="-88.00", fba="-30.00", total="1,070.00",
         ciudad="CIUDAD DE MEXICO", estado="CIUDAD DE MEXICO", cp="03020"),
    # Reembolso: la comisión regresa con signo positivo.
    fila("10 jun 2026 11:59:50 a.m. GMT-7", "Reembolso", "702-B", "SKU1", "Producto uno",
         "1", ventas="-1,100.00", impuesto="-176.00", comision="88.00",
         total="-1,188.00", ciudad="CIUDAD DE MEXICO", estado="CIUDAD DE MEXICO", cp="03020"),
    # Cargos operativos: el importe llega en «otro» y en «total».
    fila("12 jun 2026 7:35:06 a.m. GMT-7", "Ajuste", otro="-100.00", total="-100.00"),
    fila("15 jun 2026 5:28:19 a.m. GMT-7", "Tarifa de inventario FBA",
         descripcion="Tarifas de almacenamiento", otro="-50.00", total="-50.00",
         marketplace="Amazon.com.mx"),
    fila("16 jun 2026 12:08:20 a.m. GMT-7", "Tarifa de servicio",
         descripcion="Suscripción", otro="-600.00", total="-600.00",
         marketplace="Amazon.com.mx"),
    # Transferencia: retiro al banco, se excluye de todos los importes.
    fila("20 jun 2026 1:05:20 p.m. GMT-7", "Trasferir",
         descripcion="Para la cuenta que termina en 553",
         otro="-5,000.00", total="-5,000.00", marketplace=""),
]


@pytest.fixture
def df_crudo() -> pd.DataFrame:
    """DataFrame con los encabezados originales, todo como texto."""
    return pd.DataFrame(FILAS_BASE, columns=ENCABEZADOS)


@pytest.fixture
def df_limpio(df_crudo: pd.DataFrame) -> pd.DataFrame:
    """DataFrame ya normalizado y tipado, listo para el motor de métricas."""
    from services.amazon_parser import mapear_columnas

    mapeo, _ = mapear_columnas(list(df_crudo.columns))
    limpio, _ = limpiar_dataframe(df_crudo.rename(columns=mapeo))
    return limpio


@pytest.fixture
def csv_bytes(df_crudo: pd.DataFrame) -> bytes:
    """El mismo conjunto serializado como CSV UTF-8 con BOM."""
    return df_crudo.to_csv(index=False).encode("utf-8-sig")

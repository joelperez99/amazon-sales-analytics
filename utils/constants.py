"""Constantes del dominio: encabezados, tipos de transacción, catálogos y paleta.

Este módulo es la única fuente de verdad sobre cómo se llaman internamente las
columnas del reporte de Amazon.  El resto de la aplicación trabaja siempre con los
nombres canónicos definidos aquí.
"""

from __future__ import annotations

import unicodedata

# =============================================================================
# Normalización de texto
# =============================================================================


# Caracteres de ancho cero e invisibles que a veces contamina el reporte de
# Amazon (espacio de ancho cero, uniones, marca de orden de bytes). No son
# espacios "normales", así que ``str.split`` no los elimina y crearían valores
# casi idénticos —"Nuevo León" vs "Nuevo​León"— que no se agrupan.
_CARACTERES_INVISIBLES = ("​", "‌", "‍", "⁠", "﻿", "­")


def normalizar_texto(valor: object) -> str:
    """Normaliza un texto para poder compararlo.

    Pasa a minúsculas, elimina acentos, caracteres invisibles, signos de
    puntuación irrelevantes y espacios duplicados (incluidos los espacios Unicode
    como el no separable).  ``"Id. del Pedido "`` y ``"id del pedido"`` producen
    el mismo resultado, igual que ``"NUEVO  LEÓN"`` y ``"nuevo leon"``.
    """
    if valor is None:
        return ""
    texto = str(valor)
    # Descompone y elimina las marcas diacríticas (á -> a, ñ -> n).
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    # Sustituye por un espacio: la puntuación, cualquier espacio Unicode (incluido
    # el no separable) y los caracteres invisibles de ancho cero. Tratarlos como
    # espacio —en vez de borrarlos— evita tanto los duplicados por doble espacio
    # como que dos palabras queden pegadas cuando el separador es invisible.
    texto = "".join(
        " " if (c in ".:;_-/\\()[]{}#*\"'" or c.isspace() or c in _CARACTERES_INVISIBLES)
        else c
        for c in texto
    )
    return " ".join(texto.split())


# =============================================================================
# Columnas canónicas
# =============================================================================

# Nombres internos usados en todo el código.
COL_FECHA = "fecha_hora"
COL_LIQUIDACION = "id_liquidacion"
COL_TIPO = "tipo"
COL_PEDIDO = "id_pedido"
COL_SKU = "sku"
COL_DESCRIPCION = "descripcion"
COL_CANTIDAD = "cantidad"
COL_MARKETPLACE = "marketplace"
#: Canal de cumplimiento: "Amazon" (FBA) o "Comerciante" (FBM).
COL_CUMPLIMIENTO = "cumplimiento"
COL_CIUDAD = "ciudad"
COL_ESTADO = "estado"
COL_CP = "codigo_postal"
COL_MODELO_IMPUESTOS = "modelo_impuestos"
COL_VENTAS = "ventas_productos"
COL_IMPUESTO_VENTAS = "impuesto_ventas_productos"
COL_CREDITOS_ENVIO = "creditos_envio"
COL_IMPUESTO_ENVIO = "impuesto_envio"
COL_CREDITOS_ENVOLTORIO = "creditos_envoltorio"
COL_IMPUESTO_ENVOLTORIO = "impuesto_envoltorio"
COL_TARIFA_REGLAMENTARIA = "tarifa_reglamentaria"
COL_IMPUESTO_REGLAMENTARIO = "impuesto_tarifa_reglamentaria"
COL_DESCUENTOS = "descuentos_promocionales"
COL_IMPUESTO_DESCUENTOS = "impuesto_descuentos_promocionales"
COL_RETENCIONES = "retenciones_plataforma"
COL_TARIFAS_VENTA = "tarifas_venta"
COL_TARIFAS_FBA = "tarifas_fba"
COL_TARIFAS_OTRAS = "tarifas_otras"
COL_OTRO = "otro"
COL_TOTAL = "total"
COL_ESTADO_TRANSACCION = "estado_transaccion"
COL_FECHA_LIBERACION = "fecha_liberacion"

# Columnas derivadas que agrega el limpiador.
COL_FECHA_DIA = "fecha"
COL_ANIO = "anio"
COL_MES = "mes"
COL_MES_NOMBRE = "mes_nombre"
COL_SEMANA = "semana"
COL_DIA_SEMANA = "dia_semana"
COL_HORA = "hora"
COL_HASH = "row_hash"
COL_ES_DUPLICADO = "es_duplicado"

# Etiquetas legibles (para tablas y exportaciones).
ETIQUETAS_COLUMNAS: dict[str, str] = {
    COL_FECHA: "Fecha/hora",
    COL_LIQUIDACION: "Id. de liquidación",
    COL_TIPO: "Tipo",
    COL_PEDIDO: "Id. del pedido",
    COL_SKU: "SKU",
    COL_DESCRIPCION: "Descripción",
    COL_CANTIDAD: "Cantidad",
    COL_MARKETPLACE: "Marketplace",
    COL_CUMPLIMIENTO: "Cumplimiento",
    COL_CIUDAD: "Ciudad",
    COL_ESTADO: "Estado",
    COL_CP: "Código postal",
    COL_MODELO_IMPUESTOS: "Modelo de impuestos",
    COL_VENTAS: "Ventas de productos",
    COL_IMPUESTO_VENTAS: "Impuesto de ventas",
    COL_CREDITOS_ENVIO: "Créditos de envío",
    COL_IMPUESTO_ENVIO: "Impuesto de envío",
    COL_CREDITOS_ENVOLTORIO: "Créditos de envoltorio",
    COL_IMPUESTO_ENVOLTORIO: "Impuesto de envoltorio",
    COL_TARIFA_REGLAMENTARIA: "Tarifa reglamentaria",
    COL_IMPUESTO_REGLAMENTARIO: "Impuesto sobre tarifa reglamentaria",
    COL_DESCUENTOS: "Descuentos promocionales",
    COL_IMPUESTO_DESCUENTOS: "Impuesto de descuentos promocionales",
    COL_RETENCIONES: "Retenciones en la plataforma",
    COL_TARIFAS_VENTA: "Tarifas de venta",
    COL_TARIFAS_FBA: "Tarifas FBA",
    COL_TARIFAS_OTRAS: "Tarifas de otra transacción",
    COL_OTRO: "Otro",
    COL_TOTAL: "Total",
    COL_ESTADO_TRANSACCION: "Estado de la transacción",
    COL_FECHA_LIBERACION: "Fecha de liberación",
    COL_FECHA_DIA: "Fecha",
    COL_ANIO: "Año",
    COL_MES: "Mes",
    COL_MES_NOMBRE: "Nombre del mes",
    COL_SEMANA: "Semana",
    COL_DIA_SEMANA: "Día de la semana",
    COL_HORA: "Hora",
}

# Encabezado original tal como llega en el reporte de Amazon México.
# Se usa para reconstruir el archivo descargable con los nombres originales.
ENCABEZADOS_ORIGINALES: dict[str, str] = {
    COL_FECHA: "fecha/hora",
    COL_LIQUIDACION: "Id. de liquidación",
    COL_TIPO: "tipo",
    COL_PEDIDO: "Id. del pedido",
    COL_SKU: "sku",
    COL_DESCRIPCION: "descripción",
    COL_CANTIDAD: "cantidad",
    COL_MARKETPLACE: "marketplace",
    COL_CUMPLIMIENTO: "cumplimiento",
    COL_CIUDAD: "ciudad del pedido",
    COL_ESTADO: "estado del pedido",
    COL_CP: "código postal del pedido",
    COL_MODELO_IMPUESTOS: "modelo de recaudación de impuestos",
    COL_VENTAS: "ventas de productos",
    COL_IMPUESTO_VENTAS: "impuesto de ventas de productos",
    COL_CREDITOS_ENVIO: "créditos de envío",
    COL_IMPUESTO_ENVIO: "impuesto de abono de envío",
    COL_CREDITOS_ENVOLTORIO: "créditos por envoltorio de regalo",
    COL_IMPUESTO_ENVOLTORIO: "impuesto de créditos de envoltura",
    COL_TARIFA_REGLAMENTARIA: "Tarifa reglamentaria",
    COL_IMPUESTO_REGLAMENTARIO: "Impuesto sobre tarifa reglamentaria",
    COL_DESCUENTOS: "descuentos promocionales",
    COL_IMPUESTO_DESCUENTOS: "impuesto de reembolsos promocionales",
    COL_RETENCIONES: "impuesto de retenciones en la plataforma",
    COL_TARIFAS_VENTA: "tarifas de venta",
    COL_TARIFAS_FBA: "tarifas fba",
    COL_TARIFAS_OTRAS: "tarifas de otra transacción",
    COL_OTRO: "otro",
    COL_TOTAL: "total",
    COL_ESTADO_TRANSACCION: "Estado de la transacción",
    COL_FECHA_LIBERACION: "Fecha de liberación de la transacción",
}

# -----------------------------------------------------------------------------
# Alias aceptados por columna (ya normalizados con ``normalizar_texto``).
# El primer alias de cada lista es el nombre preferido del reporte de Amazon MX.
# -----------------------------------------------------------------------------
ALIAS_COLUMNAS: dict[str, list[str]] = {
    COL_FECHA: [
        "fecha hora", "fecha y hora", "date time", "fecha de la transaccion",
        "fecha", "date", "purchase date", "fecha de compra",
    ],
    COL_LIQUIDACION: [
        "id de liquidacion", "id liquidacion", "settlement id", "liquidacion",
        "numero de liquidacion", "id del pago",
    ],
    COL_TIPO: ["tipo", "type", "tipo de transaccion", "transaction type"],
    COL_PEDIDO: [
        "id del pedido", "id de pedido", "id pedido", "order id", "amazon order id",
        "numero de pedido", "pedido",
    ],
    COL_SKU: ["sku", "sku del vendedor", "seller sku", "sku vendedor", "msku"],
    COL_DESCRIPCION: [
        "descripcion", "description", "titulo del producto", "nombre del producto",
        "product name", "titulo",
    ],
    COL_CANTIDAD: [
        "cantidad", "quantity", "cantidad de unidades", "unidades", "qty",
        "quantity purchased",
    ],
    COL_MARKETPLACE: ["marketplace", "mercado", "sitio", "tienda"],
    COL_CUMPLIMIENTO: [
        "cumplimiento", "fulfillment", "canal de cumplimiento", "fulfilment",
        "gestion logistica",
    ],
    COL_CIUDAD: ["ciudad del pedido", "ciudad", "order city", "ciudad de envio", "city"],
    COL_ESTADO: [
        "estado del pedido", "estado", "order state", "entidad federativa",
        "estado de envio", "state",
    ],
    COL_CP: [
        "codigo postal del pedido", "codigo postal", "order postal", "cp",
        "postal code", "zip",
    ],
    COL_MODELO_IMPUESTOS: [
        "modelo de recaudacion de impuestos", "tax collection model",
        "modelo de impuestos",
    ],
    COL_VENTAS: [
        "ventas de productos", "ventas de producto", "product sales", "ventas",
        "importe de ventas",
    ],
    COL_IMPUESTO_VENTAS: [
        "impuesto de ventas de productos", "product sales tax",
        "impuesto sobre ventas de productos", "impuesto de ventas",
    ],
    COL_CREDITOS_ENVIO: ["creditos de envio", "shipping credits", "abono de envio"],
    COL_IMPUESTO_ENVIO: [
        "impuesto de abono de envio", "impuesto de creditos de envio",
        "shipping credits tax", "impuesto de envio",
    ],
    COL_CREDITOS_ENVOLTORIO: [
        "creditos por envoltorio de regalo", "gift wrap credits",
        "creditos de envoltorio de regalo", "creditos de envoltura",
    ],
    COL_IMPUESTO_ENVOLTORIO: [
        "impuesto de creditos de envoltura", "impuesto de creditos de envoltorio",
        "gift wrap credits tax", "giftwrap credits tax",
    ],
    COL_TARIFA_REGLAMENTARIA: ["tarifa reglamentaria", "regulatory fee", "tarifas reglamentarias"],
    COL_IMPUESTO_REGLAMENTARIO: [
        "impuesto sobre tarifa reglamentaria", "tax on regulatory fee",
        "impuesto de tarifa reglamentaria",
    ],
    COL_DESCUENTOS: [
        "descuentos promocionales", "promotional rebates", "descuentos promocionales de amazon",
    ],
    COL_IMPUESTO_DESCUENTOS: [
        "impuesto de reembolsos promocionales", "impuesto de descuentos promocionales",
        "promotional rebates tax",
    ],
    COL_RETENCIONES: [
        "impuesto de retenciones en la plataforma", "retenciones en la plataforma",
        "marketplace withheld tax", "impuesto retenido por el marketplace",
    ],
    COL_TARIFAS_VENTA: ["tarifas de venta", "selling fees", "comisiones", "tarifa de venta"],
    COL_TARIFAS_FBA: [
        "tarifas fba", "fba fees", "tarifas de logistica de amazon", "tarifa fba",
    ],
    COL_TARIFAS_OTRAS: [
        "tarifas de otra transaccion", "other transaction fees", "otras tarifas de transaccion",
    ],
    COL_OTRO: ["otro", "other", "otros"],
    COL_TOTAL: ["total", "importe total", "total mxn", "monto total"],
    COL_ESTADO_TRANSACCION: [
        "estado de la transaccion", "transaction status", "estatus de la transaccion",
    ],
    COL_FECHA_LIBERACION: [
        "fecha de liberacion de la transaccion", "fecha de liberacion",
        "transaction release date", "fecha de disponibilidad",
    ],
}

# Índice inverso alias -> columna canónica.  Los alias más largos se resuelven
# primero para que "estado de la transaccion" no se confunda con "estado".
INDICE_ALIAS: dict[str, str] = {}
for _canonica, _alias in ALIAS_COLUMNAS.items():
    for _a in _alias:
        INDICE_ALIAS.setdefault(_a, _canonica)

# -----------------------------------------------------------------------------
# Agrupaciones de columnas
# -----------------------------------------------------------------------------

#: Todas las columnas que deben convertirse a número.
COLUMNAS_MONETARIAS: list[str] = [
    COL_VENTAS,
    COL_IMPUESTO_VENTAS,
    COL_CREDITOS_ENVIO,
    COL_IMPUESTO_ENVIO,
    COL_CREDITOS_ENVOLTORIO,
    COL_IMPUESTO_ENVOLTORIO,
    COL_TARIFA_REGLAMENTARIA,
    COL_IMPUESTO_REGLAMENTARIO,
    COL_DESCUENTOS,
    COL_IMPUESTO_DESCUENTOS,
    COL_RETENCIONES,
    COL_TARIFAS_VENTA,
    COL_TARIFAS_FBA,
    COL_TARIFAS_OTRAS,
    COL_OTRO,
    COL_TOTAL,
]

#: Componentes que se suman para reconstruir el neto (todo menos ``total``).
COLUMNAS_COMPONENTES_NETO: list[str] = [c for c in COLUMNAS_MONETARIAS if c != COL_TOTAL]

#: Columnas de impuesto cobrado al cliente (entran y salen vía retención).
COLUMNAS_IMPUESTOS: list[str] = [
    COL_IMPUESTO_VENTAS,
    COL_IMPUESTO_ENVIO,
    COL_IMPUESTO_ENVOLTORIO,
    COL_IMPUESTO_REGLAMENTARIO,
]

#: Columnas de tarifas que Amazon cobra al vendedor (normalmente negativas).
COLUMNAS_TARIFAS: list[str] = [
    COL_TARIFAS_VENTA,
    COL_TARIFAS_FBA,
    COL_TARIFAS_OTRAS,
    COL_TARIFA_REGLAMENTARIA,
]

#: Columnas que deben conservarse como texto (SKU, pedidos, códigos postales).
COLUMNAS_TEXTO: list[str] = [
    COL_LIQUIDACION,
    COL_TIPO,
    COL_PEDIDO,
    COL_SKU,
    COL_DESCRIPCION,
    COL_MARKETPLACE,
    COL_CUMPLIMIENTO,
    COL_CIUDAD,
    COL_ESTADO,
    COL_CP,
    COL_MODELO_IMPUESTOS,
    COL_ESTADO_TRANSACCION,
]

#: Columnas de fecha.
COLUMNAS_FECHA: list[str] = [COL_FECHA, COL_FECHA_LIBERACION]

#: Sin estas columnas el archivo no puede analizarse.
COLUMNAS_REQUERIDAS: list[str] = [COL_FECHA, COL_TIPO, COL_TOTAL]

#: Recomendadas: si faltan, la aplicación funciona pero con métricas limitadas.
COLUMNAS_RECOMENDADAS: list[str] = [
    COL_PEDIDO,
    COL_SKU,
    COL_CANTIDAD,
    COL_VENTAS,
    COL_TARIFAS_VENTA,
    COL_TARIFAS_FBA,
]

#: Llave compuesta para detectar registros duplicados.
LLAVE_DUPLICADOS: list[str] = [
    COL_PEDIDO,
    COL_TIPO,
    COL_SKU,
    COL_FECHA,
    COL_TOTAL,
    COL_LIQUIDACION,
]

#: Orden preferido de columnas en las tablas de detalle.
ORDEN_COLUMNAS: list[str] = list(ENCABEZADOS_ORIGINALES.keys())

# =============================================================================
# Tipos de transacción
# =============================================================================

TIPO_PEDIDO = "Pedido"
TIPO_REEMBOLSO = "Reembolso"
TIPO_AJUSTE = "Ajuste"
TIPO_TARIFA_INVENTARIO = "Tarifa de inventario FBA"
TIPO_TARIFA_SERVICIO = "Tarifa de servicio"
TIPO_TRANSFERENCIA = "Transferencia"
TIPO_OTROS = "Otros cargos"

TIPOS_TRANSACCION: list[str] = [
    TIPO_PEDIDO,
    TIPO_REEMBOLSO,
    TIPO_AJUSTE,
    TIPO_TARIFA_INVENTARIO,
    TIPO_TARIFA_SERVICIO,
    TIPO_TRANSFERENCIA,
    TIPO_OTROS,
]

#: Alias normalizados -> tipo canónico.  "Trasferir" (con la errata del reporte
#: original de Amazon) y "Transferir" apuntan al mismo tipo.
ALIAS_TIPOS: dict[str, str] = {
    "pedido": TIPO_PEDIDO,
    "pedidos": TIPO_PEDIDO,
    "order": TIPO_PEDIDO,
    "orden": TIPO_PEDIDO,
    "shipment": TIPO_PEDIDO,
    "envio": TIPO_PEDIDO,
    "reembolso": TIPO_REEMBOLSO,
    "reembolsos": TIPO_REEMBOLSO,
    "refund": TIPO_REEMBOLSO,
    "devolucion": TIPO_REEMBOLSO,
    "return": TIPO_REEMBOLSO,
    "ajuste": TIPO_AJUSTE,
    "ajustes": TIPO_AJUSTE,
    "adjustment": TIPO_AJUSTE,
    "tarifa de inventario fba": TIPO_TARIFA_INVENTARIO,
    "tarifas de inventario fba": TIPO_TARIFA_INVENTARIO,
    "fba inventory fee": TIPO_TARIFA_INVENTARIO,
    "tarifa de almacenamiento": TIPO_TARIFA_INVENTARIO,
    "tarifa de servicio": TIPO_TARIFA_SERVICIO,
    "tarifas de servicio": TIPO_TARIFA_SERVICIO,
    "service fee": TIPO_TARIFA_SERVICIO,
    "suscripcion": TIPO_TARIFA_SERVICIO,
    "trasferir": TIPO_TRANSFERENCIA,
    "transferir": TIPO_TRANSFERENCIA,
    "transferencia": TIPO_TRANSFERENCIA,
    "transfer": TIPO_TRANSFERENCIA,
    "liquidacion": TIPO_TRANSFERENCIA,
    "otros cargos": TIPO_OTROS,
    "otro cargo": TIPO_OTROS,
    "otros": TIPO_OTROS,
    "other": TIPO_OTROS,
}

#: Tipos que se excluyen del cálculo del neto porque representan el retiro del
#: dinero a la cuenta bancaria (contarlos duplicaría la salida de efectivo).
TIPOS_EXCLUIDOS_DEL_NETO: list[str] = [TIPO_TRANSFERENCIA]

#: Tipos cuyo importe es un cargo operativo, no ligado a un pedido.
TIPOS_CARGO_OPERATIVO: list[str] = [
    TIPO_TARIFA_INVENTARIO,
    TIPO_TARIFA_SERVICIO,
    TIPO_OTROS,
    TIPO_AJUSTE,
]

# =============================================================================
# Unificación de nombres de producto
# =============================================================================
# Algunas variantes del mismo producto llegan con descripciones idénticas entre
# sí —los sabores de S-Nutrition comparten exactamente el mismo texto—, así que
# agrupar por «descripción» los fusionaría y perdería el detalle por variante. El
# SKU sí las distingue: se reasigna un nombre canónico por SKU. La clave es el
# SKU en MAYÚSCULAS; el valor es el nombre que se mostrará en gráficas y tablas.
#
# Para agregar o corregir un producto, basta con añadir una línea aquí.
ALIAS_PRODUCTOS: dict[str, str] = {
    # --- S-Nutrition: infantil (fórmula 200gr «para niños de 1 a 10 años») ---
    "S-NUTRITION-FRESA-200": "SNUTRITION-INF-FRESA",
    "S-NUTRITION-VAINILLA-200": "SNUTRITION-INF-VAINILLA",
    "S-NUTRITION-CHOCOLATE-200": "SNUTRITION-INF-CHOCOLATE",
    # --- S-Nutrition: adulto ---
    "SNUTRITION-ADU-FRESA": "SNUTRITION-ADU-FRESA",
    "SNUTRITION-ADU-VAINILLA": "SNUTRITION-ADU-VAINILLA",
    "SNUTRITION-ADU-CHOCOLATE": "SNUTRITION-ADU-CHOCOLATE",
    # --- LecheLak: sencillo vs. paquete de 12 (misma descripción salvo el sufijo
    #     «- 12 pack», que el recorte de la gráfica ocultaba) ---
    "LECHELAK-1DM": "LecheLak Leche Entera de Cabra en Polvo 340gr",
    "AS-H0HB-9T44": "12 Pack LecheLak Leche Entera de Cabra en Polvo 340gr",
}

#: Formato de SKU de S-Nutrition ya canónico (para reconocer variantes futuras
#: —p. ej. SNUTRITION-INF-CHOCOLATE— aunque no estén en ``ALIAS_PRODUCTOS``).
PATRON_SKU_SNUTRITION = r"SNUTRITION-(ADU|INF)-[A-Z]+"

# =============================================================================
# Catálogo de estados de México
# =============================================================================

#: Nombre normalizado -> nombre oficial usado en las gráficas y el mapa.
ESTADOS_MEXICO: dict[str, str] = {
    "aguascalientes": "Aguascalientes",
    "baja california": "Baja California",
    "baja california norte": "Baja California",
    "baja california sur": "Baja California Sur",
    "campeche": "Campeche",
    "chiapas": "Chiapas",
    "chihuahua": "Chihuahua",
    "ciudad de mexico": "Ciudad de México",
    "cdmx": "Ciudad de México",
    "distrito federal": "Ciudad de México",
    "df": "Ciudad de México",
    "mexico city": "Ciudad de México",
    "coahuila": "Coahuila de Zaragoza",
    "coahuila de zaragoza": "Coahuila de Zaragoza",
    "colima": "Colima",
    "durango": "Durango",
    "guanajuato": "Guanajuato",
    "guerrero": "Guerrero",
    "hidalgo": "Hidalgo",
    "jalisco": "Jalisco",
    "mexico": "México",
    "estado de mexico": "México",
    "edo de mexico": "México",
    "edomex": "México",
    "michoacan": "Michoacán de Ocampo",
    "michoacan de ocampo": "Michoacán de Ocampo",
    "morelos": "Morelos",
    "nayarit": "Nayarit",
    "nuevo leon": "Nuevo León",
    "oaxaca": "Oaxaca",
    "puebla": "Puebla",
    "queretaro": "Querétaro",
    "queretaro de arteaga": "Querétaro",
    "quintana roo": "Quintana Roo",
    "qroo": "Quintana Roo",
    "q roo": "Quintana Roo",
    "san luis potosi": "San Luis Potosí",
    "slp": "San Luis Potosí",
    "sinaloa": "Sinaloa",
    "sonora": "Sonora",
    "tabasco": "Tabasco",
    "tamaulipas": "Tamaulipas",
    "tlaxcala": "Tlaxcala",
    "veracruz": "Veracruz de Ignacio de la Llave",
    "veracruz de ignacio de la llave": "Veracruz de Ignacio de la Llave",
    "yucatan": "Yucatán",
    "zacatecas": "Zacatecas",
}

#: GeoJSON público de los estados de México (se descarga bajo demanda y se cachea).
#: Si no hay conexión, la aplicación muestra una gráfica de barras en su lugar.
GEOJSON_MEXICO_URL = (
    "https://raw.githubusercontent.com/angelnmara/geojson/master/mexicoHigh.json"
)

MESES_ES: dict[int, str] = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre",
    12: "Diciembre",
}

DIAS_ES: dict[int, str] = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes",
    5: "Sábado", 6: "Domingo",
}

# =============================================================================
# Paleta de la aplicación
# =============================================================================
# Paleta categórica validada para superficie clara (#fcfcfb).  El orden de los
# colores es el mecanismo de seguridad para daltonismo: se asignan siempre en
# este orden y nunca se reciclan.

PALETA_CATEGORICA: list[str] = [
    "#2a78d6",  # 1 azul
    "#eb6834",  # 2 naranja
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 amarillo
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 verde
    "#4a3aa7",  # 7 violeta
    "#e34948",  # 8 rojo
]

#: Rampa secuencial de un solo tono (azul) para magnitudes: heatmaps y mapas.
RAMPA_SECUENCIAL: list[str] = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
    "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
    "#184f95", "#104281", "#0d366b",
]

#: Colores de estado (reservados: nunca se usan como color de serie).
COLOR_BUENO = "#0ca30c"
COLOR_ADVERTENCIA = "#fab219"
COLOR_SERIO = "#ec835a"
COLOR_CRITICO = "#d03b3b"

#: Tinta y cromo del tablero (modo claro).
COLOR_SUPERFICIE = "#fcfcfb"
COLOR_PLANO = "#f9f9f7"
COLOR_TINTA = "#0b0b0b"
COLOR_TINTA_SECUNDARIA = "#52514e"
COLOR_TINTA_TENUE = "#898781"
COLOR_REJILLA = "#e1e0d9"
COLOR_EJE = "#c3c2b7"
COLOR_EXITO_TEXTO = "#006300"

FUENTE_UI = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Roles semánticos fijos: el color sigue a la entidad, no a su posición en el ranking.
COLOR_VENTAS = PALETA_CATEGORICA[0]      # azul
COLOR_TARIFAS = PALETA_CATEGORICA[1]     # naranja
COLOR_NETO = PALETA_CATEGORICA[2]        # aqua
COLOR_IMPUESTOS = PALETA_CATEGORICA[3]   # amarillo
COLOR_REEMBOLSOS = PALETA_CATEGORICA[7]  # rojo
COLOR_UNIDADES = PALETA_CATEGORICA[6]    # violeta
COLOR_PEDIDOS = PALETA_CATEGORICA[5]     # verde

# =============================================================================
# Diccionario de métricas (usado en tooltips y en la hoja de Excel)
# =============================================================================

DICCIONARIO_METRICAS: dict[str, dict[str, str]] = {
    # --- Ventas y pedidos ---
    "ventas_brutas": {
        "nombre": "Ventas brutas",
        "grupo": "Ventas",
        "formula": "Suma de «ventas de productos» en filas de tipo Pedido",
        "descripcion": "Importe de producto vendido antes de impuestos y antes de cualquier cargo de Amazon. No incluye reembolsos.",
    },
    "impuestos_cobrados": {
        "nombre": "Impuestos cobrados",
        "grupo": "Ventas",
        "formula": "Suma de impuestos de ventas, envío, envoltorio y tarifa reglamentaria en filas de tipo Pedido",
        "descripcion": "Impuesto trasladado al comprador. Amazon lo retiene y lo entera al SAT bajo el modelo de facilitador.",
    },
    "ventas_con_impuestos": {
        "nombre": "Ventas con impuestos",
        "grupo": "Ventas",
        "formula": "Ventas brutas + Impuestos cobrados",
        "descripcion": "Lo que efectivamente pagó el cliente por el producto.",
    },
    "pedidos_unicos": {
        "nombre": "Pedidos únicos",
        "grupo": "Ventas",
        "formula": "Número de valores distintos de «Id. del pedido» en filas de tipo Pedido",
        "descripcion": "Un pedido con varias líneas o varios SKU cuenta una sola vez.",
    },
    "transacciones": {
        "nombre": "Transacciones",
        "grupo": "Ventas",
        "formula": "Número de filas del periodo (excluye transferencias)",
        "descripcion": "Cada línea del reporte de Amazon es una transacción.",
    },
    "unidades": {
        "nombre": "Unidades vendidas",
        "grupo": "Ventas",
        "formula": "Suma de «cantidad» en filas de tipo Pedido",
        "descripcion": "Piezas vendidas. No descuenta las unidades reembolsadas.",
    },
    "ticket_promedio": {
        "nombre": "Ticket promedio",
        "grupo": "Ventas",
        "formula": "Ventas brutas ÷ Pedidos únicos",
        "descripcion": "Venta promedio por pedido, sin impuestos.",
    },
    "precio_promedio_unidad": {
        "nombre": "Precio promedio por unidad",
        "grupo": "Ventas",
        "formula": "Ventas brutas ÷ Unidades vendidas",
        "descripcion": "Precio efectivo por pieza, sin impuestos.",
    },
    "unidades_por_pedido": {
        "nombre": "Unidades por pedido",
        "grupo": "Ventas",
        "formula": "Unidades vendidas ÷ Pedidos únicos",
        "descripcion": "Promedio de piezas que lleva cada pedido.",
    },
    "skus_vendidos": {
        "nombre": "SKU vendidos",
        "grupo": "Ventas",
        "formula": "Número de valores distintos de «sku» en filas de tipo Pedido",
        "descripcion": "Cantidad de claves de producto con al menos una venta.",
    },
    "productos_vendidos": {
        "nombre": "Productos vendidos",
        "grupo": "Ventas",
        "formula": "Número de valores distintos de «descripción» en filas de tipo Pedido",
        "descripcion": "Productos distintos, agrupados por su descripción.",
    },
    "dias_periodo": {
        "nombre": "Días del periodo",
        "grupo": "Ventas",
        "formula": "Días transcurridos entre la primera y la última fecha del periodo",
        "descripcion": "Base de los promedios diarios.",
    },
    "ventas_por_dia": {
        "nombre": "Ventas promedio por día",
        "grupo": "Ventas",
        "formula": "Ventas brutas ÷ Días del periodo",
        "descripcion": "Ritmo diario de venta.",
    },
    "pedidos_por_dia": {
        "nombre": "Pedidos promedio por día",
        "grupo": "Ventas",
        "formula": "Pedidos únicos ÷ Días del periodo",
        "descripcion": "Ritmo diario de pedidos.",
    },
    "unidades_por_dia": {
        "nombre": "Unidades promedio por día",
        "grupo": "Ventas",
        "formula": "Unidades vendidas ÷ Días del periodo",
        "descripcion": "Ritmo diario de piezas vendidas.",
    },
    # --- Tarifas ---
    "tarifas_venta": {
        "nombre": "Tarifas de venta",
        "grupo": "Tarifas",
        "formula": "|Suma de «tarifas de venta»| en todas las filas salvo transferencias",
        "descripcion": "Comisión por referencia que cobra Amazon. Los reembolsos devuelven parte de esta comisión y ya están netados.",
    },
    "tarifas_fba": {
        "nombre": "Tarifas FBA",
        "grupo": "Tarifas",
        "formula": "|Suma de «tarifas fba»| en todas las filas salvo transferencias",
        "descripcion": "Costo de gestión logística por parte de Amazon (recolección, empaque y envío).",
    },
    "retenciones": {
        "nombre": "Retenciones de impuestos",
        "grupo": "Tarifas",
        "formula": "|Suma de «impuesto de retenciones en la plataforma»|",
        "descripcion": "Impuesto que Amazon retiene y entera a la autoridad. No es una tarifa de Amazon; se muestra aparte.",
    },
    "tarifas_inventario": {
        "nombre": "Tarifas de inventario FBA",
        "grupo": "Tarifas",
        "formula": "|Suma de «total»| en filas de tipo Tarifa de inventario FBA",
        "descripcion": "Almacenamiento mensual y almacenamiento prolongado.",
    },
    "tarifas_servicio": {
        "nombre": "Tarifas de servicio",
        "grupo": "Tarifas",
        "formula": "|Suma de «total»| en filas de tipo Tarifa de servicio",
        "descripcion": "Suscripción de vendedor profesional y servicios similares.",
    },
    "tarifas_otras": {
        "nombre": "Tarifas de otras transacciones",
        "grupo": "Tarifas",
        "formula": "|Suma de «tarifas de otra transacción»|",
        "descripcion": "Cargos que no entran en las categorías anteriores.",
    },
    "tarifa_reglamentaria": {
        "nombre": "Tarifa reglamentaria",
        "grupo": "Tarifas",
        "formula": "|Suma de «Tarifa reglamentaria»|",
        "descripcion": "Cargo regulatorio aplicable a ciertas categorías.",
    },
    "descuentos_promocionales": {
        "nombre": "Descuentos promocionales",
        "grupo": "Tarifas",
        "formula": "|Suma de «descuentos promocionales»|",
        "descripcion": "Promociones y cupones aplicados por el vendedor.",
    },
    "otros_cargos": {
        "nombre": "Otros cargos",
        "grupo": "Tarifas",
        "formula": "|Suma de los valores negativos de «otro»| en filas que no son transferencias",
        "descripcion": "Ajustes, almacenamiento y cargos operativos registrados en la columna «otro».",
    },
    "total_cargos": {
        "nombre": "Total de cargos Amazon",
        "grupo": "Tarifas",
        "formula": "|Tarifas de venta + FBA + otras + reglamentaria| + Otros cargos + cargos por tipo no capturados en columnas",
        "descripcion": "Todo lo que Amazon descuenta al vendedor. No incluye impuestos retenidos ni el reembolso al cliente.",
    },
    "tarifa_por_pedido": {
        "nombre": "Tarifa promedio por pedido",
        "grupo": "Tarifas",
        "formula": "Total de cargos Amazon ÷ Pedidos únicos",
        "descripcion": "Cuánto cuesta en promedio despachar un pedido.",
    },
    "tarifa_por_unidad": {
        "nombre": "Tarifa promedio por unidad",
        "grupo": "Tarifas",
        "formula": "Total de cargos Amazon ÷ Unidades vendidas",
        "descripcion": "Cuánto cuesta en promedio despachar una pieza.",
    },
    "pct_comisiones": {
        "nombre": "% de comisiones sobre ventas",
        "grupo": "Tarifas",
        "formula": "Tarifas de venta ÷ Ventas brutas",
        "descripcion": "Peso de la comisión por referencia sobre la venta.",
    },
    "pct_fba": {
        "nombre": "% de tarifas FBA sobre ventas",
        "grupo": "Tarifas",
        "formula": "Tarifas FBA ÷ Ventas brutas",
        "descripcion": "Peso de la logística de Amazon sobre la venta.",
    },
    "pct_cargos": {
        "nombre": "% total de cargos Amazon",
        "grupo": "Tarifas",
        "formula": "Total de cargos Amazon ÷ Ventas brutas",
        "descripcion": "Porcentaje de la venta bruta que se queda Amazon.",
    },
    # --- Reembolsos ---
    "pedidos_reembolsados": {
        "nombre": "Pedidos reembolsados",
        "grupo": "Reembolsos",
        "formula": "Número de «Id. del pedido» distintos en filas de tipo Reembolso",
        "descripcion": "Pedidos con al menos una devolución en el periodo.",
    },
    "transacciones_reembolso": {
        "nombre": "Transacciones de reembolso",
        "grupo": "Reembolsos",
        "formula": "Número de filas de tipo Reembolso",
        "descripcion": "Líneas de devolución registradas.",
    },
    "unidades_reembolsadas": {
        "nombre": "Unidades reembolsadas",
        "grupo": "Reembolsos",
        "formula": "|Suma de «cantidad»| en filas de tipo Reembolso",
        "descripcion": "Piezas devueltas por los clientes.",
    },
    "importe_reembolsado": {
        "nombre": "Importe reembolsado",
        "grupo": "Reembolsos",
        "formula": "|Suma de «total»| en filas de tipo Reembolso",
        "descripcion": "Dinero devuelto al cliente, ya neto de la comisión que Amazon regresa.",
    },
    "pct_pedidos_reembolsados": {
        "nombre": "% de pedidos reembolsados",
        "grupo": "Reembolsos",
        "formula": "Pedidos reembolsados ÷ Pedidos únicos",
        "descripcion": "Los reembolsos pueden corresponder a pedidos de periodos anteriores.",
    },
    "pct_unidades_reembolsadas": {
        "nombre": "% de unidades reembolsadas",
        "grupo": "Reembolsos",
        "formula": "Unidades reembolsadas ÷ Unidades vendidas",
        "descripcion": "Proporción de piezas devueltas.",
    },
    "tasa_reembolso": {
        "nombre": "Tasa de reembolso sobre ventas",
        "grupo": "Reembolsos",
        "formula": "Importe reembolsado ÷ Ventas brutas",
        "descripcion": "Peso económico de las devoluciones.",
    },
    # --- Resultado neto ---
    "neto": {
        "nombre": "Neto después de tarifas",
        "grupo": "Resultado",
        "formula": "Suma de «total» de todas las transacciones del periodo, excluyendo transferencias",
        "descripcion": "Dinero depositable. NO es utilidad: todavía no descuenta el costo del producto.",
    },
    "neto_reconstruido": {
        "nombre": "Neto reconstruido",
        "grupo": "Resultado",
        "formula": "Suma de todos los componentes monetarios (ventas, impuestos, créditos, tarifas, descuentos, otro)",
        "descripcion": "Recalcula el neto sumando las columnas de detalle para poder conciliar contra «total».",
    },
    "diferencia_conciliacion": {
        "nombre": "Diferencia de conciliación",
        "grupo": "Resultado",
        "formula": "Neto − Neto reconstruido",
        "descripcion": "Si es distinta de cero hay columnas faltantes o valores que no se pudieron interpretar.",
    },
    "neto_por_pedido": {
        "nombre": "Neto por pedido",
        "grupo": "Resultado",
        "formula": "Neto después de tarifas ÷ Pedidos únicos",
        "descripcion": "Depósito promedio que deja cada pedido.",
    },
    "neto_por_unidad": {
        "nombre": "Neto por unidad",
        "grupo": "Resultado",
        "formula": "Neto después de tarifas ÷ Unidades vendidas",
        "descripcion": "Depósito promedio por pieza.",
    },
    "neto_por_sku": {
        "nombre": "Neto por SKU",
        "grupo": "Resultado",
        "formula": "Neto después de tarifas ÷ SKU vendidos",
        "descripcion": "Aportación promedio de cada clave de producto.",
    },
    "margen_neto": {
        "nombre": "Margen neto Amazon",
        "grupo": "Resultado",
        "formula": "Neto después de tarifas ÷ Ventas brutas",
        "descripcion": "Porcentaje de la venta bruta que llega al vendedor antes del costo del producto.",
    },
    # --- Rentabilidad ---
    "costo_mercancia": {
        "nombre": "Costo de mercancía vendida",
        "grupo": "Rentabilidad",
        "formula": "Σ (unidades netas del SKU × (costo unitario + costo logístico adicional))",
        "descripcion": "Requiere el catálogo de costos. Las unidades netas descuentan las devoluciones.",
    },
    "utilidad_antes_publicidad": {
        "nombre": "Utilidad antes de publicidad",
        "grupo": "Rentabilidad",
        "formula": "Neto después de tarifas − Costo de mercancía vendida",
        "descripcion": "Utilidad operativa sin considerar el gasto en anuncios.",
    },
    "utilidad_despues_publicidad": {
        "nombre": "Utilidad después de publicidad",
        "grupo": "Rentabilidad",
        "formula": "Utilidad antes de publicidad − Gasto publicitario",
        "descripcion": "Utilidad final del periodo con los datos capturados.",
    },
    "margen_bruto": {
        "nombre": "Margen bruto",
        "grupo": "Rentabilidad",
        "formula": "(Ventas brutas − Costo de mercancía vendida) ÷ Ventas brutas",
        "descripcion": "Margen antes de las tarifas de Amazon.",
    },
    "margen_contribucion": {
        "nombre": "Margen de contribución",
        "grupo": "Rentabilidad",
        "formula": "Utilidad después de publicidad ÷ Ventas brutas",
        "descripcion": "Porcentaje de la venta que queda tras tarifas, costo y publicidad.",
    },
    "roi": {
        "nombre": "ROI",
        "grupo": "Rentabilidad",
        "formula": "Utilidad después de publicidad ÷ Costo de mercancía vendida",
        "descripcion": "Retorno sobre la inversión en mercancía.",
    },
    "acos": {
        "nombre": "ACOS",
        "grupo": "Rentabilidad",
        "formula": "Gasto publicitario ÷ Ventas atribuidas a publicidad",
        "descripcion": "Costo publicitario de la venta. Con los datos del reporte se aproxima con las ventas del SKU anunciado.",
    },
    "tacos": {
        "nombre": "TACOS",
        "grupo": "Rentabilidad",
        "formula": "Gasto publicitario ÷ Ventas brutas totales",
        "descripcion": "Peso de la publicidad sobre toda la venta, anunciada o no.",
    },
}

# =============================================================================
# Planes SaaS
# =============================================================================

PLANES: dict[str, dict[str, object]] = {
    "gratuito": {
        "nombre": "Gratuito",
        "precio_mxn": 0,
        "max_archivos_mes": 2,
        "max_filas_archivo": 5_000,
        "dias_historial": 30,
        "comparacion_periodos": False,
        "rentabilidad": False,
        "exportacion_avanzada": False,
        "alertas": False,
        "multi_usuario": False,
        "api": False,
        "descripcion": "Ideal para probar la herramienta con un reporte mensual.",
    },
    "profesional": {
        "nombre": "Profesional",
        "precio_mxn": 499,
        "max_archivos_mes": 100,
        "max_filas_archivo": 500_000,
        "dias_historial": 730,
        "comparacion_periodos": True,
        "rentabilidad": True,
        "exportacion_avanzada": True,
        "alertas": True,
        "multi_usuario": False,
        "api": False,
        "descripcion": "Para el vendedor que administra su cuenta a diario.",
    },
    "empresarial": {
        "nombre": "Empresarial",
        "precio_mxn": 1499,
        "max_archivos_mes": 0,  # 0 = sin límite
        "max_filas_archivo": 0,
        "dias_historial": 0,
        "comparacion_periodos": True,
        "rentabilidad": True,
        "exportacion_avanzada": True,
        "alertas": True,
        "multi_usuario": True,
        "api": True,
        "descripcion": "Varias cuentas de Amazon, equipo con roles y reportes programados.",
    },
}

ROLES: dict[str, str] = {
    "propietario": "Propietario",
    "administrador": "Administrador",
    "analista": "Analista",
    "lector": "Lector",
}

# Permisos mínimos por rol.
PERMISOS_ROL: dict[str, set[str]] = {
    "propietario": {"ver", "cargar", "exportar", "configurar", "administrar_usuarios", "facturar"},
    "administrador": {"ver", "cargar", "exportar", "configurar", "administrar_usuarios"},
    "analista": {"ver", "cargar", "exportar"},
    "lector": {"ver"},
}
"""Página de inicio: bienvenida, instrucciones y acceso rápido."""

from __future__ import annotations

import streamlit as st

from components.layout import barra_lateral_usuario, encabezado
from components.metric_cards import cifra_destacada
from database.repositories import FileRepository, ImportRepository
from services.auth_service import sesion_actual
from services.file_service import cargar_datos_demo, cargar_historico, hay_datos, obtener_datos
from services.metrics_service import calcular_metricas
from utils.constants import COLOR_TINTA_TENUE, FUENTE_UI, PLANES
from utils.formatting import (
    formato_entero,
    formato_fecha,
    formato_moneda,
    formato_porcentaje,
)
from utils.logger import get_logger, registrar_error

logger = get_logger("pagina_inicio")

barra_lateral_usuario()
sesion = sesion_actual()
if sesion is None:
    st.stop()

encabezado(
    f"Hola, {sesion.nombre.split()[0]}",
    "Este es tu panel de control de Amazon Seller Central.",
    "🏠",
)

# =============================================================================
# Indicadores del periodo cargado
# =============================================================================

if hay_datos():
    df = obtener_datos()
    metricas = calcular_metricas(df)

    inicio, fin = metricas.get("fecha_inicio"), metricas.get("fecha_fin")
    periodo = (
        f"{formato_fecha(inicio)} al {formato_fecha(fin)}"
        if inicio is not None and fin is not None
        else "sin fechas válidas"
    )

    st.markdown("#### Último periodo analizado")
    st.caption(f"{periodo} · {formato_entero(len(df))} transacciones cargadas")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        cifra_destacada("Ventas brutas", formato_moneda(metricas["ventas_brutas"]))
    with col2:
        cifra_destacada("Pedidos únicos", formato_entero(metricas["pedidos_unicos"]))
    with col3:
        cifra_destacada("Neto depositable", formato_moneda(metricas["neto"]))
    with col4:
        cifra_destacada(
            "Margen neto Amazon",
            formato_porcentaje(metricas["margen_neto"]),
            "Antes del costo del producto",
        )

    st.markdown("")
    col_a, col_b, col_c = st.columns(3)
    if col_a.button("Ver el resumen ejecutivo", width="stretch", type="primary"):
        st.switch_page("pages/03_resumen.py")
    if col_b.button("Analizar productos", width="stretch"):
        st.switch_page("pages/05_productos.py")
    if col_c.button("Cargar otro archivo", width="stretch"):
        st.switch_page("pages/02_cargar_archivos.py")

else:
    st.info(
        "Todavía no has cargado ningún reporte. Empieza subiendo tu archivo de "
        "transacciones o explora la aplicación con datos de ejemplo."
    )
    col_a, col_b = st.columns(2)
    if col_a.button("Cargar mi reporte", width="stretch", type="primary"):
        st.switch_page("pages/02_cargar_archivos.py")
    if col_b.button("Probar con datos de ejemplo", width="stretch"):
        filas = cargar_datos_demo()
        if filas:
            st.success(f"Se cargaron {formato_entero(filas)} transacciones de ejemplo.")
            st.rerun()
        else:
            st.error(
                "No fue posible generar los datos de ejemplo. "
                "Ejecuta `python scripts/generar_datos_demo.py` desde la carpeta del proyecto."
            )

st.markdown("---")

# =============================================================================
# Instrucciones e historial
# =============================================================================

col_izq, col_der = st.columns([3, 2])

with col_izq:
    st.markdown("#### Cómo obtener tu reporte de Amazon")
    st.markdown(
        """
1. Entra a **Seller Central** con tu cuenta de vendedor.
2. Ve a **Informes → Pagos → Todos los estados de cuenta**.
3. Elige **Informe de transacciones personalizado** y selecciona el rango de fechas.
4. Descarga el archivo (llega como CSV) y súbelo en **Cargar archivos**.

La aplicación reconoce los encabezados en español aunque cambien mayúsculas,
acentos o espacios, y acepta también archivos de Excel.
        """
    )

    with st.expander("Qué significa cada cifra", expanded=False):
        st.markdown(
            """
- **Ventas brutas**: solo las filas de tipo *Pedido*, antes de impuestos y cargos.
- **Pedidos únicos**: valores distintos de *Id. del pedido*. Un pedido con tres
  SKU cuenta una sola vez.
- **Total de cargos Amazon**: comisiones, tarifas FBA, almacenamiento, suscripción
  y cargos varios.
- **Neto después de tarifas**: lo que Amazon deposita. **No es utilidad**: todavía
  no descuenta el costo de tu producto. Para eso captura tus costos en
  *Costos y rentabilidad*.
- Las **transferencias** (retiros a tu banco) se excluyen de todos los importes:
  contarlas duplicaría la salida de dinero.
            """
        )

with col_der:
    st.markdown("#### Tus últimos archivos")
    try:
        archivos = FileRepository.listar(sesion.organization_id, limite=8)
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "listado de archivos en inicio")
        archivos = None

    if archivos is not None and not archivos.empty:
        vista = archivos[["Archivo", "Filas", "Subido"]].copy()
        vista["Subido"] = vista["Subido"].apply(lambda v: formato_fecha(v, con_hora=True))
        st.dataframe(vista, width="stretch", hide_index=True)

        if st.button("Cargar mi histórico completo", width="stretch"):
            filas = cargar_historico(sesion)
            if filas:
                st.success(f"Se cargaron {formato_entero(filas)} transacciones del histórico.")
                st.rerun()
            else:
                st.warning("No hay transacciones guardadas en el histórico todavía.")
    else:
        st.caption("Aún no has subido archivos.")

    # --- Plan actual ---
    plan = PLANES.get(sesion.plan, PLANES["gratuito"])
    st.markdown("#### Tu plan")
    limite_archivos = plan["max_archivos_mes"]
    try:
        usados = FileRepository.contar_del_mes(sesion.organization_id)
    except Exception:  # noqa: BLE001
        usados = 0

    texto_limite = (
        "archivos ilimitados"
        if not limite_archivos
        else f"{usados} de {limite_archivos} archivos este mes"
    )
    st.markdown(
        f"""
        <div style="font-family:{FUENTE_UI};font-size:13px;color:{COLOR_TINTA_TENUE};line-height:1.7">
            <b>{plan['nombre']}</b> — {plan['descripcion']}<br>
            {texto_limite}
        </div>
        """,
        unsafe_allow_html=True,
    )

    ultimo_inicio, ultimo_fin = ImportRepository.ultimo_periodo(sesion.organization_id)
    if ultimo_inicio and ultimo_fin:
        st.caption(
            f"Última importación: {formato_fecha(ultimo_inicio)} al {formato_fecha(ultimo_fin)}"
        )

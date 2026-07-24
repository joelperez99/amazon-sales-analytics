"""Página de configuración: cuenta, plan, datos, seguridad y diagnóstico."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.layout import barra_lateral_usuario, encabezado
from database.connection import probar_conexion
from database.repositories import (
    AlertRepository,
    AuditRepository,
    CostRepository,
    FileRepository,
    ImportRepository,
    OrganizationRepository,
    UserRepository,
)
from services.auth_service import cambiar_password, sesion_actual
from services.storage_service import aplicar_retencion, get_storage
from utils.config import get_settings
from utils.constants import PERMISOS_ROL, PLANES, ROLES
from utils.formatting import formato_entero, formato_fecha
from utils.logger import get_logger, registrar_error

logger = get_logger("pagina_configuracion")
settings = get_settings()

barra_lateral_usuario()
sesion = sesion_actual()
if sesion is None:
    st.stop()

encabezado("Configuración", "Tu cuenta, tu plan y tus datos.", "⚙️")

tab_cuenta, tab_plan, tab_datos, tab_equipo, tab_sistema = st.tabs(
    ["Mi cuenta", "Plan y facturación", "Mis datos", "Equipo", "Sistema"]
)

# =============================================================================
# Mi cuenta
# =============================================================================

with tab_cuenta:
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("#### Datos de la cuenta")
        st.text_input("Nombre", value=sesion.nombre, disabled=True)
        st.text_input("Correo electrónico", value=sesion.email, disabled=True)
        st.text_input("Rol", value=ROLES.get(sesion.rol, sesion.rol), disabled=True)
        st.text_input("Organización", value=sesion.organizacion, disabled=True)
        st.caption(
            "Permisos de tu rol: "
            + ", ".join(sorted(PERMISOS_ROL.get(sesion.rol, set())))
        )

    with col_b:
        st.markdown("#### Cambiar contraseña")
        with st.form("form_cambiar_password"):
            actual = st.text_input("Contraseña actual", type="password")
            nueva = st.text_input(
                "Contraseña nueva", type="password",
                help=f"Mínimo {settings.password_min_length} caracteres, con letras y números.",
            )
            confirmar = st.text_input("Confirma la contraseña nueva", type="password")
            enviar = st.form_submit_button("Actualizar contraseña", width="stretch")

        if enviar:
            if nueva != confirmar:
                st.error("Las contraseñas nuevas no coinciden.")
            elif sesion.user_id == 0:
                st.warning("En modo abierto (sin autenticación) no hay contraseña que cambiar.")
            else:
                resultado = cambiar_password(sesion.user_id, actual, nueva)
                if resultado.valido:
                    st.success("Contraseña actualizada.")
                for error in resultado.errores:
                    st.error(error)

    st.markdown("---")
    st.markdown("#### Preferencias")
    col_c, col_d = st.columns(2)
    with col_c:
        frecuencia_defecto = st.selectbox(
            "Agrupación temporal preferida", ["Día", "Semana", "Mes"],
            key="pref_frecuencia",
        )
    with col_d:
        st.number_input(
            "Filas por página en las tablas", min_value=10, max_value=200,
            value=25, step=5, key="pref_filas",
        )
    if st.button("Guardar preferencias"):
        try:
            UserRepository.guardar_preferencias(
                sesion.user_id,
                {
                    "frecuencia": frecuencia_defecto,
                    "filas_pagina": st.session_state.get("pref_filas", 25),
                },
            )
            st.success("Preferencias guardadas.")
        except Exception as error:  # noqa: BLE001
            id_error = registrar_error(logger, error, "guardado de preferencias")
            st.error(f"No fue posible guardar. Referencia: {id_error}.")

# =============================================================================
# Plan y facturación
# =============================================================================

with tab_plan:
    st.markdown("#### Comparativa de planes")

    comparativa = pd.DataFrame([
        {
            "Plan": datos["nombre"],
            "Precio mensual": f"${datos['precio_mxn']:,} MXN",
            "Archivos por mes": (
                "Ilimitados" if not datos["max_archivos_mes"] else f"{datos['max_archivos_mes']:,}"
            ),
            "Filas por archivo": (
                "Sin límite" if not datos["max_filas_archivo"] else f"{datos['max_filas_archivo']:,}"
            ),
            "Historial": (
                "Sin límite" if not datos["dias_historial"] else f"{datos['dias_historial']} días"
            ),
            "Comparación de periodos": "Sí" if datos["comparacion_periodos"] else "No",
            "Rentabilidad": "Sí" if datos["rentabilidad"] else "No",
            "Exportación avanzada": "Sí" if datos["exportacion_avanzada"] else "No",
            "Alertas": "Sí" if datos["alertas"] else "No",
            "Multiusuario": "Sí" if datos["multi_usuario"] else "No",
            "API": "Sí" if datos["api"] else "No",
        }
        for datos in PLANES.values()
    ])
    st.dataframe(comparativa, width="stretch", hide_index=True)

    plan_actual = PLANES.get(sesion.plan, PLANES["gratuito"])
    st.info(f"Tu plan actual es **{plan_actual['nombre']}**. {plan_actual['descripcion']}")

    if settings.billing_enabled:
        st.caption(
            "El cobro con Stripe está habilitado. Al cambiar de plan se abrirá el "
            "portal de pago."
        )
    else:
        st.caption(
            "El cobro está en **modo de pruebas**: puedes cambiar de plan sin pagar. "
            "Para activar Stripe, configura `BILLING_ENABLED`, `STRIPE_SECRET_KEY` y "
            "los identificadores de precio en tu archivo `.env`."
        )

    if sesion.puede("facturar") or not settings.billing_enabled:
        col_a, col_b = st.columns([2, 1])
        with col_a:
            nuevo_plan = st.selectbox(
                "Cambiar a",
                list(PLANES.keys()),
                index=list(PLANES.keys()).index(sesion.plan) if sesion.plan in PLANES else 0,
                format_func=lambda p: PLANES[p]["nombre"],
            )
        with col_b:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button("Aplicar plan", width="stretch", type="primary"):
                try:
                    OrganizationRepository.actualizar_plan(sesion.organization_id, nuevo_plan)
                    sesion.plan = nuevo_plan
                    st.success(
                        f"Plan actualizado a {PLANES[nuevo_plan]['nombre']}. "
                        "Recarga la página para ver las funciones habilitadas."
                    )
                except Exception as error:  # noqa: BLE001
                    id_error = registrar_error(logger, error, "cambio de plan")
                    st.error(f"No fue posible cambiar el plan. Referencia: {id_error}.")
    else:
        st.warning("Tu rol no tiene permiso para modificar la facturación.")

# =============================================================================
# Mis datos
# =============================================================================

with tab_datos:
    st.markdown("#### Archivos e importaciones")

    try:
        archivos = FileRepository.listar(sesion.organization_id, limite=100)
        importaciones = ImportRepository.listar(sesion.organization_id, limite=30)
    except Exception as error:  # noqa: BLE001
        id_error = registrar_error(logger, error, "consulta de archivos")
        st.error(f"No fue posible consultar tus archivos. Referencia: {id_error}.")
        archivos = importaciones = pd.DataFrame()

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Archivos guardados", formato_entero(len(archivos)))
    col_b.metric("Importaciones", formato_entero(len(importaciones)))
    try:
        almacenamiento = get_storage()
        espacio = getattr(almacenamiento, "espacio_usado", lambda _: 0)(sesion.organization_id)
        col_c.metric("Espacio usado", f"{espacio / 1024 / 1024:,.1f} MB")
    except Exception:  # noqa: BLE001
        col_c.metric("Espacio usado", "N/D")

    if not archivos.empty:
        vista = archivos.copy()
        vista["Subido"] = vista["Subido"].apply(lambda v: formato_fecha(v, con_hora=True))
        vista["Tamaño"] = (vista["Bytes"] / 1024).round(1).astype(str) + " KB"
        st.dataframe(
            vista[["Id", "Archivo", "Filas", "Columnas", "Tamaño", "Subido"]],
            width="stretch", hide_index=True,
        )

        col_x, col_y = st.columns([2, 1])
        with col_x:
            a_eliminar = st.selectbox(
                "Eliminar un archivo",
                archivos["Id"].tolist(),
                format_func=lambda i: str(
                    archivos.loc[archivos["Id"] == i, "Archivo"].iloc[0]
                ),
                key="archivo_eliminar",
            )
        with col_y:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button("Eliminar archivo", width="stretch"):
                try:
                    ruta = FileRepository.marcar_eliminado(a_eliminar, sesion.organization_id)
                    if ruta:
                        get_storage().eliminar(ruta)
                        st.success("Archivo eliminado de forma segura.")
                        st.rerun()
                    else:
                        st.warning("El archivo ya no está disponible.")
                except Exception as error:  # noqa: BLE001
                    id_error = registrar_error(logger, error, "eliminación de archivo")
                    st.error(f"No fue posible eliminar. Referencia: {id_error}.")

    if not importaciones.empty:
        with st.expander("Historial de importaciones", expanded=False):
            st.dataframe(importaciones, width="stretch", hide_index=True)

    st.markdown("---")
    st.markdown("#### Política de retención")
    st.caption(
        f"Los archivos se conservan "
        + (
            f"{settings.file_retention_days} días."
            if settings.file_retention_days > 0
            else "de forma indefinida."
        )
        + " Ajusta `FILE_RETENTION_DAYS` en el archivo `.env` para cambiarlo."
    )
    if settings.file_retention_days > 0 and st.button("Aplicar retención ahora"):
        eliminados = aplicar_retencion(sesion.organization_id)
        st.success(f"Se eliminaron {eliminados} archivos que superaron la retención.")

    st.markdown("---")
    st.markdown("#### Zona de riesgo")
    st.caption(
        "Estas acciones no se pueden deshacer. Afectan únicamente a los datos de tu "
        "organización: ninguna otra cuenta se ve alterada."
    )

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        confirmar_tx = st.checkbox("Confirmo que quiero borrar mi histórico de transacciones")
        if st.button("Borrar histórico", disabled=not confirmar_tx, width="stretch"):
            try:
                borradas = ImportRepository.eliminar_todo(sesion.organization_id)
                st.success(f"Se eliminaron {formato_entero(borradas)} transacciones.")
            except Exception as error:  # noqa: BLE001
                id_error = registrar_error(logger, error, "borrado del histórico")
                st.error(f"No fue posible borrar. Referencia: {id_error}.")

    with col_r2:
        confirmar_costos = st.checkbox("Confirmo que quiero borrar mi catálogo de costos")
        if st.button("Borrar catálogo de costos", disabled=not confirmar_costos, width="stretch"):
            try:
                catalogo = CostRepository.cargar(sesion.organization_id)
                for sku in catalogo["sku"].astype(str):
                    CostRepository.eliminar(sesion.organization_id, sku)
                st.session_state.pop("catalogo_costos", None)
                st.success("Catálogo de costos eliminado.")
            except Exception as error:  # noqa: BLE001
                id_error = registrar_error(logger, error, "borrado del catálogo de costos")
                st.error(f"No fue posible borrar. Referencia: {id_error}.")

# =============================================================================
# Equipo
# =============================================================================

with tab_equipo:
    plan_actual = PLANES.get(sesion.plan, PLANES["gratuito"])
    if not plan_actual["multi_usuario"]:
        st.warning(
            "El acceso de varios usuarios está disponible en el plan Empresarial. "
            "Puedes cambiar de plan en la pestaña anterior."
        )
    elif not sesion.puede("administrar_usuarios"):
        st.warning("Tu rol no permite administrar los usuarios de la organización.")
    else:
        st.markdown("#### Miembros de la organización")
        try:
            miembros = OrganizationRepository.miembros(sesion.organization_id)
        except Exception as error:  # noqa: BLE001
            registrar_error(logger, error, "consulta de miembros")
            miembros = pd.DataFrame()

        if not miembros.empty:
            vista = miembros.copy()
            vista["Rol"] = vista["Rol"].map(lambda r: ROLES.get(r, r))
            vista["Desde"] = vista["Desde"].apply(formato_fecha)
            st.dataframe(vista, width="stretch", hide_index=True)

        st.markdown("#### Agregar un miembro")
        st.caption(
            "El usuario debe tener ya una cuenta creada. Al agregarlo, obtiene acceso "
            "a los datos de esta organización con el rol que elijas."
        )
        with st.form("form_miembro"):
            correo_miembro = st.text_input("Correo del usuario")
            rol_miembro = st.selectbox(
                "Rol", list(ROLES.keys()), format_func=lambda r: ROLES[r], index=2
            )
            agregar = st.form_submit_button("Agregar al equipo", width="stretch")

        if agregar:
            usuario = UserRepository.por_email(correo_miembro)
            if usuario is None:
                st.error("No existe una cuenta con ese correo. Pide al usuario que se registre primero.")
            else:
                try:
                    OrganizationRepository.agregar_miembro(
                        sesion.organization_id, usuario["id"], rol_miembro
                    )
                    st.success(f"{usuario['nombre']} se agregó como {ROLES[rol_miembro]}.")
                    st.rerun()
                except Exception as error:  # noqa: BLE001
                    id_error = registrar_error(logger, error, "alta de miembro")
                    st.error(f"No fue posible agregarlo. Referencia: {id_error}.")

        st.markdown("#### Personalización de marca")
        with st.form("form_branding"):
            nombre_org = st.text_input("Nombre de la organización", value=sesion.organizacion)
            logo = st.text_input("URL del logotipo", placeholder="https://…")
            color = st.color_picker("Color principal", value="#2a78d6")
            guardar_marca = st.form_submit_button("Guardar", width="stretch")
        if guardar_marca:
            try:
                OrganizationRepository.actualizar_branding(
                    sesion.organization_id, nombre_org, logo, color
                )
                st.success("Personalización guardada.")
            except Exception as error:  # noqa: BLE001
                id_error = registrar_error(logger, error, "guardado de branding")
                st.error(f"No fue posible guardar. Referencia: {id_error}.")

# =============================================================================
# Sistema
# =============================================================================

with tab_sistema:
    st.markdown("#### Estado del sistema")

    conectada, mensaje = probar_conexion()
    if conectada:
        st.success(f"Base de datos: {mensaje}")
    else:
        st.error(f"Base de datos: {mensaje}")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Entorno", settings.app_env)
    col_b.metric("Almacenamiento", settings.storage_backend)
    col_c.metric("Autenticación", "Activa" if settings.auth_enabled else "Desactivada")

    st.markdown("#### Umbrales de las alertas")
    st.caption("Se configuran en el archivo `.env` y se aplican al generar los hallazgos.")
    umbrales = settings.alertas
    st.dataframe(
        pd.DataFrame([
            {"Umbral": "Caída de ventas", "Valor": f"{umbrales.caida_ventas_pct:.0f}%"},
            {"Umbral": "Tasa de reembolso", "Valor": f"{umbrales.tasa_reembolso_pct:.0f}%"},
            {"Umbral": "Porcentaje de cargos", "Valor": f"{umbrales.pct_cargos_pct:.0f}%"},
            {"Umbral": "Concentración por SKU", "Valor": f"{umbrales.concentracion_sku_pct:.0f}%"},
            {"Umbral": "Días sin venta de un SKU", "Valor": f"{umbrales.dias_sin_venta} días"},
            {"Umbral": "Tolerancia de conciliación", "Valor": f"${umbrales.tolerancia_conciliacion:,.2f} MXN"},
        ]),
        width="stretch", hide_index=True,
    )

    st.markdown("#### Límites de carga")
    st.caption(
        f"Tamaño máximo por archivo: {settings.max_file_size_mb} MB · "
        f"Extensiones permitidas: {', '.join(settings.allowed_extensions)} · "
        f"Lectura por bloques de {settings.csv_chunk_size:,} filas."
    )

    with st.expander("Historial de hallazgos guardados", expanded=False):
        try:
            historial_alertas = AlertRepository.listar(sesion.organization_id, limite=100)
        except Exception:  # noqa: BLE001
            historial_alertas = pd.DataFrame()
        if not historial_alertas.empty:
            st.dataframe(historial_alertas, width="stretch", hide_index=True)
        else:
            st.caption("Todavía no se han guardado hallazgos.")

    if sesion.puede("configurar"):
        with st.expander("Bitácora de actividad", expanded=False):
            try:
                bitacora = AuditRepository.listar(sesion.organization_id, limite=100)
            except Exception:  # noqa: BLE001
                bitacora = pd.DataFrame()
            if not bitacora.empty:
                st.dataframe(bitacora, width="stretch", hide_index=True)
                st.caption(
                    "La bitácora nunca guarda contraseñas ni contenido de tus archivos: "
                    "solo qué acción se realizó y cuándo."
                )
            else:
                st.caption("Sin actividad registrada.")

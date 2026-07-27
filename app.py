"""Amazon Sales Analytics — punto de entrada.

Ejecuta la aplicación con::

    streamlit run app.py

Este archivo se encarga de:

1. Configurar la página y el tema.
2. Inicializar la base de datos y el usuario de demostración.
3. Mostrar la pantalla de acceso cuando la autenticación está activa.
4. Construir la navegación lateral con las doce páginas del tablero.
5. Capturar cualquier error no controlado y mostrar una página amigable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# La raíz del proyecto debe estar en el path para que ``pages/`` pueda importar
# los módulos de ``services``, ``components`` y ``utils``.
RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from services import session_cookie  # noqa: E402
from services.auth_service import (  # noqa: E402
    asegurar_usuario_demo,
    iniciar_sesion,
    iniciar_sesion_demo,
    registrar_usuario,
    restablecer_password,
    sesion_actual,
    solicitar_recuperacion,
)
from utils.config import get_settings  # noqa: E402
from utils.constants import (  # noqa: E402
    COLOR_TINTA,
    COLOR_TINTA_SECUNDARIA,
    COLOR_TINTA_TENUE,
    FUENTE_UI,
)
from utils.logger import configurar_logging, get_logger, registrar_error  # noqa: E402

logger = get_logger("app")
settings = get_settings()

st.set_page_config(
    page_title=settings.app_name,
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get help": None,
        "Report a Bug": None,
        "About": (
            f"**{settings.app_name}**\n\n"
            "Analiza los reportes de transacciones de Amazon Seller Central: "
            "ventas, comisiones, reembolsos, rentabilidad y distribución geográfica."
        ),
    },
)


# =============================================================================
# Arranque
# =============================================================================


@st.cache_resource(show_spinner="Preparando la aplicación…")
def inicializar() -> bool:
    """Inicializa la base de datos una sola vez por proceso."""
    configurar_logging()
    try:
        from database.connection import inicializar_base_de_datos

        inicializar_base_de_datos()
        asegurar_usuario_demo()
        logger.info("Aplicación iniciada correctamente (entorno: %s).", settings.app_env)
        return True
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "inicialización de la aplicación")
        return False


def estilos_globales() -> None:
    """Ajustes finos de la interfaz de Streamlit."""
    st.markdown(
        f"""
        <style>
        .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }}
        [data-testid="stSidebarNav"] {{ padding-top: .4rem; }}
        h1, h2, h3 {{ font-family: {FUENTE_UI}; color: {COLOR_TINTA}; }}
        [data-testid="stMetricValue"] {{ font-family: {FUENTE_UI}; }}
        /* Las tablas anchas se desplazan dentro de su contenedor, nunca la página. */
        [data-testid="stDataFrame"] {{ overflow-x: auto; }}
        div[data-testid="stExpander"] details {{ border-radius: 10px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# Pantalla de acceso
# =============================================================================


def pantalla_acceso() -> None:
    """Registro, inicio de sesión y recuperación de contraseña."""
    izquierda, centro, derecha = st.columns([1, 2, 1])

    with centro:
        st.markdown(
            f"""
            <div style="text-align:center;margin:1.5rem 0 1.2rem 0;font-family:{FUENTE_UI}">
                <div style="font-size:44px;line-height:1">📦</div>
                <div style="font-size:28px;font-weight:600;color:{COLOR_TINTA};margin-top:6px">
                    {settings.app_name}
                </div>
                <div style="font-size:14px;color:{COLOR_TINTA_SECUNDARIA};margin-top:6px">
                    Convierte tus reportes de Amazon Seller Central en un tablero
                    de ventas, comisiones y rentabilidad.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_entrar, tab_registro, tab_recuperar = st.tabs(
            ["Iniciar sesión", "Crear cuenta", "Recuperar contraseña"]
        )

        # --- Iniciar sesión --------------------------------------------------
        with tab_entrar:
            with st.form("form_login", clear_on_submit=False):
                email = st.text_input("Correo electrónico", key="login_email")
                password = st.text_input("Contraseña", type="password", key="login_password")
                entrar = st.form_submit_button("Entrar", width="stretch", type="primary")

            if entrar:
                resultado = iniciar_sesion(email, password)
                if resultado.valido:
                    st.rerun()
                for error in resultado.errores:
                    st.error(error)

            if settings.demo_mode:
                st.markdown("---")
                st.caption("¿Solo quieres ver cómo funciona?")
                if st.button("Entrar con la cuenta de demostración", width="stretch"):
                    resultado = iniciar_sesion_demo()
                    if resultado.valido:
                        st.rerun()
                    for error in resultado.errores:
                        st.error(error)
                st.caption(
                    f"Usuario: `{settings.demo_email}` · Contraseña: `{settings.demo_password}`"
                )

        # --- Crear cuenta ----------------------------------------------------
        with tab_registro:
            with st.form("form_registro"):
                nombre_nuevo = st.text_input("Tu nombre", key="reg_nombre")
                email_nuevo = st.text_input("Correo electrónico", key="reg_email")
                organizacion = st.text_input(
                    "Nombre de tu negocio (opcional)", key="reg_organizacion"
                )
                password_nueva = st.text_input(
                    "Contraseña", type="password", key="reg_password",
                    help=(
                        f"Mínimo {settings.password_min_length} caracteres, "
                        "combinando letras y números."
                    ),
                )
                password_confirma = st.text_input(
                    "Confirma la contraseña", type="password", key="reg_password2"
                )
                crear = st.form_submit_button(
                    "Crear cuenta gratuita", width="stretch", type="primary"
                )

            if crear:
                if password_nueva != password_confirma:
                    st.error("Las contraseñas no coinciden.")
                else:
                    resultado = registrar_usuario(
                        email=email_nuevo,
                        nombre=nombre_nuevo,
                        password=password_nueva,
                        organizacion=organizacion,
                    )
                    if resultado.valido:
                        st.success(
                            "Cuenta creada. Ya puedes iniciar sesión desde la primera pestaña."
                        )
                    for error in resultado.errores:
                        st.error(error)

        # --- Recuperar contraseña --------------------------------------------
        with tab_recuperar:
            st.caption(
                "Genera un código de recuperación. En un despliegue con servidor de "
                "correo el código se envía al buzón del usuario; en modo de pruebas "
                "se muestra aquí."
            )
            with st.form("form_recuperar"):
                email_recuperar = st.text_input("Correo electrónico", key="rec_email")
                solicitar = st.form_submit_button("Generar código", width="stretch")

            if solicitar:
                existe, token = solicitar_recuperacion(email_recuperar)
                # La respuesta es idéntica exista o no la cuenta: no se filtra información.
                st.info(
                    "Si el correo está registrado, se generó un código de recuperación "
                    "válido por 2 horas."
                )
                if existe and not settings.es_produccion:
                    st.code(token, language=None)

            st.markdown("---")
            with st.form("form_restablecer"):
                token_captura = st.text_input("Código de recuperación", key="rec_token")
                password_reset = st.text_input(
                    "Contraseña nueva", type="password", key="rec_password"
                )
                restablecer = st.form_submit_button(
                    "Cambiar contraseña", width="stretch"
                )

            if restablecer:
                resultado = restablecer_password(token_captura, password_reset)
                if resultado.valido:
                    st.success("Contraseña actualizada. Ya puedes iniciar sesión.")
                for error in resultado.errores:
                    st.error(error)

        st.markdown(
            f"""
            <div style="text-align:center;margin-top:2rem;font-family:{FUENTE_UI};
                        font-size:12px;color:{COLOR_TINTA_TENUE}">
                Tus archivos y tus análisis son privados: cada cuenta solo ve su propia información.
            </div>
            """,
            unsafe_allow_html=True,
        )


# =============================================================================
# Navegación
# =============================================================================


def construir_navegacion() -> None:
    """Arma la navegación lateral con las doce páginas."""
    paginas = [
        st.Page("pages/01_inicio.py", title="Inicio", icon="🏠", default=True),
        st.Page("pages/02_cargar_archivos.py", title="Cargar archivos", icon="📤"),
        st.Page("pages/03_resumen.py", title="Resumen ejecutivo", icon="📊"),
        st.Page("pages/04_ventas.py", title="Ventas", icon="📈"),
        st.Page("pages/05_productos.py", title="Productos", icon="📦"),
        st.Page("pages/06_tarifas.py", title="Tarifas", icon="💳"),
        st.Page("pages/07_reembolsos.py", title="Reembolsos", icon="↩️"),
        st.Page("pages/08_geografia.py", title="Geografía", icon="🗺️"),
        st.Page("pages/09_liquidaciones.py", title="Liquidaciones", icon="🧾"),
        st.Page("pages/10_rentabilidad.py", title="Costos y rentabilidad", icon="💰"),
        st.Page("pages/11_exportar.py", title="Exportar", icon="⬇️"),
        st.Page("pages/12_configuracion.py", title="Configuración", icon="⚙️"),
    ]

    navegacion = st.navigation(
        {
            "Panel": paginas[0:1],
            "Datos": paginas[1:2],
            "Análisis": paginas[2:10],
            "Herramientas": paginas[10:],
        }
    )
    navegacion.run()


# =============================================================================
# Ejecución
# =============================================================================


def main() -> None:
    """Flujo principal de la aplicación."""
    estilos_globales()

    # Las cookies se leen una sola vez por ejecución; esto invalida la caché del
    # ciclo anterior para que la sesión persistente se resuelva con datos frescos.
    session_cookie.nuevo_ciclo()

    if not inicializar():
        st.error(
            "No fue posible preparar la base de datos. Revisa el valor de `DATABASE_URL` "
            "en tu archivo `.env` y consulta `logs/app.log` para más detalle."
        )
        st.stop()

    sesion = sesion_actual()
    if settings.auth_enabled and sesion is None:
        pantalla_acceso()
        return

    construir_navegacion()


# Streamlit ejecuta este archivo en cada recarga; la llamada va sin guardas para
# que funcione igual con `streamlit run app.py` y con un runner externo.
#: Excepciones con las que Streamlit controla su propio flujo (``st.rerun``,
#: ``st.stop``, cambio de página). Nunca deben tratarse como errores.
_CONTROL_STREAMLIT = {"RerunException", "StopException", "RerunData"}

try:
    main()
except Exception as error:  # noqa: BLE001 - última red de seguridad de la aplicación
    if type(error).__name__ in _CONTROL_STREAMLIT:
        raise
    id_error = registrar_error(logger, error, "error no controlado en la aplicación")
    st.error(
        "Ocurrió un problema inesperado y la página no pudo mostrarse por completo.\n\n"
        f"Referencia del error: **{id_error}**\n\n"
        "Vuelve a intentarlo. Si el problema continúa, revisa `logs/app.log`."
    )
    if not settings.es_produccion:
        st.exception(error)

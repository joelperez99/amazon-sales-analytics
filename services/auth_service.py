"""Autenticación y control de acceso.

Contraseñas
-----------
Se cifran con **bcrypt** si la biblioteca está instalada; si no, se usa
``PBKDF2-HMAC-SHA256`` de la biblioteca estándar con 260 000 iteraciones.  En
ningún caso se guarda ni se registra la contraseña en claro.

Sesión
------
El estado de sesión vive en ``st.session_state`` y caduca según
``SESSION_TIMEOUT_MINUTES``.  La verificación de caducidad ocurre en cada
recarga de página.

Planes
------
``verificar_limite_archivos`` y ``tiene_funcion`` aplican los límites del plan
contratado antes de permitir una acción.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import streamlit as st

from database.repositories import (
    FileRepository,
    OrganizationRepository,
    UserRepository,
)
from utils.config import get_settings
from utils.constants import PERMISOS_ROL, PLANES
from utils.logger import get_logger, registrar_auditoria, registrar_error
from utils.validations import RegistroUsuario, ResultadoValidacion

logger = get_logger("auth_service")

_PBKDF2_ITERACIONES = 260_000
_PREFIJO_PBKDF2 = "pbkdf2_sha256"

try:  # pragma: no cover - depende del entorno
    import bcrypt

    _BCRYPT_DISPONIBLE = True
except ImportError:  # pragma: no cover
    bcrypt = None  # type: ignore[assignment]
    _BCRYPT_DISPONIBLE = False
    logger.warning(
        "bcrypt no está instalado; se usará PBKDF2-HMAC-SHA256 de la biblioteca estándar."
    )


# =============================================================================
# Cifrado de contraseñas
# =============================================================================


def cifrar_password(password: str) -> str:
    """Devuelve el hash de la contraseña.  Nunca devuelve el texto en claro."""
    if _BCRYPT_DISPONIBLE:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    sal = os.urandom(16)
    derivada = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), sal, _PBKDF2_ITERACIONES
    )
    return "$".join([
        _PREFIJO_PBKDF2,
        str(_PBKDF2_ITERACIONES),
        base64.b64encode(sal).decode("ascii"),
        base64.b64encode(derivada).decode("ascii"),
    ])


def verificar_password(password: str, hash_guardado: str) -> bool:
    """Compara una contraseña contra su hash, en tiempo constante."""
    if not password or not hash_guardado:
        return False

    if hash_guardado.startswith(_PREFIJO_PBKDF2):
        try:
            _, iteraciones, sal_b64, esperado_b64 = hash_guardado.split("$")
            sal = base64.b64decode(sal_b64)
            esperado = base64.b64decode(esperado_b64)
            calculado = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), sal, int(iteraciones)
            )
            return hmac.compare_digest(calculado, esperado)
        except (ValueError, TypeError):
            return False

    if _BCRYPT_DISPONIBLE:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hash_guardado.encode("utf-8"))
        except (ValueError, TypeError):
            return False

    return False


# =============================================================================
# Sesión
# =============================================================================


@dataclass
class Sesion:
    """Usuario autenticado en la sesión actual."""

    user_id: int
    email: str
    nombre: str
    rol: str
    organization_id: int
    plan: str = "gratuito"
    organizacion: str = ""
    es_demo: bool = False

    def puede(self, permiso: str) -> bool:
        """``True`` si el rol del usuario incluye el permiso indicado."""
        return permiso in PERMISOS_ROL.get(self.rol, set())

    @property
    def limites(self) -> dict[str, Any]:
        """Límites del plan contratado."""
        return PLANES.get(self.plan, PLANES["gratuito"])


_CLAVE_SESION = "_sesion_usuario"
_CLAVE_EXPIRA = "_sesion_expira"


def _guardar_sesion(sesion: Sesion) -> None:
    settings = get_settings()
    st.session_state[_CLAVE_SESION] = sesion
    st.session_state[_CLAVE_EXPIRA] = datetime.now() + timedelta(
        minutes=settings.session_timeout_minutes
    )


def sesion_actual() -> Sesion | None:
    """Devuelve la sesión vigente, o ``None`` si no hay o ya caducó."""
    settings = get_settings()

    if not settings.auth_enabled:
        # Modo abierto: se usa una sesión local de desarrollo.
        if _CLAVE_SESION not in st.session_state:
            st.session_state[_CLAVE_SESION] = _sesion_desarrollo()
        return st.session_state[_CLAVE_SESION]

    sesion = st.session_state.get(_CLAVE_SESION)
    if sesion is None:
        return None

    expira = st.session_state.get(_CLAVE_EXPIRA)
    if expira is not None and datetime.now() > expira:
        cerrar_sesion(motivo="caducidad")
        return None

    # Cada interacción renueva la ventana de inactividad.
    st.session_state[_CLAVE_EXPIRA] = datetime.now() + timedelta(
        minutes=settings.session_timeout_minutes
    )
    return sesion


def _sesion_desarrollo() -> Sesion:
    """Sesión sintética para ``AUTH_ENABLED=false`` (solo desarrollo)."""
    organization_id = _asegurar_organizacion_desarrollo()
    return Sesion(
        user_id=0,
        email="local@desarrollo",
        nombre="Usuario local",
        rol="propietario",
        organization_id=organization_id,
        plan="empresarial",
        organizacion="Desarrollo local",
    )


def _asegurar_organizacion_desarrollo() -> int:
    """Crea (una sola vez) la organización usada en modo abierto."""
    try:
        existente = UserRepository.por_email("local@desarrollo")
        if existente and existente["organization_id"]:
            return int(existente["organization_id"])
        organization_id = OrganizationRepository.crear("Desarrollo local", plan="empresarial")
        UserRepository.crear(
            email="local@desarrollo",
            nombre="Usuario local",
            password_hash=cifrar_password(secrets.token_urlsafe(24)),
            organization_id=organization_id,
            rol="propietario",
        )
        return organization_id
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "creación de la organización de desarrollo")
        return 1


def cerrar_sesion(motivo: str = "manual") -> None:
    """Cierra la sesión y limpia los datos en memoria."""
    sesion = st.session_state.get(_CLAVE_SESION)
    if sesion is not None:
        registrar_auditoria("cierre_sesion", getattr(sesion, "user_id", None), {"motivo": motivo})

    for clave in (
        _CLAVE_SESION, _CLAVE_EXPIRA, "df_datos", "df_filtrado", "catalogo_costos",
        "reporte_limpieza", "archivos_procesados", "filtros",
    ):
        st.session_state.pop(clave, None)


# =============================================================================
# Registro e inicio de sesión
# =============================================================================


def registrar_usuario(
    email: str, nombre: str, password: str, organizacion: str = "", plan: str = "gratuito"
) -> ResultadoValidacion:
    """Crea un usuario nuevo con su organización."""
    resultado = ResultadoValidacion()

    try:
        datos = RegistroUsuario(
            email=email, nombre=nombre, password=password, organizacion=organizacion
        )
    except Exception as error:  # noqa: BLE001 - errores de validación de Pydantic
        mensaje = str(error)
        if "value_error" in mensaje or "Value error" in mensaje:
            # Extrae solo el texto legible del error de Pydantic.
            for linea in mensaje.splitlines():
                if "Value error," in linea:
                    resultado.agregar_error(linea.split("Value error,", 1)[1].strip())
                    break
            else:
                resultado.agregar_error("Revisa los datos capturados.")
        elif "email" in mensaje.lower():
            resultado.agregar_error("El correo electrónico no tiene un formato válido.")
        else:
            resultado.agregar_error("Revisa los datos capturados.")
        return resultado

    if UserRepository.por_email(datos.email) is not None:
        resultado.agregar_error("Ya existe una cuenta registrada con ese correo.")
        return resultado

    try:
        nombre_organizacion = datos.organizacion.strip() or f"Cuenta de {datos.nombre}"
        organization_id = OrganizationRepository.crear(nombre_organizacion, plan=plan)
        user_id = UserRepository.crear(
            email=datos.email,
            nombre=datos.nombre,
            password_hash=cifrar_password(datos.password),
            organization_id=organization_id,
            rol="propietario",
        )
        registrar_auditoria("registro_usuario", user_id, {"plan": plan})
        resultado.detalle["user_id"] = user_id
        resultado.detalle["organization_id"] = organization_id
    except Exception as error:  # noqa: BLE001
        id_error = registrar_error(logger, error, "registro de usuario")
        resultado.agregar_error(
            f"No fue posible crear la cuenta. Referencia del error: {id_error}."
        )

    return resultado


def iniciar_sesion(email: str, password: str) -> ResultadoValidacion:
    """Valida las credenciales y abre la sesión."""
    resultado = ResultadoValidacion()
    # Mensaje genérico a propósito: no revela si el correo existe.
    mensaje_generico = "Correo o contraseña incorrectos."

    try:
        usuario = UserRepository.por_email(email)
    except Exception as error:  # noqa: BLE001
        id_error = registrar_error(logger, error, "consulta de usuario en inicio de sesión")
        resultado.agregar_error(
            f"No fue posible validar las credenciales. Referencia: {id_error}."
        )
        return resultado

    if usuario is None or not verificar_password(password, usuario["password_hash"]):
        resultado.agregar_error(mensaje_generico)
        logger.info("Intento de inicio de sesión fallido.")
        return resultado

    if not usuario["activo"]:
        resultado.agregar_error("La cuenta está desactivada. Contacta al administrador.")
        return resultado

    organizacion = OrganizationRepository.obtener(usuario["organization_id"]) or {}

    _guardar_sesion(Sesion(
        user_id=usuario["id"],
        email=usuario["email"],
        nombre=usuario["nombre"],
        rol=usuario["rol"],
        organization_id=usuario["organization_id"],
        plan=organizacion.get("plan", "gratuito"),
        organizacion=organizacion.get("nombre", ""),
        es_demo=usuario["es_demo"],
    ))

    UserRepository.registrar_acceso(usuario["id"])
    registrar_auditoria("inicio_sesion", usuario["id"])
    return resultado


def solicitar_recuperacion(email: str) -> tuple[bool, str]:
    """Genera un token de recuperación de contraseña.

    En un despliegue real el token se envía por correo.  Aquí se devuelve para
    mostrarlo en pantalla, que es lo adecuado en modo de pruebas.
    """
    token = secrets.token_urlsafe(32)
    existe = UserRepository.guardar_token_recuperacion(email, token)
    # Siempre se responde igual, exista o no el correo: no se filtra información.
    if existe:
        registrar_auditoria("solicitud_recuperacion", None, {"email_registrado": True})
        return True, token
    logger.info("Solicitud de recuperación para un correo no registrado.")
    return False, ""


def restablecer_password(token: str, password_nueva: str) -> ResultadoValidacion:
    """Cambia la contraseña usando un token válido."""
    resultado = ResultadoValidacion()
    settings = get_settings()

    if len(password_nueva) < settings.password_min_length:
        resultado.agregar_error(
            f"La contraseña debe tener al menos {settings.password_min_length} caracteres."
        )
        return resultado

    usuario = UserRepository.por_token(token)
    if usuario is None:
        resultado.agregar_error("El enlace de recuperación no es válido o ya venció.")
        return resultado

    UserRepository.actualizar_password(usuario["id"], cifrar_password(password_nueva))
    registrar_auditoria("restablecer_password", usuario["id"])
    return resultado


def cambiar_password(user_id: int, password_actual: str, password_nueva: str) -> ResultadoValidacion:
    """Cambia la contraseña de un usuario autenticado."""
    resultado = ResultadoValidacion()
    settings = get_settings()

    usuario = UserRepository.por_id(user_id)
    if usuario is None or not verificar_password(password_actual, usuario["password_hash"]):
        resultado.agregar_error("La contraseña actual no es correcta.")
        return resultado

    if len(password_nueva) < settings.password_min_length:
        resultado.agregar_error(
            f"La contraseña nueva debe tener al menos {settings.password_min_length} caracteres."
        )
        return resultado

    UserRepository.actualizar_password(user_id, cifrar_password(password_nueva))
    registrar_auditoria("cambio_password", user_id)
    return resultado


# =============================================================================
# Usuario de demostración
# =============================================================================


def asegurar_usuario_demo() -> None:
    """Crea el usuario de demostración si ``DEMO_MODE`` está activo."""
    settings = get_settings()
    if not settings.demo_mode:
        return

    try:
        if UserRepository.por_email(settings.demo_email) is not None:
            return
        organization_id = OrganizationRepository.crear("Cuenta de demostración", plan="profesional")
        UserRepository.crear(
            email=settings.demo_email,
            nombre="Usuario de demostración",
            password_hash=cifrar_password(settings.demo_password),
            organization_id=organization_id,
            rol="propietario",
            es_demo=True,
        )
        logger.info("Usuario de demostración creado: %s", settings.demo_email)
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "creación del usuario de demostración")


def iniciar_sesion_demo() -> ResultadoValidacion:
    """Inicia sesión con el usuario de demostración."""
    settings = get_settings()
    asegurar_usuario_demo()
    return iniciar_sesion(settings.demo_email, settings.demo_password)


# =============================================================================
# Planes y permisos
# =============================================================================


def tiene_funcion(sesion: Sesion | None, funcion: str) -> bool:
    """``True`` si el plan del usuario incluye la función indicada.

    Funciones válidas: ``comparacion_periodos``, ``rentabilidad``,
    ``exportacion_avanzada``, ``alertas``, ``multi_usuario``, ``api``.
    """
    if sesion is None:
        return False
    return bool(PLANES.get(sesion.plan, PLANES["gratuito"]).get(funcion, False))


def verificar_limite_archivos(sesion: Sesion) -> tuple[bool, str]:
    """Comprueba el límite mensual de archivos del plan."""
    limites = sesion.limites
    maximo = int(limites.get("max_archivos_mes", 0) or 0)
    if maximo <= 0:
        return True, ""

    try:
        usados = FileRepository.contar_del_mes(sesion.organization_id)
    except Exception as error:  # noqa: BLE001
        registrar_error(logger, error, "conteo de archivos del mes")
        return True, ""

    if usados >= maximo:
        return False, (
            f"Tu plan {limites['nombre']} permite {maximo} archivos por mes y ya usaste {usados}. "
            "Cambia de plan en la página de configuración para subir más."
        )
    return True, ""


def verificar_limite_filas(sesion: Sesion, filas: int) -> tuple[bool, str]:
    """Comprueba el límite de filas por archivo del plan."""
    maximo = int(sesion.limites.get("max_filas_archivo", 0) or 0)
    if maximo <= 0 or filas <= maximo:
        return True, ""
    return False, (
        f"El archivo tiene {filas:,} filas y tu plan {sesion.limites['nombre']} permite "
        f"hasta {maximo:,} por archivo."
    )


def dias_historial(sesion: Sesion) -> int:
    """Días de historial que conserva el plan (``0`` = sin límite)."""
    return int(sesion.limites.get("dias_historial", 0) or 0)

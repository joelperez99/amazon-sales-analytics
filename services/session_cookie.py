"""Cookie de sesión persistente.

Guarda un token opaco en una cookie del navegador para que la sesión sobreviva a
un reinicio del servidor (por ejemplo, al ajustar código durante el desarrollo) o
a una recarga de la página.  El token **no** identifica al usuario por sí solo:
apunta a una fila de ``user_sessions`` que guarda únicamente su hash.

Depende de ``extra-streamlit-components`` para leer y escribir cookies, algo que
Streamlit no permite de forma nativa.  Si el paquete no está instalado, todas las
funciones se vuelven inertes y la aplicación funciona igual, solo que la sesión
vuelve a vivir únicamente en memoria (se pierde al reiniciar).

Detalle de implementación
-------------------------
El componente de cookies dibuja un ``iframe`` por cada *key* distinta y solo puede
invocarse una vez por *key* en cada ejecución del script.  Por eso:

* el gestor se construye una sola vez y se guarda en ``st.session_state``;
* :func:`nuevo_ciclo` se llama al inicio de cada ejecución para invalidar la
  caché de lectura, de modo que las cookies se lean **una vez por ejecución** y
  todas las llamadas posteriores de esa misma ejecución reutilicen el resultado.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from utils.logger import get_logger

logger = get_logger("session_cookie")

#: Nombre de la cookie en el navegador.
NOMBRE_COOKIE = "amz_sesion"

_CLAVE_GESTOR = "_gestor_cookies"
_CLAVE_CACHE = "_cookies_del_ciclo"


def disponible() -> bool:
    """``True`` si la biblioteca de cookies está instalada."""
    try:
        import extra_streamlit_components  # noqa: F401
    except ImportError:
        return False
    return True


def _gestor():
    """Gestor de cookies, construido una sola vez por sesión de navegador."""
    import extra_streamlit_components as stx

    if _CLAVE_GESTOR not in st.session_state:
        st.session_state[_CLAVE_GESTOR] = stx.CookieManager(key="gestor_cookies_init")
    return st.session_state[_CLAVE_GESTOR]


def nuevo_ciclo() -> None:
    """Invalida la caché de cookies al comenzar una nueva ejecución del script."""
    st.session_state.pop(_CLAVE_CACHE, None)


def _cookies() -> dict:
    """Lee todas las cookies una sola vez por ejecución del script."""
    if _CLAVE_CACHE in st.session_state:
        return st.session_state[_CLAVE_CACHE]
    try:
        cookies = _gestor().get_all(key="cookies_get_all") or {}
    except Exception as error:  # noqa: BLE001 - el componente aún no está listo
        logger.debug("No fue posible leer las cookies todavía: %s", error)
        cookies = {}
    st.session_state[_CLAVE_CACHE] = cookies
    return cookies


def leer_token() -> str | None:
    """Devuelve el token guardado en la cookie, o ``None`` si no hay."""
    if not disponible():
        return None
    return _cookies().get(NOMBRE_COOKIE)


def escribir_token(token: str, expira: datetime, *, seguro: bool = False) -> None:
    """Guarda el token en la cookie del navegador."""
    if not disponible():
        return
    try:
        _gestor().set(
            NOMBRE_COOKIE,
            token,
            key="cookie_set",
            expires_at=expira,
            secure=True if seguro else None,
            same_site="strict",
        )
        # Refleja el cambio en la caché del ciclo para que una lectura posterior
        # de esta misma ejecución ya vea el token.
        st.session_state.setdefault(_CLAVE_CACHE, {})[NOMBRE_COOKIE] = token
    except Exception as error:  # noqa: BLE001
        logger.debug("No fue posible escribir la cookie de sesión: %s", error)


def borrar_token() -> None:
    """Elimina la cookie de sesión del navegador."""
    if not disponible():
        return
    try:
        _gestor().delete(NOMBRE_COOKIE, key="cookie_delete")
    except KeyError:
        # ``delete`` intenta borrar la clave de su propio diccionario; si no está,
        # no hay nada que hacer.
        pass
    except Exception as error:  # noqa: BLE001
        logger.debug("No fue posible borrar la cookie de sesión: %s", error)
    cache = st.session_state.get(_CLAVE_CACHE)
    if cache:
        cache.pop(NOMBRE_COOKIE, None)

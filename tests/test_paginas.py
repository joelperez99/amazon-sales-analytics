"""Pruebas de renderizado de las páginas del tablero.

Usan ``AppTest`` de Streamlit para ejecutar cada página en memoria, sin navegador
ni servidor, con una sesión y un conjunto de datos ya cargados.  Verifican que
ninguna página lance una excepción al dibujarse, ni con datos ni sin ellos.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

#: Todas las páginas del tablero, en el orden de la navegación.
PAGINAS = [
    "01_inicio.py",
    "02_cargar_archivos.py",
    "03_resumen.py",
    "04_ventas.py",
    "05_productos.py",
    "06_tarifas.py",
    "07_reembolsos.py",
    "08_geografia.py",
    "09_liquidaciones.py",
    "10_rentabilidad.py",
    "11_exportar.py",
    "12_configuracion.py",
]

#: Tiempo máximo de ejecución de una página, en segundos.
TIEMPO_LIMITE = 90


@pytest.fixture(scope="module")
def datos_demo() -> pd.DataFrame:
    """Conjunto de datos simulados, generándolo si aún no existe."""
    from services.amazon_parser import leer_archivo
    from services.data_cleaner import limpiar_dataframe
    from utils.config import get_settings

    ruta = get_settings().ruta_datos / "demo" / "transacciones_demo.csv"
    if not ruta.exists():
        from scripts.generar_datos_demo import generar_archivo_demo

        generar_archivo_demo(ruta, meses=1)

    lectura = leer_archivo(ruta.read_bytes(), ruta.name)
    limpio, _ = limpiar_dataframe(lectura.df)
    return limpio


@pytest.fixture(scope="module")
def sesion_prueba():
    """Sesión de un usuario del plan empresarial (todas las funciones activas)."""
    from database.connection import inicializar_base_de_datos
    from database.repositories import OrganizationRepository, UserRepository
    from services.auth_service import Sesion, cifrar_password

    inicializar_base_de_datos()

    correo = "pruebas_paginas@test.mx"
    usuario = UserRepository.por_email(correo)
    if usuario is None:
        organization_id = OrganizationRepository.crear("Pruebas de páginas", plan="empresarial")
        user_id = UserRepository.crear(
            correo, "Usuario de pruebas", cifrar_password("Prueba1234!"),
            organization_id, rol="propietario",
        )
    else:
        user_id = usuario["id"]
        organization_id = usuario["organization_id"]

    return Sesion(
        user_id=user_id,
        email=correo,
        nombre="Usuario de pruebas",
        rol="propietario",
        organization_id=organization_id,
        plan="empresarial",
        organizacion="Pruebas de páginas",
    )


def _preparar(pagina: str, sesion, df: pd.DataFrame | None) -> AppTest:
    """Instancia la página con la sesión y, opcionalmente, con datos cargados."""
    prueba = AppTest.from_file(str(RAIZ / "pages" / pagina), default_timeout=TIEMPO_LIMITE)
    prueba.session_state["_sesion_usuario"] = sesion
    prueba.session_state["_sesion_expira"] = datetime.now() + timedelta(hours=8)
    if df is not None:
        prueba.session_state["df_datos"] = df
    return prueba


@pytest.mark.parametrize("pagina", PAGINAS)
def test_la_pagina_se_dibuja_con_datos(pagina: str, sesion_prueba, datos_demo) -> None:
    """Cada página se renderiza sin excepciones con un periodo cargado."""
    prueba = _preparar(pagina, sesion_prueba, datos_demo).run()
    assert not prueba.exception, (
        f"«{pagina}» lanzó una excepción: "
        + " | ".join(str(e.value) for e in prueba.exception)
    )


@pytest.mark.parametrize("pagina", PAGINAS)
def test_la_pagina_se_dibuja_sin_datos(pagina: str, sesion_prueba) -> None:
    """Cada página resuelve el estado vacío sin romperse."""
    prueba = _preparar(pagina, sesion_prueba, None).run()
    assert not prueba.exception, (
        f"«{pagina}» falló sin datos: "
        + " | ".join(str(e.value) for e in prueba.exception)
    )


def test_el_periodo_sin_registros_muestra_un_aviso(sesion_prueba, datos_demo) -> None:
    """Filtrar hasta dejar el periodo vacío avisa, no truena."""
    from components.filters import EstadoFiltros

    prueba = _preparar("03_resumen.py", sesion_prueba, datos_demo)
    prueba.session_state["filtros"] = EstadoFiltros(
        fecha_inicio=datos_demo["fecha_hora"].min().date(),
        fecha_fin=datos_demo["fecha_hora"].min().date(),
        skus=["SKU-QUE-NO-EXISTE"],
    )
    resultado = prueba.run()
    assert not resultado.exception


def test_la_pantalla_de_acceso_se_dibuja() -> None:
    """La aplicación principal muestra el formulario de acceso sin sesión."""
    prueba = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=TIEMPO_LIMITE).run()
    assert not prueba.exception

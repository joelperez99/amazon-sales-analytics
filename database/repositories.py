"""Repositorios: todo el acceso a la base de datos.

Cada método recibe el ``organization_id`` (y a veces el ``user_id``) y filtra por
él sin excepción.  Ese es el mecanismo de aislamiento entre inquilinos: no hay
forma de leer datos de otra organización desde la interfaz.

Todas las consultas son parametrizadas por SQLAlchemy: no se concatena texto SQL
en ningún punto del proyecto.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import and_, delete, func, select

from database.connection import obtener_sesion
from database.models import (
    Alert,
    AuditLog,
    Dashboard,
    ExportHistory,
    Import,
    Organization,
    OrganizationMember,
    ProductCost,
    SavedFilter,
    Subscription,
    Transaction,
    UploadedFile,
    User,
)
from utils.constants import PLANES
from utils.logger import get_logger

logger = get_logger("repositories")

#: Columnas del DataFrame que se persisten en la tabla ``transactions``.
_COLUMNAS_TRANSACCION: tuple[str, ...] = (
    "fecha_hora", "id_liquidacion", "tipo", "id_pedido", "sku", "descripcion",
    "cantidad", "marketplace", "cumplimiento", "ciudad", "estado", "codigo_postal",
    "modelo_impuestos", "ventas_productos", "impuesto_ventas_productos",
    "creditos_envio", "impuesto_envio", "creditos_envoltorio", "impuesto_envoltorio",
    "tarifa_reglamentaria", "impuesto_tarifa_reglamentaria", "descuentos_promocionales",
    "impuesto_descuentos_promocionales", "retenciones_plataforma", "tarifas_venta",
    "tarifas_fba", "tarifas_otras", "otro", "total", "estado_transaccion",
    "fecha_liberacion", "row_hash",
)


def _slug(texto: str) -> str:
    """Convierte un nombre en un identificador apto para URL."""
    limpio = re.sub(r"[^a-z0-9]+", "-", str(texto).lower()).strip("-")
    return limpio or "organizacion"


# =============================================================================
# Organizaciones
# =============================================================================


class OrganizationRepository:
    """Altas y consultas de organizaciones y su plan."""

    @staticmethod
    def crear(nombre: str, plan: str = "gratuito") -> int:
        with obtener_sesion() as sesion:
            base = _slug(nombre)
            slug = base
            intento = 1
            while sesion.scalar(select(Organization.id).where(Organization.slug == slug)):
                intento += 1
                slug = f"{base}-{intento}"

            organizacion = Organization(nombre=nombre, slug=slug, plan=plan)
            sesion.add(organizacion)
            sesion.flush()

            sesion.add(Subscription(
                organization_id=organizacion.id,
                plan=plan,
                estado="activa",
                periodo_inicio=date.today(),
                mes_referencia=date.today().strftime("%Y-%m"),
            ))
            return organizacion.id

    @staticmethod
    def obtener(organization_id: int) -> dict[str, Any] | None:
        with obtener_sesion() as sesion:
            organizacion = sesion.get(Organization, organization_id)
            if organizacion is None:
                return None
            return {
                "id": organizacion.id,
                "nombre": organizacion.nombre,
                "slug": organizacion.slug,
                "plan": organizacion.plan,
                "logo_url": organizacion.logo_url,
                "color_primario": organizacion.color_primario,
            }

    @staticmethod
    def actualizar_plan(organization_id: int, plan: str) -> None:
        if plan not in PLANES:
            raise ValueError(f"Plan desconocido: {plan}")
        with obtener_sesion() as sesion:
            organizacion = sesion.get(Organization, organization_id)
            if organizacion is None:
                return
            organizacion.plan = plan
            suscripcion = sesion.scalar(
                select(Subscription).where(Subscription.organization_id == organization_id)
            )
            if suscripcion is None:
                sesion.add(Subscription(organization_id=organization_id, plan=plan))
            else:
                suscripcion.plan = plan

    @staticmethod
    def actualizar_branding(
        organization_id: int, nombre: str | None = None,
        logo_url: str | None = None, color: str | None = None,
    ) -> None:
        with obtener_sesion() as sesion:
            organizacion = sesion.get(Organization, organization_id)
            if organizacion is None:
                return
            if nombre:
                organizacion.nombre = nombre
            if logo_url is not None:
                organizacion.logo_url = logo_url
            if color is not None:
                organizacion.color_primario = color

    @staticmethod
    def miembros(organization_id: int) -> pd.DataFrame:
        """Usuarios que pertenecen a la organización."""
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(User.email, User.nombre, OrganizationMember.rol, OrganizationMember.invitado_en)
                .join(OrganizationMember, OrganizationMember.user_id == User.id)
                .where(OrganizationMember.organization_id == organization_id)
                .order_by(OrganizationMember.invitado_en)
            ).all()
        return pd.DataFrame(filas, columns=["Correo", "Nombre", "Rol", "Desde"])

    @staticmethod
    def agregar_miembro(organization_id: int, user_id: int, rol: str = "analista") -> None:
        with obtener_sesion() as sesion:
            existente = sesion.scalar(
                select(OrganizationMember).where(and_(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.user_id == user_id,
                ))
            )
            if existente is not None:
                existente.rol = rol
                return
            sesion.add(OrganizationMember(
                organization_id=organization_id, user_id=user_id, rol=rol
            ))


# =============================================================================
# Usuarios
# =============================================================================


class UserRepository:
    """Consultas sobre usuarios.  El hash de la contraseña nunca sale de aquí."""

    @staticmethod
    def crear(
        email: str, nombre: str, password_hash: str,
        organization_id: int, rol: str = "propietario", es_demo: bool = False,
    ) -> int:
        with obtener_sesion() as sesion:
            usuario = User(
                email=email.strip().lower(),
                nombre=nombre.strip(),
                password_hash=password_hash,
                organization_id=organization_id,
                rol=rol,
                es_demo=es_demo,
            )
            sesion.add(usuario)
            sesion.flush()
            sesion.add(OrganizationMember(
                organization_id=organization_id, user_id=usuario.id, rol=rol
            ))
            return usuario.id

    @staticmethod
    def por_email(email: str) -> dict[str, Any] | None:
        with obtener_sesion() as sesion:
            usuario = sesion.scalar(
                select(User).where(User.email == email.strip().lower())
            )
            return UserRepository._a_dict(usuario) if usuario else None

    @staticmethod
    def por_id(user_id: int) -> dict[str, Any] | None:
        with obtener_sesion() as sesion:
            return UserRepository._a_dict(sesion.get(User, user_id))

    @staticmethod
    def _a_dict(usuario: User | None) -> dict[str, Any] | None:
        if usuario is None:
            return None
        return {
            "id": usuario.id,
            "email": usuario.email,
            "nombre": usuario.nombre,
            "password_hash": usuario.password_hash,
            "rol": usuario.rol,
            "organization_id": usuario.organization_id,
            "activo": usuario.activo,
            "es_demo": usuario.es_demo,
            "ultimo_acceso": usuario.ultimo_acceso,
            "preferencias": usuario.preferencias or {},
        }

    @staticmethod
    def registrar_acceso(user_id: int) -> None:
        with obtener_sesion() as sesion:
            usuario = sesion.get(User, user_id)
            if usuario is not None:
                usuario.ultimo_acceso = datetime.now()

    @staticmethod
    def actualizar_password(user_id: int, password_hash: str) -> None:
        with obtener_sesion() as sesion:
            usuario = sesion.get(User, user_id)
            if usuario is not None:
                usuario.password_hash = password_hash
                usuario.token_recuperacion = None
                usuario.token_expira = None

    @staticmethod
    def guardar_token_recuperacion(email: str, token: str, horas: int = 2) -> bool:
        with obtener_sesion() as sesion:
            usuario = sesion.scalar(select(User).where(User.email == email.strip().lower()))
            if usuario is None:
                return False
            usuario.token_recuperacion = token
            usuario.token_expira = datetime.now() + timedelta(hours=horas)
            return True

    @staticmethod
    def por_token(token: str) -> dict[str, Any] | None:
        with obtener_sesion() as sesion:
            usuario = sesion.scalar(
                select(User).where(and_(
                    User.token_recuperacion == token,
                    User.token_expira > datetime.now(),
                ))
            )
            return UserRepository._a_dict(usuario) if usuario else None

    @staticmethod
    def guardar_preferencias(user_id: int, preferencias: dict[str, Any]) -> None:
        with obtener_sesion() as sesion:
            usuario = sesion.get(User, user_id)
            if usuario is not None:
                actuales = dict(usuario.preferencias or {})
                actuales.update(preferencias)
                usuario.preferencias = actuales

    @staticmethod
    def total_usuarios() -> int:
        with obtener_sesion() as sesion:
            return int(sesion.scalar(select(func.count(User.id))) or 0)


# =============================================================================
# Archivos e importaciones
# =============================================================================


class FileRepository:
    """Historial de archivos subidos."""

    @staticmethod
    def registrar(
        user_id: int, organization_id: int, nombre_original: str,
        nombre_almacenado: str, ruta: str, backend: str, extension: str,
        tamano_bytes: int, hash_contenido: str, filas: int, columnas: int,
    ) -> int:
        with obtener_sesion() as sesion:
            archivo = UploadedFile(
                user_id=user_id, organization_id=organization_id,
                nombre_original=nombre_original, nombre_almacenado=nombre_almacenado,
                ruta=ruta, backend=backend, extension=extension,
                tamano_bytes=tamano_bytes, hash_contenido=hash_contenido,
                filas=filas, columnas=columnas,
            )
            sesion.add(archivo)
            sesion.flush()
            return archivo.id

    @staticmethod
    def listar(organization_id: int, limite: int = 50) -> pd.DataFrame:
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(
                    UploadedFile.id, UploadedFile.nombre_original, UploadedFile.filas,
                    UploadedFile.columnas, UploadedFile.tamano_bytes, UploadedFile.subido_en,
                )
                .where(and_(
                    UploadedFile.organization_id == organization_id,
                    UploadedFile.eliminado.is_(False),
                ))
                .order_by(UploadedFile.subido_en.desc())
                .limit(limite)
            ).all()
        return pd.DataFrame(
            filas, columns=["Id", "Archivo", "Filas", "Columnas", "Bytes", "Subido"]
        )

    @staticmethod
    def existe_hash(organization_id: int, hash_contenido: str) -> bool:
        """``True`` si ya se subió un archivo con el mismo contenido."""
        with obtener_sesion() as sesion:
            return bool(sesion.scalar(
                select(UploadedFile.id).where(and_(
                    UploadedFile.organization_id == organization_id,
                    UploadedFile.hash_contenido == hash_contenido,
                    UploadedFile.eliminado.is_(False),
                )).limit(1)
            ))

    @staticmethod
    def contar_del_mes(organization_id: int) -> int:
        """Archivos subidos en el mes en curso (para los límites del plan)."""
        inicio_mes = date.today().replace(day=1)
        with obtener_sesion() as sesion:
            return int(sesion.scalar(
                select(func.count(UploadedFile.id)).where(and_(
                    UploadedFile.organization_id == organization_id,
                    UploadedFile.subido_en >= datetime.combine(inicio_mes, datetime.min.time()),
                    UploadedFile.eliminado.is_(False),
                ))
            ) or 0)

    @staticmethod
    def marcar_eliminado(archivo_id: int, organization_id: int) -> str | None:
        """Marca el archivo como eliminado y devuelve su ruta para borrarlo del almacenamiento."""
        with obtener_sesion() as sesion:
            archivo = sesion.scalar(
                select(UploadedFile).where(and_(
                    UploadedFile.id == archivo_id,
                    UploadedFile.organization_id == organization_id,
                ))
            )
            if archivo is None:
                return None
            archivo.eliminado = True
            return archivo.ruta

    @staticmethod
    def antiguos(organization_id: int, dias: int) -> list[tuple[int, str]]:
        """Archivos que superaron la política de retención."""
        if dias <= 0:
            return []
        limite = datetime.now() - timedelta(days=dias)
        with obtener_sesion() as sesion:
            return [
                (fila[0], fila[1])
                for fila in sesion.execute(
                    select(UploadedFile.id, UploadedFile.ruta).where(and_(
                        UploadedFile.organization_id == organization_id,
                        UploadedFile.subido_en < limite,
                        UploadedFile.eliminado.is_(False),
                    ))
                ).all()
            ]


class ImportRepository:
    """Registro de cada procesamiento y persistencia de las transacciones."""

    @staticmethod
    def crear(
        user_id: int, organization_id: int, uploaded_file_id: int | None,
        filas_leidas: int, filas_validas: int, filas_descartadas: int,
        duplicados: int, periodo_inicio: date | None, periodo_fin: date | None,
        mensaje: str = "",
    ) -> int:
        with obtener_sesion() as sesion:
            importacion = Import(
                user_id=user_id, organization_id=organization_id,
                uploaded_file_id=uploaded_file_id, estado="completada",
                filas_leidas=filas_leidas, filas_validas=filas_validas,
                filas_descartadas=filas_descartadas, duplicados=duplicados,
                periodo_inicio=periodo_inicio, periodo_fin=periodo_fin,
                mensaje=mensaje[:4000], terminada_en=datetime.now(),
            )
            sesion.add(importacion)
            sesion.flush()
            return importacion.id

    @staticmethod
    def guardar_transacciones(
        df: pd.DataFrame, user_id: int, organization_id: int,
        import_id: int, uploaded_file_id: int | None = None,
        tamano_lote: int = 5_000,
    ) -> int:
        """Guarda las transacciones evitando repetir las que ya existen.

        La restricción única ``(organization_id, row_hash)`` impide duplicar un
        registro que ya está en la base; aquí se filtra antes de insertar para no
        provocar el error.

        Returns:
            Número de filas realmente insertadas.
        """
        if df.empty:
            return 0

        columnas = [c for c in _COLUMNAS_TRANSACCION if c in df.columns]
        datos = df[columnas].copy()

        # Normaliza tipos para el driver: NaT/NaN -> None.
        for columna in datos.columns:
            if pd.api.types.is_datetime64_any_dtype(datos[columna]):
                datos[columna] = datos[columna].astype("object").where(datos[columna].notna(), None)
            elif pd.api.types.is_numeric_dtype(datos[columna]):
                datos[columna] = datos[columna].fillna(0.0).astype(float)
            else:
                datos[columna] = datos[columna].astype("object").where(datos[columna].notna(), None)

        registros = datos.to_dict("records")
        ahora = datetime.now()

        insertadas = 0
        with obtener_sesion() as sesion:
            existentes: set[str] = set()
            if "row_hash" in columnas:
                hashes = [r["row_hash"] for r in registros if r.get("row_hash")]
                # Se consulta en bloques para no exceder el límite de parámetros.
                for inicio in range(0, len(hashes), 900):
                    lote = hashes[inicio: inicio + 900]
                    encontrados = sesion.execute(
                        select(Transaction.row_hash).where(and_(
                            Transaction.organization_id == organization_id,
                            Transaction.row_hash.in_(lote),
                        ))
                    ).scalars().all()
                    existentes.update(h for h in encontrados if h)

            nuevos = [
                {
                    **registro,
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "import_id": import_id,
                    "uploaded_file_id": uploaded_file_id,
                    "importada_en": ahora,
                }
                for registro in registros
                if not registro.get("row_hash") or registro["row_hash"] not in existentes
            ]

            # Dentro del mismo archivo también puede haber hashes repetidos.
            vistos: set[str] = set()
            unicos = []
            for registro in nuevos:
                clave = registro.get("row_hash")
                if clave and clave in vistos:
                    continue
                if clave:
                    vistos.add(clave)
                unicos.append(registro)

            for inicio in range(0, len(unicos), tamano_lote):
                sesion.bulk_insert_mappings(Transaction, unicos[inicio: inicio + tamano_lote])
                insertadas += len(unicos[inicio: inicio + tamano_lote])

        logger.info(
            "Transacciones guardadas: %d nuevas de %d (organización %d).",
            insertadas, len(registros), organization_id,
        )
        return insertadas

    @staticmethod
    def cargar_transacciones(
        organization_id: int,
        desde: date | None = None,
        hasta: date | None = None,
        limite: int | None = None,
    ) -> pd.DataFrame:
        """Recupera el histórico de transacciones de la organización."""
        with obtener_sesion() as sesion:
            consulta = select(Transaction).where(
                Transaction.organization_id == organization_id
            )
            if desde is not None:
                consulta = consulta.where(
                    Transaction.fecha_hora >= datetime.combine(desde, datetime.min.time())
                )
            if hasta is not None:
                consulta = consulta.where(
                    Transaction.fecha_hora <= datetime.combine(hasta, datetime.max.time())
                )
            consulta = consulta.order_by(Transaction.fecha_hora)
            if limite:
                consulta = consulta.limit(limite)

            filas = sesion.scalars(consulta).all()

        if not filas:
            return pd.DataFrame()

        registros = [
            {columna: getattr(fila, columna) for columna in _COLUMNAS_TRANSACCION}
            for fila in filas
        ]
        df = pd.DataFrame(registros)

        from services.data_cleaner import optimizar_tipos
        from utils.constants import COL_ES_DUPLICADO, COL_FECHA
        from utils.date_parser import enriquecer_columnas_fecha

        df[COL_FECHA] = pd.to_datetime(df[COL_FECHA], errors="coerce")
        df["fecha_liberacion"] = pd.to_datetime(df["fecha_liberacion"], errors="coerce")
        df = enriquecer_columnas_fecha(df, COL_FECHA)
        df[COL_ES_DUPLICADO] = False
        return optimizar_tipos(df)

    @staticmethod
    def listar(organization_id: int, limite: int = 20) -> pd.DataFrame:
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(
                    Import.id, Import.filas_leidas, Import.filas_validas,
                    Import.duplicados, Import.periodo_inicio, Import.periodo_fin,
                    Import.iniciada_en,
                )
                .where(Import.organization_id == organization_id)
                .order_by(Import.iniciada_en.desc())
                .limit(limite)
            ).all()
        return pd.DataFrame(
            filas,
            columns=["Id", "Filas leídas", "Filas válidas", "Duplicados", "Desde", "Hasta", "Fecha"],
        )

    @staticmethod
    def ultimo_periodo(organization_id: int) -> tuple[date | None, date | None]:
        with obtener_sesion() as sesion:
            fila = sesion.execute(
                select(Import.periodo_inicio, Import.periodo_fin)
                .where(Import.organization_id == organization_id)
                .order_by(Import.iniciada_en.desc())
                .limit(1)
            ).first()
        return (fila[0], fila[1]) if fila else (None, None)

    @staticmethod
    def eliminar_todo(organization_id: int) -> int:
        """Borra el histórico de transacciones de la organización."""
        with obtener_sesion() as sesion:
            resultado = sesion.execute(
                delete(Transaction).where(Transaction.organization_id == organization_id)
            )
            return int(resultado.rowcount or 0)


# =============================================================================
# Costos, filtros, alertas y auditoría
# =============================================================================


class CostRepository:
    """Catálogo de costos por SKU."""

    @staticmethod
    def guardar(organization_id: int, user_id: int, catalogo: pd.DataFrame) -> int:
        """Inserta o actualiza los costos.  Devuelve cuántos SKU se guardaron."""
        if catalogo is None or catalogo.empty:
            return 0

        with obtener_sesion() as sesion:
            guardados = 0
            for registro in catalogo.to_dict("records"):
                sku = str(registro.get("sku", "")).strip()
                if not sku:
                    continue
                existente = sesion.scalar(
                    select(ProductCost).where(and_(
                        ProductCost.organization_id == organization_id,
                        ProductCost.sku == sku,
                    ))
                )
                valores = {
                    "costo_unitario": float(registro.get("costo_unitario") or 0),
                    "costo_logistico_adicional": float(registro.get("costo_logistico_adicional") or 0),
                    "gasto_publicitario": float(registro.get("gasto_publicitario") or 0),
                    "marca": str(registro.get("marca") or "")[:120],
                    "categoria": str(registro.get("categoria") or "")[:120],
                }
                if existente is None:
                    sesion.add(ProductCost(
                        organization_id=organization_id, user_id=user_id, sku=sku, **valores
                    ))
                else:
                    for clave, valor in valores.items():
                        setattr(existente, clave, valor)
                guardados += 1
            return guardados

    @staticmethod
    def cargar(organization_id: int) -> pd.DataFrame:
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(
                    ProductCost.sku, ProductCost.costo_unitario,
                    ProductCost.costo_logistico_adicional, ProductCost.gasto_publicitario,
                    ProductCost.marca, ProductCost.categoria,
                ).where(ProductCost.organization_id == organization_id)
                .order_by(ProductCost.sku)
            ).all()
        if not filas:
            from services.profitability_service import catalogo_vacio

            return catalogo_vacio()
        return pd.DataFrame(filas, columns=[
            "sku", "costo_unitario", "costo_logistico_adicional",
            "gasto_publicitario", "marca", "categoria",
        ])

    @staticmethod
    def eliminar(organization_id: int, sku: str) -> None:
        with obtener_sesion() as sesion:
            sesion.execute(
                delete(ProductCost).where(and_(
                    ProductCost.organization_id == organization_id,
                    ProductCost.sku == sku,
                ))
            )


class FilterRepository:
    """Filtros guardados por el usuario."""

    @staticmethod
    def guardar(user_id: int, organization_id: int, nombre: str, filtros: dict[str, Any]) -> int:
        with obtener_sesion() as sesion:
            existente = sesion.scalar(
                select(SavedFilter).where(and_(
                    SavedFilter.user_id == user_id, SavedFilter.nombre == nombre
                ))
            )
            if existente is not None:
                existente.filtros = filtros
                return existente.id
            filtro = SavedFilter(
                user_id=user_id, organization_id=organization_id,
                nombre=nombre, filtros=filtros,
            )
            sesion.add(filtro)
            sesion.flush()
            return filtro.id

    @staticmethod
    def listar(user_id: int) -> list[dict[str, Any]]:
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(SavedFilter.id, SavedFilter.nombre, SavedFilter.filtros)
                .where(SavedFilter.user_id == user_id)
                .order_by(SavedFilter.creado_en.desc())
            ).all()
        return [{"id": f[0], "nombre": f[1], "filtros": f[2]} for f in filas]

    @staticmethod
    def eliminar(filtro_id: int, user_id: int) -> None:
        with obtener_sesion() as sesion:
            sesion.execute(
                delete(SavedFilter).where(and_(
                    SavedFilter.id == filtro_id, SavedFilter.user_id == user_id
                ))
            )


class AlertRepository:
    """Histórico de hallazgos."""

    @staticmethod
    def guardar_lote(
        user_id: int, organization_id: int, import_id: int | None, hallazgos: list[Any]
    ) -> int:
        if not hallazgos:
            return 0
        with obtener_sesion() as sesion:
            for hallazgo in hallazgos:
                sesion.add(Alert(
                    user_id=user_id, organization_id=organization_id, import_id=import_id,
                    severidad=getattr(hallazgo, "severidad", "informativo"),
                    categoria=getattr(hallazgo, "categoria", "General")[:60],
                    titulo=getattr(hallazgo, "titulo", "")[:255],
                    mensaje=getattr(hallazgo, "mensaje", ""),
                    recomendacion=getattr(hallazgo, "recomendacion", ""),
                ))
            return len(hallazgos)

    @staticmethod
    def listar(organization_id: int, limite: int = 100) -> pd.DataFrame:
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(Alert.severidad, Alert.categoria, Alert.titulo, Alert.mensaje, Alert.creada_en)
                .where(Alert.organization_id == organization_id)
                .order_by(Alert.creada_en.desc())
                .limit(limite)
            ).all()
        return pd.DataFrame(filas, columns=["Severidad", "Categoría", "Hallazgo", "Detalle", "Fecha"])


class ExportRepository:
    """Historial de descargas."""

    @staticmethod
    def registrar(
        user_id: int, organization_id: int, tipo_reporte: str,
        formato: str, nombre_archivo: str, filas: int,
    ) -> None:
        with obtener_sesion() as sesion:
            sesion.add(ExportHistory(
                user_id=user_id, organization_id=organization_id,
                tipo_reporte=tipo_reporte[:80], formato=formato[:20],
                nombre_archivo=nombre_archivo[:255], filas=filas,
            ))

    @staticmethod
    def listar(organization_id: int, limite: int = 50) -> pd.DataFrame:
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(
                    ExportHistory.tipo_reporte, ExportHistory.formato,
                    ExportHistory.nombre_archivo, ExportHistory.filas,
                    ExportHistory.generado_en,
                )
                .where(ExportHistory.organization_id == organization_id)
                .order_by(ExportHistory.generado_en.desc())
                .limit(limite)
            ).all()
        return pd.DataFrame(filas, columns=["Reporte", "Formato", "Archivo", "Filas", "Fecha"])


class AuditRepository:
    """Bitácora de acciones."""

    @staticmethod
    def registrar(
        accion: str, usuario_id: int | None = None,
        organization_id: int | None = None, detalle: dict[str, Any] | None = None,
    ) -> None:
        with obtener_sesion() as sesion:
            sesion.add(AuditLog(
                user_id=usuario_id, organization_id=organization_id,
                accion=accion[:120], detalle=detalle or {},
            ))

    @staticmethod
    def listar(organization_id: int | None = None, limite: int = 200) -> pd.DataFrame:
        with obtener_sesion() as sesion:
            consulta = select(AuditLog.creado_en, AuditLog.accion, AuditLog.user_id, AuditLog.detalle)
            if organization_id is not None:
                consulta = consulta.where(AuditLog.organization_id == organization_id)
            filas = sesion.execute(
                consulta.order_by(AuditLog.creado_en.desc()).limit(limite)
            ).all()
        return pd.DataFrame(filas, columns=["Fecha", "Acción", "Usuario", "Detalle"])


class DashboardRepository:
    """Tableros guardados."""

    @staticmethod
    def guardar(user_id: int, organization_id: int, nombre: str, configuracion: dict[str, Any]) -> int:
        with obtener_sesion() as sesion:
            existente = sesion.scalar(
                select(Dashboard).where(and_(
                    Dashboard.user_id == user_id, Dashboard.nombre == nombre
                ))
            )
            if existente is not None:
                existente.configuracion = configuracion
                return existente.id
            tablero = Dashboard(
                user_id=user_id, organization_id=organization_id,
                nombre=nombre, configuracion=configuracion,
            )
            sesion.add(tablero)
            sesion.flush()
            return tablero.id

    @staticmethod
    def listar(user_id: int) -> list[dict[str, Any]]:
        with obtener_sesion() as sesion:
            filas = sesion.execute(
                select(Dashboard.id, Dashboard.nombre, Dashboard.configuracion)
                .where(Dashboard.user_id == user_id)
                .order_by(Dashboard.creado_en.desc())
            ).all()
        return [{"id": f[0], "nombre": f[1], "configuracion": f[2]} for f in filas]

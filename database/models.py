"""Modelo de datos (SQLAlchemy 2.0).

Aislamiento por inquilino
-------------------------
Cada fila de negocio lleva ``organization_id`` y ``user_id``.  Los repositorios
**siempre** filtran por esos campos, de modo que un usuario nunca puede ver los
archivos, las transacciones ni los costos de otra cuenta.

Índices
-------
Se declaran índices para las columnas por las que se consulta con frecuencia:
fecha, Id. del pedido, SKU, Id. de liquidación, tipo, usuario y organización.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Clase base de todos los modelos."""


#: Entero de 64 bits para las llaves de las tablas grandes.
#:
#: SQLite solo autoincrementa una columna declarada como ``INTEGER PRIMARY KEY``;
#: con ``BIGINT`` deja de ser alias de ``rowid`` y las inserciones fallan.  Esta
#: variante usa ``INTEGER`` en SQLite y ``BIGINT`` en PostgreSQL.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def _ahora() -> datetime:
    return datetime.now()


# =============================================================================
# Organizaciones y usuarios
# =============================================================================


class Organization(Base):
    """Cuenta de cliente.  Un usuario individual también tiene su organización."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(40), default="gratuito", nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    color_primario: Mapped[str | None] = mapped_column(String(20))
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)

    miembros: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    suscripcion: Mapped["Subscription | None"] = relationship(
        back_populates="organizacion", uselist=False, cascade="all, delete-orphan"
    )


class User(Base):
    """Usuario que inicia sesión en la aplicación."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Hash bcrypt.  La contraseña en claro nunca se almacena ni se registra.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(40), default="propietario", nullable=False)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    es_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token_recuperacion: Mapped[str | None] = mapped_column(String(255))
    token_expira: Mapped[datetime | None] = mapped_column(DateTime)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)

    preferencias: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)


class UserSession(Base):
    """Sesión persistente ligada a una cookie del navegador.

    Solo se guarda el **hash** del token (SHA-256), nunca el token en claro: así,
    aunque alguien lea la base, no puede reconstruir la cookie de un usuario.  La
    cookie mantiene la sesión iniciada aunque se reinicie el servidor.
    """

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expira: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)


class OrganizationMember(Base):
    """Relación usuario–organización con su rol (planes multiusuario)."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_miembro_organizacion"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rol: Mapped[str] = mapped_column(String(40), default="analista", nullable=False)
    invitado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)

    organizacion: Mapped[Organization] = relationship(back_populates="miembros")


class Subscription(Base):
    """Plan contratado por una organización (preparado para Stripe)."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[str] = mapped_column(String(40), default="gratuito", nullable=False)
    estado: Mapped[str] = mapped_column(String(40), default="activa", nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120))
    periodo_inicio: Mapped[date | None] = mapped_column(Date)
    periodo_fin: Mapped[date | None] = mapped_column(Date)
    archivos_usados_mes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mes_referencia: Mapped[str | None] = mapped_column(String(7))  # "2026-07"
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime, default=_ahora, onupdate=_ahora, nullable=False
    )

    organizacion: Mapped[Organization] = relationship(back_populates="suscripcion")


# =============================================================================
# Archivos e importaciones
# =============================================================================


class UploadedFile(Base):
    """Archivo subido por el usuario, guardado en el backend de almacenamiento."""

    __tablename__ = "uploaded_files"
    __table_args__ = (
        Index("ix_archivos_org_fecha", "organization_id", "subido_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_almacenado: Mapped[str] = mapped_column(String(255), nullable=False)
    ruta: Mapped[str] = mapped_column(String(1000), nullable=False)
    backend: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    #: SHA-256 del contenido: permite avisar si se sube dos veces el mismo archivo.
    hash_contenido: Mapped[str | None] = mapped_column(String(64), index=True)
    filas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    columnas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subido_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)
    eliminado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Import(Base):
    """Ejecución de procesamiento de uno o varios archivos."""

    __tablename__ = "imports"
    __table_args__ = (
        Index("ix_imports_org_fecha", "organization_id", "iniciada_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploaded_files.id", ondelete="SET NULL"), index=True
    )
    estado: Mapped[str] = mapped_column(String(30), default="completada", nullable=False)
    filas_leidas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filas_validas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filas_descartadas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    periodo_inicio: Mapped[date | None] = mapped_column(Date)
    periodo_fin: Mapped[date | None] = mapped_column(Date)
    mensaje: Mapped[str | None] = mapped_column(Text)
    iniciada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)
    terminada_en: Mapped[datetime | None] = mapped_column(DateTime)


class Transaction(Base):
    """Una línea del reporte de transacciones de Amazon.

    Se conservan los nombres canónicos del proyecto para que la fila de la base
    de datos y la fila del DataFrame sean intercambiables.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_tx_org_fecha", "organization_id", "fecha_hora"),
        Index("ix_tx_org_sku", "organization_id", "sku"),
        Index("ix_tx_org_pedido", "organization_id", "id_pedido"),
        Index("ix_tx_org_liquidacion", "organization_id", "id_liquidacion"),
        Index("ix_tx_org_tipo", "organization_id", "tipo"),
        UniqueConstraint("organization_id", "row_hash", name="uq_tx_org_hash"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)

    # --- Aislamiento y trazabilidad -----------------------------------------
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("imports.id", ondelete="CASCADE"), index=True
    )
    uploaded_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploaded_files.id", ondelete="SET NULL")
    )
    importada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)
    row_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # --- Campos del reporte --------------------------------------------------
    fecha_hora: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    id_liquidacion: Mapped[str | None] = mapped_column(String(60))
    tipo: Mapped[str | None] = mapped_column(String(60))
    id_pedido: Mapped[str | None] = mapped_column(String(60))
    sku: Mapped[str | None] = mapped_column(String(120))
    descripcion: Mapped[str | None] = mapped_column(Text)
    cantidad: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    marketplace: Mapped[str | None] = mapped_column(String(80))
    cumplimiento: Mapped[str | None] = mapped_column(String(60))
    ciudad: Mapped[str | None] = mapped_column(String(160))
    estado: Mapped[str | None] = mapped_column(String(120))
    codigo_postal: Mapped[str | None] = mapped_column(String(20))
    modelo_impuestos: Mapped[str | None] = mapped_column(String(80))

    ventas_productos: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impuesto_ventas_productos: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    creditos_envio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impuesto_envio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    creditos_envoltorio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impuesto_envoltorio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tarifa_reglamentaria: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impuesto_tarifa_reglamentaria: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    descuentos_promocionales: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impuesto_descuentos_promocionales: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    retenciones_plataforma: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tarifas_venta: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tarifas_fba: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tarifas_otras: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    otro: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    estado_transaccion: Mapped[str | None] = mapped_column(String(60))
    fecha_liberacion: Mapped[datetime | None] = mapped_column(DateTime)


class Product(Base):
    """Catálogo de productos derivado de los SKU vistos en los reportes."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_producto_org_sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    descripcion: Mapped[str | None] = mapped_column(Text)
    marca: Mapped[str | None] = mapped_column(String(120))
    categoria: Mapped[str | None] = mapped_column(String(120))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)


class ProductCost(Base):
    """Costo por SKU capturado por el usuario."""

    __tablename__ = "product_costs"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_costo_org_sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sku: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    costo_unitario: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    costo_logistico_adicional: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    gasto_publicitario: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    marca: Mapped[str | None] = mapped_column(String(120))
    categoria: Mapped[str | None] = mapped_column(String(120))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, default=_ahora, onupdate=_ahora, nullable=False
    )


# =============================================================================
# Configuración del usuario
# =============================================================================


class Dashboard(Base):
    """Configuración de un tablero guardado por el usuario."""

    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    configuracion: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    es_predeterminado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)


class SavedFilter(Base):
    """Combinación de filtros guardada para reutilizarla."""

    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    filtros: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)


class Alert(Base):
    """Hallazgo generado en un análisis, conservado como histórico."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alertas_org_fecha", "organization_id", "creada_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"))
    severidad: Mapped[str] = mapped_column(String(20), default="informativo", nullable=False)
    categoria: Mapped[str] = mapped_column(String(60), default="General", nullable=False)
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    recomendacion: Mapped[str | None] = mapped_column(Text)
    atendida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)


class ExportHistory(Base):
    """Registro de cada descarga generada."""

    __tablename__ = "export_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_reporte: Mapped[str] = mapped_column(String(80), nullable=False)
    formato: Mapped[str] = mapped_column(String(20), default="xlsx", nullable=False)
    nombre_archivo: Mapped[str] = mapped_column(String(255), nullable=False)
    filas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, nullable=False)


class AuditLog(Base):
    """Bitácora de acciones. No guarda datos sensibles, solo qué pasó y cuándo."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_auditoria_fecha", "creado_en"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    accion: Mapped[str] = mapped_column(String(120), nullable=False)
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, default=_ahora, server_default=func.now(), nullable=False
    )

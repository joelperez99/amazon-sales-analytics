-- =============================================================================
-- Amazon Sales Analytics — esquema inicial (PostgreSQL)
--
-- La aplicación crea estas tablas por su cuenta al arrancar (SQLAlchemy
-- ``create_all``).  Este script existe para tres casos:
--
--   1. Provisionar la base de datos antes del primer despliegue.
--   2. Inicializar el contenedor de PostgreSQL con docker-compose
--      (la carpeta se monta en /docker-entrypoint-initdb.d).
--   3. Revisar el modelo de datos sin leer el código de Python.
--
-- Es idempotente: todas las sentencias usan IF NOT EXISTS.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Organizaciones y usuarios
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organizations (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(200) NOT NULL,
    slug            VARCHAR(120) NOT NULL UNIQUE,
    plan            VARCHAR(40)  NOT NULL DEFAULT 'gratuito',
    logo_url        VARCHAR(500),
    color_primario  VARCHAR(20),
    activa          BOOLEAN      NOT NULL DEFAULT TRUE,
    creada_en       TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_organizations_slug ON organizations (slug);

CREATE TABLE IF NOT EXISTS users (
    id                  SERIAL PRIMARY KEY,
    email               VARCHAR(255) NOT NULL UNIQUE,
    nombre              VARCHAR(200) NOT NULL,
    -- Hash bcrypt o PBKDF2. La contraseña en claro jamás se almacena.
    password_hash       VARCHAR(255) NOT NULL,
    rol                 VARCHAR(40)  NOT NULL DEFAULT 'propietario',
    organization_id     INTEGER      REFERENCES organizations (id) ON DELETE SET NULL,
    activo              BOOLEAN      NOT NULL DEFAULT TRUE,
    es_demo             BOOLEAN      NOT NULL DEFAULT FALSE,
    token_recuperacion  VARCHAR(255),
    token_expira        TIMESTAMP,
    ultimo_acceso       TIMESTAMP,
    preferencias        JSONB        DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_users_email  ON users (email);
CREATE INDEX IF NOT EXISTS ix_users_org    ON users (organization_id);

CREATE TABLE IF NOT EXISTS organization_members (
    id              SERIAL PRIMARY KEY,
    organization_id INTEGER     NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    user_id         INTEGER     NOT NULL REFERENCES users (id)         ON DELETE CASCADE,
    rol             VARCHAR(40) NOT NULL DEFAULT 'analista',
    invitado_en     TIMESTAMP   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_miembro_organizacion UNIQUE (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_members_org  ON organization_members (organization_id);
CREATE INDEX IF NOT EXISTS ix_members_user ON organization_members (user_id);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                      SERIAL PRIMARY KEY,
    organization_id         INTEGER     NOT NULL UNIQUE
                                        REFERENCES organizations (id) ON DELETE CASCADE,
    plan                    VARCHAR(40) NOT NULL DEFAULT 'gratuito',
    estado                  VARCHAR(40) NOT NULL DEFAULT 'activa',
    stripe_customer_id      VARCHAR(120),
    stripe_subscription_id  VARCHAR(120),
    periodo_inicio          DATE,
    periodo_fin             DATE,
    archivos_usados_mes     INTEGER     NOT NULL DEFAULT 0,
    mes_referencia          VARCHAR(7),
    actualizada_en          TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Archivos e importaciones
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS uploaded_files (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER      NOT NULL REFERENCES users (id)         ON DELETE CASCADE,
    organization_id   INTEGER      NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    nombre_original   VARCHAR(255) NOT NULL,
    nombre_almacenado VARCHAR(255) NOT NULL,
    ruta              VARCHAR(1000) NOT NULL,
    backend           VARCHAR(20)  NOT NULL DEFAULT 'local',
    extension         VARCHAR(10)  NOT NULL,
    tamano_bytes      BIGINT       NOT NULL DEFAULT 0,
    -- SHA-256 del contenido: avisa si se sube dos veces el mismo archivo.
    hash_contenido    VARCHAR(64),
    filas             INTEGER      NOT NULL DEFAULT 0,
    columnas          INTEGER      NOT NULL DEFAULT 0,
    subido_en         TIMESTAMP    NOT NULL DEFAULT NOW(),
    eliminado         BOOLEAN      NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_archivos_user       ON uploaded_files (user_id);
CREATE INDEX IF NOT EXISTS ix_archivos_org        ON uploaded_files (organization_id);
CREATE INDEX IF NOT EXISTS ix_archivos_hash       ON uploaded_files (hash_contenido);
CREATE INDEX IF NOT EXISTS ix_archivos_org_fecha  ON uploaded_files (organization_id, subido_en);

CREATE TABLE IF NOT EXISTS imports (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER     NOT NULL REFERENCES users (id)          ON DELETE CASCADE,
    organization_id   INTEGER     NOT NULL REFERENCES organizations (id)  ON DELETE CASCADE,
    uploaded_file_id  INTEGER     REFERENCES uploaded_files (id)          ON DELETE SET NULL,
    estado            VARCHAR(30) NOT NULL DEFAULT 'completada',
    filas_leidas      INTEGER     NOT NULL DEFAULT 0,
    filas_validas     INTEGER     NOT NULL DEFAULT 0,
    filas_descartadas INTEGER     NOT NULL DEFAULT 0,
    duplicados        INTEGER     NOT NULL DEFAULT 0,
    periodo_inicio    DATE,
    periodo_fin       DATE,
    mensaje           TEXT,
    iniciada_en       TIMESTAMP   NOT NULL DEFAULT NOW(),
    terminada_en      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_imports_user      ON imports (user_id);
CREATE INDEX IF NOT EXISTS ix_imports_org       ON imports (organization_id);
CREATE INDEX IF NOT EXISTS ix_imports_org_fecha ON imports (organization_id, iniciada_en);

-- Tabla principal: una fila por línea del reporte de transacciones de Amazon.
CREATE TABLE IF NOT EXISTS transactions (
    id                  BIGSERIAL PRIMARY KEY,

    -- Aislamiento por inquilino y trazabilidad del origen.
    user_id             INTEGER   NOT NULL REFERENCES users (id)          ON DELETE CASCADE,
    organization_id     INTEGER   NOT NULL REFERENCES organizations (id)  ON DELETE CASCADE,
    import_id           INTEGER   REFERENCES imports (id)                 ON DELETE CASCADE,
    uploaded_file_id    INTEGER   REFERENCES uploaded_files (id)          ON DELETE SET NULL,
    importada_en        TIMESTAMP NOT NULL DEFAULT NOW(),
    -- SHA-1 de (pedido, tipo, sku, fecha, total, liquidación): evita reinsertar.
    row_hash            VARCHAR(64),

    -- Campos del reporte de Amazon.
    fecha_hora                          TIMESTAMP,
    id_liquidacion                      VARCHAR(60),
    tipo                                VARCHAR(60),
    id_pedido                           VARCHAR(60),
    sku                                 VARCHAR(120),
    descripcion                         TEXT,
    cantidad                            DOUBLE PRECISION NOT NULL DEFAULT 0,
    marketplace                         VARCHAR(80),
    cumplimiento                        VARCHAR(60),
    ciudad                              VARCHAR(160),
    estado                              VARCHAR(120),
    codigo_postal                       VARCHAR(20),
    modelo_impuestos                    VARCHAR(80),

    ventas_productos                    DOUBLE PRECISION NOT NULL DEFAULT 0,
    impuesto_ventas_productos           DOUBLE PRECISION NOT NULL DEFAULT 0,
    creditos_envio                      DOUBLE PRECISION NOT NULL DEFAULT 0,
    impuesto_envio                      DOUBLE PRECISION NOT NULL DEFAULT 0,
    creditos_envoltorio                 DOUBLE PRECISION NOT NULL DEFAULT 0,
    impuesto_envoltorio                 DOUBLE PRECISION NOT NULL DEFAULT 0,
    tarifa_reglamentaria                DOUBLE PRECISION NOT NULL DEFAULT 0,
    impuesto_tarifa_reglamentaria       DOUBLE PRECISION NOT NULL DEFAULT 0,
    descuentos_promocionales            DOUBLE PRECISION NOT NULL DEFAULT 0,
    impuesto_descuentos_promocionales   DOUBLE PRECISION NOT NULL DEFAULT 0,
    retenciones_plataforma              DOUBLE PRECISION NOT NULL DEFAULT 0,
    tarifas_venta                       DOUBLE PRECISION NOT NULL DEFAULT 0,
    tarifas_fba                         DOUBLE PRECISION NOT NULL DEFAULT 0,
    tarifas_otras                       DOUBLE PRECISION NOT NULL DEFAULT 0,
    otro                                DOUBLE PRECISION NOT NULL DEFAULT 0,
    total                               DOUBLE PRECISION NOT NULL DEFAULT 0,

    estado_transaccion  VARCHAR(60),
    fecha_liberacion    TIMESTAMP,

    CONSTRAINT uq_tx_org_hash UNIQUE (organization_id, row_hash)
);

-- Índices de consulta. El primer campo es siempre organization_id porque toda
-- consulta de la aplicación filtra por inquilino antes que por cualquier otra cosa.
CREATE INDEX IF NOT EXISTS ix_tx_user            ON transactions (user_id);
CREATE INDEX IF NOT EXISTS ix_tx_org             ON transactions (organization_id);
CREATE INDEX IF NOT EXISTS ix_tx_import          ON transactions (import_id);
CREATE INDEX IF NOT EXISTS ix_tx_fecha           ON transactions (fecha_hora);
CREATE INDEX IF NOT EXISTS ix_tx_hash            ON transactions (row_hash);
CREATE INDEX IF NOT EXISTS ix_tx_org_fecha       ON transactions (organization_id, fecha_hora);
CREATE INDEX IF NOT EXISTS ix_tx_org_sku         ON transactions (organization_id, sku);
CREATE INDEX IF NOT EXISTS ix_tx_org_pedido      ON transactions (organization_id, id_pedido);
CREATE INDEX IF NOT EXISTS ix_tx_org_liquidacion ON transactions (organization_id, id_liquidacion);
CREATE INDEX IF NOT EXISTS ix_tx_org_tipo        ON transactions (organization_id, tipo);

-- -----------------------------------------------------------------------------
-- Productos y costos
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    organization_id INTEGER      NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    sku             VARCHAR(120) NOT NULL,
    descripcion     TEXT,
    marca           VARCHAR(120),
    categoria       VARCHAR(120),
    activo          BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_producto_org_sku UNIQUE (organization_id, sku)
);
CREATE INDEX IF NOT EXISTS ix_products_org ON products (organization_id);
CREATE INDEX IF NOT EXISTS ix_products_sku ON products (sku);

CREATE TABLE IF NOT EXISTS product_costs (
    id                        SERIAL PRIMARY KEY,
    organization_id           INTEGER      NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    user_id                   INTEGER      REFERENCES users (id) ON DELETE SET NULL,
    sku                       VARCHAR(120) NOT NULL,
    costo_unitario            DOUBLE PRECISION NOT NULL DEFAULT 0,
    costo_logistico_adicional DOUBLE PRECISION NOT NULL DEFAULT 0,
    gasto_publicitario        DOUBLE PRECISION NOT NULL DEFAULT 0,
    marca                     VARCHAR(120),
    categoria                 VARCHAR(120),
    actualizado_en            TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_costo_org_sku UNIQUE (organization_id, sku)
);
CREATE INDEX IF NOT EXISTS ix_costos_org ON product_costs (organization_id);
CREATE INDEX IF NOT EXISTS ix_costos_sku ON product_costs (sku);

-- -----------------------------------------------------------------------------
-- Configuración del usuario, alertas y bitácoras
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dashboards (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER      NOT NULL REFERENCES users (id)         ON DELETE CASCADE,
    organization_id   INTEGER      NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    nombre            VARCHAR(160) NOT NULL,
    configuracion     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    es_predeterminado BOOLEAN      NOT NULL DEFAULT FALSE,
    creado_en         TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_dashboards_user ON dashboards (user_id);
CREATE INDEX IF NOT EXISTS ix_dashboards_org  ON dashboards (organization_id);

CREATE TABLE IF NOT EXISTS saved_filters (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER      NOT NULL REFERENCES users (id)         ON DELETE CASCADE,
    organization_id INTEGER      NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    nombre          VARCHAR(160) NOT NULL,
    filtros         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    creado_en       TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_filtros_user ON saved_filters (user_id);
CREATE INDEX IF NOT EXISTS ix_filtros_org  ON saved_filters (organization_id);

CREATE TABLE IF NOT EXISTS alerts (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER      NOT NULL REFERENCES users (id)         ON DELETE CASCADE,
    organization_id INTEGER      NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    import_id       INTEGER      REFERENCES imports (id) ON DELETE CASCADE,
    severidad       VARCHAR(20)  NOT NULL DEFAULT 'informativo',
    categoria       VARCHAR(60)  NOT NULL DEFAULT 'General',
    titulo          VARCHAR(255) NOT NULL,
    mensaje         TEXT         NOT NULL,
    recomendacion   TEXT,
    atendida        BOOLEAN      NOT NULL DEFAULT FALSE,
    creada_en       TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_alertas_user      ON alerts (user_id);
CREATE INDEX IF NOT EXISTS ix_alertas_org       ON alerts (organization_id);
CREATE INDEX IF NOT EXISTS ix_alertas_org_fecha ON alerts (organization_id, creada_en);

CREATE TABLE IF NOT EXISTS export_history (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER      NOT NULL REFERENCES users (id)         ON DELETE CASCADE,
    organization_id INTEGER      NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    tipo_reporte    VARCHAR(80)  NOT NULL,
    formato         VARCHAR(20)  NOT NULL DEFAULT 'xlsx',
    nombre_archivo  VARCHAR(255) NOT NULL,
    filas           INTEGER      NOT NULL DEFAULT 0,
    generado_en     TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_exportaciones_user ON export_history (user_id);
CREATE INDEX IF NOT EXISTS ix_exportaciones_org  ON export_history (organization_id);

-- Bitácora de acciones. No almacena contraseñas ni contenido de los archivos.
CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER      REFERENCES users (id)         ON DELETE SET NULL,
    organization_id INTEGER      REFERENCES organizations (id) ON DELETE SET NULL,
    accion          VARCHAR(120) NOT NULL,
    detalle         JSONB        DEFAULT '{}'::jsonb,
    creado_en       TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_auditoria_user  ON audit_logs (user_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_org   ON audit_logs (organization_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_fecha ON audit_logs (creado_en);

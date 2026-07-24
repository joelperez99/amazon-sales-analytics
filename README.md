# Amazon Sales Analytics

Aplicación SaaS en Python y Streamlit para analizar los **reportes de transacciones
de Amazon Seller Central**. Sube el CSV o el Excel que descargas de Seller Central
y obtienes un tablero de ventas, comisiones, reembolsos, rentabilidad y
distribución geográfica, con exportación a Excel y multiusuario.

Interfaz completamente en español, con formato monetario de México (`$1,234.56 MXN`).

---

## Índice

1. [Qué resuelve](#qué-resuelve)
2. [Instalación local](#instalación-local)
3. [Configuración](#configuración)
4. [Base de datos](#base-de-datos)
5. [Uso](#uso)
6. [Arquitectura](#arquitectura)
7. [Modelo de datos](#modelo-de-datos)
8. [Cómo se calcula cada cifra](#cómo-se-calcula-cada-cifra)
9. [Reglas de negocio](#reglas-de-negocio)
10. [Planes SaaS](#planes-saas)
11. [Pruebas](#pruebas)
12. [Despliegue](#despliegue)
13. [Seguridad](#seguridad)
14. [Rendimiento](#rendimiento)
15. [Solución de problemas](#solución-de-problemas)

---

## Qué resuelve

El reporte de transacciones de Amazon es una lista plana de miles de renglones
donde se mezclan pedidos, reembolsos, comisiones, tarifas de almacenamiento,
suscripciones y transferencias bancarias. Responder «¿cuánto vendí realmente?» o
«¿cuánto se queda Amazon?» a mano es lento y propenso a error.

Esta aplicación:

- Reconoce el archivo aunque cambien mayúsculas, acentos o espacios en los encabezados.
- Interpreta las fechas en español (`1 jun 2026 12:41:59 a.m. GMT-7`).
- Separa cada tipo de transacción y **nunca cuenta una transferencia como venta**.
- Cuenta los pedidos por `Id. del pedido`, así que un pedido con tres SKU cuenta una vez.
- Concilia el neto por dos caminos independientes y avisa si no cuadran.
- Distingue el **neto después de tarifas Amazon** de la **utilidad real**: la segunda
  solo aparece cuando capturas el costo de tus productos.

---

## Instalación local

Requisitos: **Python 3.11 o superior**.

```bash
# 1. Clona o descarga el proyecto y entra a la carpeta
cd amazon_sales_saas

# 2. Crea un entorno virtual
python -m venv .venv

#    Windows (PowerShell)
.venv\Scripts\Activate.ps1
#    macOS / Linux
source .venv/bin/activate

# 3. Instala las dependencias
pip install -r requirements.txt

# 4. Copia la configuración de ejemplo
cp .env.example .env          # Windows: copy .env.example .env

# 5. Genera datos simulados (opcional pero recomendado la primera vez)
python scripts/generar_datos_demo.py

# 6. Arranca la aplicación
streamlit run app.py
```

Abre <http://localhost:8501>.

Con la configuración por omisión no necesitas instalar nada más: la aplicación
crea una base **SQLite** en `data/amazon_analytics.db` en el primer arranque.

### Usuario de demostración

Con `DEMO_MODE=true` (valor por omisión) se crea automáticamente:

| Campo      | Valor                       |
|------------|-----------------------------|
| Correo     | `demo@amazonanalytics.mx`   |
| Contraseña | `Demo1234!`                 |
| Plan       | Profesional                 |

En la pantalla de acceso hay un botón **«Entrar con la cuenta de demostración»**.
Dentro, el botón **«Probar con datos de ejemplo»** carga dos meses de
transacciones simuladas sin necesidad de subir archivos.

> Cambia `DEMO_EMAIL` y `DEMO_PASSWORD`, o pon `DEMO_MODE=false`, antes de
> exponer la aplicación en internet.

### Modo sin autenticación (solo desarrollo)

Para trabajar sin pantalla de acceso, en tu `.env`:

```env
AUTH_ENABLED=false
```

---

## Configuración

Todo se controla desde el archivo `.env`. Las variables principales:

| Variable | Por omisión | Para qué sirve |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/amazon_analytics.db` | Cadena de conexión |
| `AUTH_ENABLED` | `true` | Activa el registro e inicio de sesión |
| `DEMO_MODE` | `true` | Crea el usuario demo y el botón de datos de ejemplo |
| `SESSION_SECRET` | — | **Cámbialo** por una cadena larga y aleatoria |
| `SESSION_TIMEOUT_MINUTES` | `480` | Minutos de inactividad antes de cerrar sesión |
| `STORAGE_BACKEND` | `local` | `local`, `s3` o `supabase` |
| `STORAGE_LOCAL_PATH` | `./data/uploads` | Dónde se guardan los archivos subidos |
| `FILE_RETENTION_DAYS` | `365` | Retención de archivos (`0` = indefinida) |
| `MAX_FILE_SIZE_MB` | `200` | Tamaño máximo por archivo |
| `ALLOWED_EXTENSIONS` | `.csv,.xlsx,.xls` | Extensiones aceptadas |
| `CSV_CHUNK_SIZE` | `100000` | Filas por bloque al leer CSV grandes |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` o `ERROR` |

Umbrales que disparan los hallazgos automáticos:

| Variable | Por omisión | Alerta cuando… |
|---|---|---|
| `ALERTA_CAIDA_VENTAS_PCT` | `15` | las ventas caen más de ese % |
| `ALERTA_TASA_REEMBOLSO_PCT` | `5` | los reembolsos superan ese % de las ventas |
| `ALERTA_PCT_CARGOS_PCT` | `35` | los cargos de Amazon superan ese % |
| `ALERTA_CONCENTRACION_SKU_PCT` | `40` | un SKU concentra más de ese % de la venta |
| `ALERTA_DIAS_SIN_VENTA` | `7` | un SKU lleva esos días sin venderse |
| `ALERTA_TOLERANCIA_CONCILIACION` | `1.0` | el neto y su reconstrucción difieren en más de esos pesos |

**Nunca escribas secretos en el código ni subas tu `.env` al repositorio**
(ya está en `.gitignore`).

---

## Base de datos

### SQLite (desarrollo)

Es la opción por omisión. No requiere instalación:

```env
DATABASE_URL=sqlite:///./data/amazon_analytics.db
```

La aplicación crea el archivo y las tablas en el primer arranque, activa las
llaves foráneas y el modo WAL.

### PostgreSQL (producción)

1. Crea la base y el usuario:

   ```sql
   CREATE USER amazon WITH PASSWORD 'una-contraseña-larga';
   CREATE DATABASE amazon_analytics OWNER amazon ENCODING 'UTF8';
   GRANT ALL PRIVILEGES ON DATABASE amazon_analytics TO amazon;
   ```

2. Apunta la aplicación a esa base:

   ```env
   DATABASE_URL=postgresql+psycopg2://amazon:una-contraseña-larga@localhost:5432/amazon_analytics
   ```

3. Las tablas se crean solas al arrancar. Si prefieres provisionarlas antes:

   ```bash
   psql -U amazon -d amazon_analytics -f database/migrations/001_esquema_inicial.sql
   ```

El script es idempotente: puedes ejecutarlo varias veces sin efectos secundarios.

Verifica la conexión desde **Configuración → Sistema**.

---

## Uso

### 1. Obtener el reporte en Seller Central

1. Entra a Seller Central con tu cuenta de vendedor.
2. **Informes → Pagos → Todos los estados de cuenta**.
3. Elige **Informe de transacciones personalizado** y el rango de fechas.
4. Descarga el archivo (CSV).

### 2. Cargar

En **Cargar archivos** arrastra uno o varios reportes. La aplicación:

- Detecta la codificación (UTF-8, UTF-8 con BOM, CP1252, Latin-1).
- Detecta el separador (coma, punto y coma, tabulador o barra vertical).
- Localiza la fila de encabezados aunque el archivo traiga un preámbulo.
- Traduce los encabezados a sus nombres internos, tolerando mayúsculas, acentos
  y espacios.
- Convierte fechas e importes, y reporta lo que corrigió o descartó.
- Marca los **posibles duplicados** sin borrarlos: tú decides si los excluyes.

Si algún encabezado no se reconoce, el asistente **«Relacionar columnas
manualmente»** te deja mapearlo a mano.

### 3. Analizar

Las páginas del tablero:

| Página | Qué muestra |
|---|---|
| **Inicio** | Bienvenida, últimos archivos, último periodo, accesos rápidos |
| **Cargar archivos** | Subida, validación, vista previa, duplicados |
| **Resumen ejecutivo** | 10 tarjetas con variación, cascada, comparación, hallazgos |
| **Ventas** | Evolución por día/semana/mes, ventas por hora, detalle de pedidos |
| **Productos** | Top SKU, Pareto 80/20, dispersión volumen–margen, tabla detallada |
| **Tarifas** | Composición de cargos, evolución, cargos por producto |
| **Reembolsos** | Devoluciones por día, SKU, estado y ciudad |
| **Geografía** | Mapa de México, rankings por estado y ciudad |
| **Liquidaciones** | Conciliación de cada depósito de Amazon |
| **Costos y rentabilidad** | Utilidad real, margen, ROI, ACOS y TACOS |
| **Exportar** | Reporte completo de 12+ hojas y descargas individuales |
| **Configuración** | Cuenta, plan, datos, equipo, diagnóstico |

Los filtros de la barra lateral (fechas, marketplace, tipo, SKU, producto,
cumplimiento, estado, ciudad, liquidación, estado de la transacción) afectan a
**todas** las tarjetas, gráficas y tablas de todas las páginas.

---

## Arquitectura

```
amazon_sales_saas/
│
├── app.py                      Punto de entrada: tema, acceso, navegación
├── pages/                      Las 12 páginas del tablero
│   ├── 01_inicio.py
│   ├── 02_cargar_archivos.py
│   ├── 03_resumen.py
│   ├── 04_ventas.py
│   ├── 05_productos.py
│   ├── 06_tarifas.py
│   ├── 07_reembolsos.py
│   ├── 08_geografia.py
│   ├── 09_liquidaciones.py
│   ├── 10_rentabilidad.py
│   ├── 11_exportar.py
│   └── 12_configuracion.py
│
├── components/                 Piezas de interfaz reutilizables
│   ├── filters.py              Barra lateral y aplicación de filtros
│   ├── metric_cards.py         Tarjetas de KPI con variación y tooltip
│   ├── charts.py               Todas las gráficas de Plotly
│   ├── tables.py               Tablas con búsqueda, columnas y paginación
│   ├── alerts.py               Presentación de hallazgos y mensajes
│   └── layout.py               Andamiaje común de las páginas
│
├── services/                   Lógica de negocio (sin dependencias de la interfaz)
│   ├── amazon_parser.py        Lectura, encoding, delimitador, encabezados
│   ├── data_cleaner.py         Tipos, fechas, importes, normalización
│   ├── metrics_service.py      TODAS las fórmulas del tablero
│   ├── comparison_service.py   Periodo anterior y variaciones
│   ├── profitability_service.py Costos, utilidad, ROI, ACOS, TACOS
│   ├── alerts_service.py       Reglas de los hallazgos automáticos
│   ├── export_service.py       Excel y CSV con formato
│   ├── file_service.py         Orquestación de la carga y estado de sesión
│   ├── auth_service.py         Contraseñas, sesión, planes y permisos
│   └── storage_service.py      Almacenamiento local, S3 o Supabase
│
├── database/
│   ├── connection.py           Motor y sesiones de SQLAlchemy
│   ├── models.py               Las 14 tablas del modelo
│   ├── repositories.py         Todo el acceso a datos, filtrado por inquilino
│   └── migrations/
│       └── 001_esquema_inicial.sql
│
├── utils/
│   ├── config.py               Configuración validada con Pydantic
│   ├── constants.py            Encabezados, tipos, catálogos, paleta, métricas
│   ├── formatting.py           Moneda MXN, porcentajes, división segura
│   ├── date_parser.py          Fechas en español, vectorizado
│   ├── validations.py          Validación de archivos, columnas y duplicados
│   └── logger.py               Registro con enmascarado de secretos
│
├── tests/                      188 pruebas unitarias
│   ├── conftest.py             Datos simulados
│   ├── test_parser.py
│   ├── test_cleaner.py
│   ├── test_metrics.py
│   └── test_exports.py
│
├── scripts/
│   └── generar_datos_demo.py   Generador de datos simulados
│
├── .streamlit/config.toml
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── README.md
```

**Regla de dependencias:** `pages/` usa `components/` y `services/`;
`services/` usa `database/` y `utils/`; `utils/` no depende de nada del proyecto.
Ningún módulo de `services/` importa Streamlit salvo los que gestionan sesión
(`file_service`, `auth_service`), lo que permite probar toda la lógica sin
levantar la interfaz.

---

## Modelo de datos

| Tabla | Contiene |
|---|---|
| `organizations` | La cuenta cliente y su plan |
| `users` | Quién inicia sesión; guarda solo el hash de la contraseña |
| `organization_members` | Relación usuario–organización con su rol |
| `subscriptions` | Plan contratado, listo para Stripe |
| `uploaded_files` | Cada archivo subido, con su SHA-256 |
| `imports` | Cada ejecución de procesamiento |
| `transactions` | Una fila por línea del reporte de Amazon |
| `products` | Catálogo derivado de los SKU vistos |
| `product_costs` | Costo, costo logístico y publicidad por SKU |
| `dashboards` | Tableros guardados |
| `saved_filters` | Combinaciones de filtros guardadas |
| `alerts` | Histórico de hallazgos |
| `export_history` | Cada descarga generada |
| `audit_logs` | Bitácora de acciones |

Toda fila de negocio lleva `organization_id` y `user_id`, y **todos** los
repositorios filtran por ellos. Ese es el mecanismo de aislamiento: desde la
interfaz no hay forma de leer datos de otra cuenta.

Índices sobre `fecha_hora`, `id_pedido`, `sku`, `id_liquidacion`, `tipo`,
`user_id` y `organization_id`; los compuestos empiezan siempre por
`organization_id` porque es el primer filtro de cualquier consulta.

La restricción única `(organization_id, row_hash)` en `transactions` hace que
volver a subir el mismo periodo no duplique registros en el histórico.

---

## Cómo se calcula cada cifra

La lista completa está en **Exportar → Referencia** y en la hoja
«Diccionario de métricas» del reporte de Excel. Las principales:

### Ventas

| Métrica | Fórmula |
|---|---|
| Ventas brutas | Σ `ventas de productos` en filas de tipo **Pedido** |
| Impuestos cobrados | Σ impuestos de ventas, envío, envoltorio y tarifa reglamentaria (Pedido) |
| Ventas con impuestos | Ventas brutas + Impuestos cobrados |
| Pedidos únicos | `nunique(Id. del pedido)` en filas de tipo **Pedido** |
| Unidades vendidas | Σ `cantidad` en filas de tipo **Pedido** |
| Ticket promedio | Ventas brutas ÷ Pedidos únicos |
| Precio promedio por unidad | Ventas brutas ÷ Unidades vendidas |

### Tarifas

| Métrica | Fórmula |
|---|---|
| Tarifas de venta | \|Σ `tarifas de venta`\| en todo salvo transferencias |
| Tarifas FBA | \|Σ `tarifas fba`\| en todo salvo transferencias |
| Retenciones | \|Σ `impuesto de retenciones en la plataforma`\| |
| Otros cargos | \|Σ de los valores **negativos** de `otro`\| |
| Total de cargos Amazon | \|Σ (venta + FBA + otras + reglamentaria)\| + Otros cargos + cargos residuales |
| % de cargos | Total de cargos ÷ Ventas brutas |
| Tarifa por pedido | Total de cargos ÷ Pedidos únicos |

Las **retenciones no entran** en el total de cargos: son impuesto que Amazon
entera a la autoridad, no una tarifa suya. Se reportan aparte.

Los «cargos residuales» recuperan las tarifas que un reporte registró solo en la
columna `total`, sin desglose. Se suman **únicamente** cuando todas las columnas
de detalle de esa fila están en cero, de modo que no se cuentan dos veces.

### Reembolsos

| Métrica | Fórmula |
|---|---|
| Importe reembolsado | \|Σ `total`\| en filas de tipo **Reembolso** |
| Unidades reembolsadas | \|Σ `cantidad`\| en filas de tipo **Reembolso** |
| Tasa de reembolso | Importe reembolsado ÷ Ventas brutas |

### Resultado

| Métrica | Fórmula |
|---|---|
| Neto después de tarifas | Σ `total` de todas las transacciones **excepto transferencias** |
| Neto reconstruido | Σ de todos los componentes monetarios (sin `total`) |
| Diferencia de conciliación | Neto − Neto reconstruido |
| Margen neto Amazon | Neto ÷ Ventas brutas |

Si la diferencia de conciliación supera `ALERTA_TOLERANCIA_CONCILIACION`, el
tablero muestra una alerta: normalmente significa que falta una columna monetaria
en el archivo o que llegó con un formato inesperado.

### Rentabilidad (requiere costos capturados)

| Métrica | Fórmula |
|---|---|
| Costo de mercancía vendida | Σ (unidades **netas** × (costo unitario + costo logístico)) |
| Utilidad antes de publicidad | Neto después de tarifas − Costo de mercancía |
| Utilidad después de publicidad | Utilidad antes de publicidad − Gasto publicitario |
| Margen bruto | (Ventas − Costo de mercancía) ÷ Ventas |
| Margen de contribución | Utilidad después de publicidad ÷ Ventas |
| ROI | Utilidad después de publicidad ÷ Costo de mercancía |
| ACOS | Gasto publicitario ÷ Ventas de los SKU con costo |
| TACOS | Gasto publicitario ÷ Ventas totales |

Las **unidades netas** descuentan las devoluciones: la pieza que regresa vuelve
al inventario, así que su costo no pertenece al periodo.

---

## Reglas de negocio

Estas decisiones están implementadas y cubiertas por pruebas:

1. **Un pedido con varias líneas cuenta una vez.** Los pedidos se cuentan con
   `nunique(Id. del pedido)`, nunca con el número de filas.
2. **Las unidades vienen de `cantidad`**, no del conteo de renglones.
3. **Solo las filas de tipo `Pedido` generan ventas y unidades.** Un reembolso no
   resta de «ventas brutas»: se reporta por separado y sí afecta al neto.
4. **Las transferencias se excluyen de todos los importes.** En el reporte
   aparecen como `Trasferir` (con la errata original de Amazon) o `Transferir`, y
   representan el retiro a tu banco. Ese dinero ya se contabilizó cuando entró
   por la venta: sumarlo otra vez duplicaría la salida.
5. **Los cargos conservan su signo negativo durante el cálculo.** El valor
   absoluto se usa solo para presentar en tarjetas y gráficas.
6. **La comisión que devuelve un reembolso queda netada de forma natural**, porque
   llega con signo positivo en `tarifas de venta`.
7. **Toda división pasa por `division_segura`.** Un denominador en cero produce
   «N/D», nunca una excepción ni un infinito.
8. **No se calculan variaciones porcentuales sobre base cero.** Si el periodo
   anterior vale cero, la tarjeta muestra «N/D».
9. **Se redondea solo para presentar.** Los cálculos internos trabajan con la
   precisión completa de `float64`.
10. **Sin costo de producto no se dice «utilidad».** El término correcto y el que
    usa la aplicación es «neto después de tarifas Amazon».
11. **Los duplicados se marcan, no se borran.** Se detectan con la llave
    compuesta `(Id. del pedido, tipo, SKU, fecha/hora, total, Id. de liquidación)`
    y la decisión de excluirlos es del usuario.

---

## Planes SaaS

| | Gratuito | Profesional | Empresarial |
|---|---|---|---|
| Precio mensual | $0 | $499 MXN | $1,499 MXN |
| Archivos por mes | 2 | 100 | Ilimitados |
| Filas por archivo | 5,000 | 500,000 | Sin límite |
| Historial | 30 días | 730 días | Sin límite |
| Comparación de periodos | — | Sí | Sí |
| Costos y rentabilidad | — | Sí | Sí |
| Exportación avanzada | — | Sí | Sí |
| Alertas | — | Sí | Sí |
| Varios usuarios y roles | — | — | Sí |
| API y branding | — | — | Sí |

Roles disponibles: **propietario**, **administrador**, **analista** y **lector**,
cada uno con su conjunto de permisos (`ver`, `cargar`, `exportar`, `configurar`,
`administrar_usuarios`, `facturar`).

La arquitectura está preparada para **Stripe**: la tabla `subscriptions` guarda
`stripe_customer_id` y `stripe_subscription_id`. Con `BILLING_ENABLED=false` el
cambio de plan funciona en modo de pruebas, sin cobro.

---

## Pruebas

```bash
# Todas las pruebas
pytest

# Con reporte de cobertura
pytest --cov=services --cov=utils --cov-report=term-missing

# Un archivo o una clase
pytest tests/test_metrics.py -v
pytest tests/test_metrics.py::TestNeto -v
```

Las 188 pruebas cubren: lectura de CSV y Excel, detección de codificación y
delimitador, mapeo de encabezados, fechas en español (incluidos los casos límite
de `12 a.m.` y `12 p.m.`), conversión de importes en formato mexicano y europeo,
cálculo de ventas, conteo de pedidos únicos con líneas múltiples, unidades,
tarifas, reembolsos, neto, conciliación, comparación entre periodos, detección de
duplicados, archivos con columnas faltantes, archivos vacíos, valores nulos,
divisiones entre cero, rentabilidad, hallazgos, exportación a Excel y saneamiento
de nombres de archivo.

Los datos simulados viven en `tests/conftest.py` y sus valores esperados están
calculados a mano y documentados en el encabezado de `test_metrics.py`.

---

## Despliegue

### Docker Compose (recomendado)

```bash
cp .env.example .env
# Edita .env: SESSION_SECRET, POSTGRES_PASSWORD, DEMO_MODE=false, APP_ENV=production

docker compose up -d --build
docker compose logs -f app
```

La aplicación queda en <http://localhost:8501> y PostgreSQL solo escucha en
`127.0.0.1:5432`. Los archivos subidos y los registros viven en volúmenes con
nombre, así que sobreviven al reinicio de los contenedores.

```bash
docker compose down       # detiene, conserva los datos
docker compose down -v    # detiene y BORRA los volúmenes
```

### Docker sin Compose

```bash
docker build -t amazon-analytics .
docker run -d -p 8501:8501 --env-file .env \
  -v "$(pwd)/data:/app/data" \
  --name amazon-analytics amazon-analytics
```

### Streamlit Community Cloud

1. Sube el repositorio a GitHub (sin el `.env`).
2. Crea la aplicación apuntando a `app.py`.
3. Copia el contenido de tu `.env` en **Settings → Secrets**.
4. Usa una base gestionada (Supabase, Neon o Railway) en `DATABASE_URL`; el disco
   de Community Cloud es efímero y SQLite se perdería en cada reinicio.

### Detrás de un proxy inverso

Ejemplo con Nginx y HTTPS:

```nginx
server {
    listen 443 ssl http2;
    server_name analytics.tudominio.mx;

    ssl_certificate     /etc/letsencrypt/live/analytics.tudominio.mx/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/analytics.tudominio.mx/privkey.pem;

    client_max_body_size 200M;   # debe coincidir con MAX_FILE_SIZE_MB

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;   # WebSocket de Streamlit
        proxy_set_header Connection "upgrade";
        proxy_set_header Host       $host;
        proxy_set_header X-Real-IP  $remote_addr;
        proxy_read_timeout 300s;
    }
}
```

### Lista de verificación antes de producción

- [ ] `APP_ENV=production`
- [ ] `SESSION_SECRET` cambiado por una cadena larga y aleatoria
- [ ] `DEMO_MODE=false`
- [ ] `DATABASE_URL` apuntando a PostgreSQL, con una contraseña fuerte
- [ ] `FILE_RETENTION_DAYS` acorde a tu política de datos
- [ ] HTTPS habilitado
- [ ] Respaldo programado de la base de datos
- [ ] El `.env` **no** está en el repositorio

---

## Seguridad

- **Contraseñas** cifradas con bcrypt (12 rondas); si bcrypt no está disponible,
  con PBKDF2-HMAC-SHA256 a 260,000 iteraciones. La contraseña en claro nunca se
  guarda ni se escribe en los registros.
- **Sesiones** con caducidad configurable; cada interacción renueva la ventana.
- **Aislamiento por inquilino**: cada repositorio filtra por `organization_id`.
  Un usuario solo ve sus archivos, sus transacciones, sus costos y sus reportes.
- **Sin inyección SQL**: todo el acceso a datos pasa por SQLAlchemy con consultas
  parametrizadas. No se concatena texto SQL en ningún punto del proyecto.
- **Validación de archivos**: extensión, tamaño y contenido antes de procesar.
- **Saneamiento de nombres**: se eliminan rutas (`../`, `C:\`), acentos y
  caracteres especiales. El almacenamiento local verifica además que la ruta
  resultante quede dentro del directorio permitido.
- **Errores sin fuga de información**: la interfaz muestra un identificador corto
  (por ejemplo `A3F91B2C`) y la traza completa va solo al registro del servidor.
  El registro enmascara contraseñas, tokens y cadenas de conexión.
- **Eliminación segura** de archivos y política de retención configurable.
- **Bitácora de auditoría** de las acciones relevantes, sin contenido sensible.
- **Secretos solo por variables de entorno**. No hay ninguna credencial en el código.

---

## Rendimiento

- **Todo el procesamiento es vectorizado**: no hay ni un `iterrows()` en el
  proyecto. Las fechas en español se convierten extrayendo los componentes con
  una expresión regular sobre la columna completa y construyendo el `datetime` de
  una sola vez.
- **Un solo `groupby` por tabla**: los resúmenes por SKU, estado, ciudad y
  liquidación calculan todas sus columnas en una pasada.
- **Caché**: `st.cache_resource` para el motor de base de datos y el arranque,
  `st.cache_data` para el GeoJSON del mapa (24 horas).
- **Lectura por bloques** para CSV grandes (`CSV_CHUNK_SIZE`).
- **Tipos optimizados**: las columnas de baja cardinalidad se convierten a
  `category` cuando conviene (menos del 50% de valores distintos).
- **Inserciones por lotes** de 5,000 filas, con verificación previa de hashes
  existentes para no reinsertar.
- **Indicadores de progreso** y mensajes de estado durante la carga.

---

## Solución de problemas

**«Faltan columnas obligatorias»**
El archivo no trae `fecha/hora`, `tipo` o `total`. Verifica que sea el *informe
de transacciones* y no el resumen de pagos. Si tus encabezados son distintos, usa
el asistente **«Relacionar columnas manualmente»** en la página de carga.

**Las fechas salen vacías**
El formato no coincide con ninguno de los reconocidos. Revisa un par de valores
en la vista previa: la aplicación acepta `1 jun 2026 12:41:59 a.m. GMT-7`, ISO
(`2026-06-01`) y los formatos habituales con día primero.

**La conciliación no cuadra**
La suma de `total` no coincide con la de sus componentes. Casi siempre falta una
columna monetaria en el archivo exportado. Compara el listado de columnas
detectadas con el de la sección «Detalle de la limpieza».

**El mapa de México no aparece**
El contorno geográfico se descarga bajo demanda. Sin conexión saliente, la página
muestra la misma información en barras horizontales; el resto del análisis
geográfico funciona igual.

**«No fue posible conectar con la base de datos»**
Revisa `DATABASE_URL`. Con PostgreSQL, confirma que el servicio esté arriba y que
el usuario tenga permisos. Consulta el detalle en `logs/app.log` usando el
identificador de error que muestra la interfaz.

**El archivo pesa más de lo permitido**
Sube `MAX_FILE_SIZE_MB` en el `.env` **y** `maxUploadSize` en
`.streamlit/config.toml`: ambos deben coincidir.

**Números negativos donde esperabas positivos**
Es lo correcto: en el reporte de Amazon los cargos son negativos. La aplicación
conserva el signo para calcular y muestra la magnitud en las tarjetas. El
«neto» puede ser negativo si en el periodo hubo más cargos y reembolsos que ventas.

---

## Licencia

MIT.

Este proyecto no está afiliado a Amazon. «Amazon» y «Seller Central» son marcas
de Amazon.com, Inc.

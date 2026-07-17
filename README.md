# Conciliador SAP ↔ SUNAT

Concilia el **Registro de Compras (RCE)** que SUNAT recibe de tus proveedores contra lo
efectivamente registrado en **SAP Business One**, y reparte el trabajo pendiente en
**bandejas** por analista.

## Stack

| Capa | Tecnología |
|---|---|
| **Backend** | FastAPI + Uvicorn (Python 3.10+) |
| **Base de datos** | SQLite en modo **WAL** + SQLAlchemy 2 |
| **Frontend** | React 18 + TypeScript + Vite |
| **Autenticación** | SAP Service Layer (SAP es la fuente de identidad) |

## Arranque en desarrollo

Necesitas **dos terminales**.

**1) Backend** (puerto 18450):
```bash
cd conciliador/backend
uvicorn app.main:app --reload --port 18450
```
Documentación interactiva de la API: http://localhost:18450/docs

**2) Frontend** (puerto 18451):
```bash
cd conciliador/frontend
npm install     # solo la primera vez
npm run dev
```
Abre **http://localhost:18451**

> Vite hace *proxy* de `/api` hacia el backend, así que para el navegador todo es el mismo
> origen: no hay líos de CORS ni de cookies.

## Configuración

Copia la plantilla y complétala. **El `.env` nunca se sube a Git.**

```bash
copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # para SECRET_KEY
```

## Multi-empresa

En el login se elige la **empresa** (además de usuario/clave de SAP, que son siempre los
mismos). La empresa elegida determina:

- Contra qué **Company DB** de SAP se valida el login y se leen facturas/proveedores.
- Qué **credenciales de SUNAT** (client_id/secret, usuario y clave SOL) se usan para bajar
  la propuesta RCE.

Cada empresa se define en el `.env` con un prefijo (`EMPRESAS=EMPRESA1,EMPRESA2`, luego
`EMPRESA1_SAP_COMPANY_DB=...`, `EMPRESA2_SAP_COMPANY_DB=...`, etc. — ver `.env.example`).
Una empresa a medio configurar **no tumba la app**: solo falla, con mensaje claro de qué
falta, cuando alguien intenta entrar a ella (`GET /api/empresas` la lista igual, para que
se vea en el selector, pero el login la rechaza con 503 hasta que esté completa).

La caché de propuestas SUNAT y las asignaciones de bandeja están **separadas por empresa**
(`data/propuestas/{CODIGO}/...`, y la tabla `asignaciones` tiene `empresa` en su clave
primaria) — así dos empresas que comparten un proveedor no se pisan aunque el proveedor les
emita comprobantes con el mismo número.

## Autenticación y roles

- Se ingresa con el **usuario y contraseña de SAP Business One** más la **empresa** elegida.
- Las credenciales se validan contra el Service Layer (`/Login`) del Company DB de esa empresa.
  **La contraseña nunca se almacena**: en la sesión solo queda el nombre de usuario.
- **Acceso restringido** a los departamentos de `{EMPRESA}_DEPARTAMENTOS_PERMITIDOS`
  (por defecto 4 = Contabilidad). Quien no pertenezca al área, es rechazado.
- **Rol `manager`** = *Superusuario* de SAP (o figurar en `{EMPRESA}_MANAGERS_EXTRA`).

| Rol | Qué puede hacer |
|---|---|
| **analista** | Ve el cruce y **su propia bandeja**. No ve las bandejas ajenas. |
| **manager** | Además: pestaña **Gestión** con todas las asignaciones, y puede **revocarle** la asignación a cualquiera. |

## Bandeja de trabajo

1. En **Cruce**, filtra por **Solo en SUNAT** (lo pendiente de registrar).
2. Marca los comprobantes y pulsa **Asignar a mi bandeja**.
3. En **Mi bandeja**, márcalos **Registrada** o quítalos.

La asignación **no es exclusiva**: el mismo comprobante puede estar en varias bandejas.
Cada bandeja es **privada** (solo el manager las ve todas).

Toda acción (asignar, liberar, revocar, cambiar estado, login) queda en la tabla **`auditoria`**.

## Cómo se emparejan los comprobantes

Clave idéntica en ambos lados:

```
RUC | tipo_comprobante | SERIE-NÚMERO
```

| Parte | En SAP | En SUNAT |
|---|---|---|
| RUC | `FederalTaxID` del proveedor (solo `Country = PE`) | Columna "Nro Doc Identidad" (tipo 6 = RUC) |
| Tipo | `PurchaseInvoices`=01 · `PurchaseCreditNotes`=07 | Columna "Tipo CP" |
| Serie-Nº | Campo `NumAtCard` | Columnas Serie + Número |

Se normaliza (serie en mayúsculas, número sin ceros a la izquierda). Es el **mismo comprobante
físico**, así que el número debe coincidir. Cuando no coincide, es un **hallazgo real**
(reemisión o error de digitación), no un fallo del cruce.

| Color | Significado |
|---|---|
| 🟢 Verde | En ambos (conciliado) |
| 🟠 Naranja | Solo en SAP |
| 🟡 Amarillo | Solo en SUNAT → **pendiente de registrar** (asignable) |
| 🟣 Morado | En tu bandeja |

## Estructura

```
conciliador/
├── .env                  # secretos reales (NO versionado)
├── .env.example          # plantilla
├── deploy/                # scripts de instalación (servicio Windows + tarea programada)
├── backend/app/
│   ├── config.py         # configuración desde .env
│   ├── db.py             # SQLite + WAL
│   ├── models.py         # sesiones, asignaciones, auditoría
│   ├── auth.py           # login contra SAP + reglas de acceso
│   ├── routers/          # auth · cruce · bandeja
│   └── services/
│       ├── sap.py        # Service Layer
│       ├── sunat.py      # SIRE / propuesta RCE
│       └── conciliacion.py  # motor de emparejamiento
└── frontend/src/
    ├── api.ts            # cliente de la API
    ├── types.ts
    └── components/       # Login · Cruce · Bandeja
```

## Trampas ya resueltas (no las reintroduzcas)

- **SUNAT usa `grant_type=password`**, no `client_credentials`.
- La **descarga del ZIP** de la propuesta exige además `numTicket`, `perTributario`, `codLibro`
  y `codProceso`. El manual no lo dice; sin ellos devuelve **HTTP 500**.
- El **Service Layer no devuelve `@odata.nextLink`** de forma fiable: hay que paginar con
  **`$skip` explícito**, o te quedas con la primera página (nos pasó: 100 proveedores de 4.819).
- SUNAT a veces manda los nombres envueltos en **CDATA de XML** (`![CDATA[...]]`) — se limpian.
- SIRE tiene **rate limit** (HTTP 429): hay reintentos con *backoff* y caché de propuestas.

## Despliegue en producción (Windows)

1. **`.env` real**: copia `.env.example`, completa las credenciales de cada empresa, y pon
   `APP_ENV=production` (activa cookies `Secure` y desactiva `/docs`).
2. **Certificado de SAP**: instala el CA interno del Service Layer y pon `SAP_VERIFY_SSL=true`
   (en desarrollo está en `false` — ignora el certificado, inseguro fuera de ese entorno).
3. **Entorno virtual** del backend:
   ```powershell
   cd backend
   python -m venv .venv
   .venv\Scripts\pip install -r ..\requirements.txt
   ```
4. **Compila el frontend** — el backend lo sirve solo si `frontend/dist` existe:
   ```powershell
   cd frontend
   npm install
   npm run build
   ```
5. **Instala el servicio de Windows** (necesita [NSSM](https://nssm.cc/download)):
   ```powershell
   cd deploy
   .\instalar_servicio_backend.ps1
   Start-Service ConciliadorBackend
   ```
   Con esto un solo proceso sirve la API (`/api/...`) y el frontend compilado en el mismo
   puerto — sin CORS y sobreviviendo reinicios del equipo.
6. **Tarea nocturna** que precalienta la caché de SUNAT (evita que un analista dispare una
   descarga real de SUNAT en horario laboral):
   ```powershell
   cd deploy
   .\instalar_tarea_refrescar.ps1
   ```
7. **HTTPS** si otros usuarios entran desde sus PCs (sin esto, sus claves de SAP viajarían
   en claro) — pon el servicio detrás de un reverse proxy (IIS, Caddy, nginx) con TLS.
8. **Backup** diario de `data/conciliador.db` (contiene sesiones, asignaciones y auditoría).

Scripts de instalación en [`deploy/`](deploy/): leen la ruta del proyecto solos, avisan si
falta el `.venv` o el `.env`, y no dependen de `schtasks` (rompe rutas con espacios) ni de
tareas que se saltan en silencio si el equipo está con batería.

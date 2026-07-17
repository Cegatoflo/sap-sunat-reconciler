"""
Conciliador SAP ↔ SUNAT — API.

Levantar en desarrollo:
    cd conciliador/backend
    uvicorn app.main:app --reload --port 18450

Documentación interactiva: http://localhost:18450/docs
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .empresas import cargar_empresas
from .routers import auth, bandeja, cruce

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("conciliador")

settings = get_settings()

app = FastAPI(
    title="Conciliador SAP ↔ SUNAT",
    description="Conciliación del Registro de Compras (RCE) contra SAP Business One.",
    version="1.0.0",
    docs_url=None if settings.es_produccion else "/docs",   # sin docs públicas en producción
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,          # necesario para la cookie de sesión
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cruce.router)
app.include_router(bandeja.router)


@app.on_event("startup")
def arranque() -> None:
    init_db()
    log.info("Entorno: %s", settings.app_env)
    log.info("SAP: %s", settings.sap_base_url)
    log.info("Verificación TLS de SAP: %s", settings.sap_verify_ssl)

    for cod, emp in cargar_empresas().items():
        faltan = emp.campos_faltantes()
        if faltan:
            log.warning("Empresa %s (%s) INCOMPLETA — falta: %s", cod, emp.nombre, ", ".join(faltan))
        else:
            log.info("Empresa %s (%s) lista — Company DB %s, departamento(s) permitido(s) %s",
                     cod, emp.nombre, emp.sap_company_db, emp.departamentos_permitidos)


@app.get("/health", tags=["infra"])
def health() -> dict:
    return {"ok": True, "env": settings.app_env}


# En producción se sirve el frontend ya compilado (npm run build) detrás del mismo
# proceso: un solo puerto, sin CORS, y un único servicio de Windows que administrar.
# En desarrollo `frontend/dist` no existe (se usa `npm run dev` con proxy de Vite),
# así que este mount se salta solo.
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
    log.info("Sirviendo frontend compilado desde %s", _dist)

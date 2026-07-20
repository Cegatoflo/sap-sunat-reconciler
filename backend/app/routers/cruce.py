from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import usuario_actual
from ..empresas import obtener_empresa
from ..models import Asignacion, Sesion
from ..services.conciliacion import cruzar_rango, periodo_valido

router = APIRouter(prefix="/api", tags=["cruce"])


class FilaOut(BaseModel):
    clave: str
    periodo: str
    estado: int          # 0 en ambos · 1 solo SAP · 2 solo SUNAT
    fecha: str
    ruc: str
    proveedor: str
    tipo: str
    comprobante: str
    moneda: str
    total: float
    docnum_sap: int | None = None


class AsignadoOut(BaseModel):
    usuario: str
    estado: str


class CruceOut(BaseModel):
    desde: str
    hasta: str
    filas: list[FilaOut]
    mi_bandeja: list[str]                        # claves que YO tengo asignadas
    asignaciones: dict[str, list[AsignadoOut]] = {}   # solo manager: quién tiene qué
    cache_horas: dict[str, float | None] = {}    # antigüedad del dato de SUNAT, por periodo
    estados: dict[str, str | None] = {}          # refresco por periodo: actualizando/listo/error/None


@router.get("/cruce", response_model=CruceOut)
def cruce(
    desde: str = Query(pattern=r"^\d{6}$"),
    hasta: str = Query(pattern=r"^\d{6}$"),
    refrescar: bool = Query(
        False,
        description="Fuerza la descarga desde SUNAT aunque la caché esté vigente. "
                    "Úsalo con criterio: SUNAT limita la frecuencia (429).",
    ),
    ses: Sesion = Depends(usuario_actual),
    db: Session = Depends(get_db),
) -> CruceOut:
    if not (periodo_valido(desde) and periodo_valido(hasta)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Periodo inválido (formato yyyymm)")
    if desde > hasta:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "'desde' no puede ser mayor que 'hasta'")

    empresa = obtener_empresa(ses.empresa)
    faltan = empresa.campos_faltantes()
    if faltan:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{empresa.nombre} aún no está completamente configurada (falta: {', '.join(faltan)}).",
        )

    try:
        filas, cache, estados = cruzar_rango(empresa, desde, hasta, forzar=refrescar)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error consultando SAP/SUNAT: {e}") from e

    # Dueño de cada comprobante ya apartado (asignación exclusiva, scopeada a ESTA empresa)
    duenos: dict[str, Asignacion] = {
        a.clave: a for a in db.query(Asignacion).filter(Asignacion.empresa == empresa.codigo).all()
    }
    mias = [k for k, a in duenos.items() if a.usuario == ses.usuario]

    if ses.rol == "manager":
        # El manager lo ve TODO, y además de quién es cada uno.
        visibles = filas
        asignaciones = {
            k: [AsignadoOut(usuario=a.usuario, estado=a.estado)] for k, a in duenos.items()
        }
    else:
        # Al analista NO le aparece lo que otra persona ya apartó: no puede tomarlo
        # ni reprocesarlo. Solo ve lo libre y lo suyo.
        visibles = [
            f for f in filas
            if (d := duenos.get(f.clave)) is None or d.usuario == ses.usuario
        ]
        asignaciones = {}

    return CruceOut(
        desde=desde, hasta=hasta,
        filas=[FilaOut(**asdict(f)) for f in visibles],   # Fila usa slots -> asdict, no __dict__
        mi_bandeja=mias,
        asignaciones=asignaciones,
        cache_horas=cache,
        estados=estados,
    )

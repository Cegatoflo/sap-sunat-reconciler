"""
Bandeja de trabajo (asignaciones).

  · Cada analista ve SOLO su bandeja. La de los demás no le aparece ni la puede tomar.
  · La asignación es EXCLUSIVA: un comprobante tiene un solo dueño (lo garantiza la PK).
  · El manager ve todas y puede revocarle la asignación a cualquiera.
  · Todo queda scopeado a la empresa de la sesión actual (no se mezclan entre empresas).
  · Toda acción queda registrada en la tabla de auditoría.
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import solo_manager, usuario_actual
from ..models import Asignacion, Auditoria, Sesion

router = APIRouter(prefix="/api/bandeja", tags=["bandeja"])


class ItemIn(BaseModel):
    clave: str
    periodo: str
    fecha: str = ""
    ruc: str = ""
    proveedor: str = ""
    tipo: str = ""
    comprobante: str = ""
    moneda: str = ""
    total: float = 0.0


class ItemOut(BaseModel):
    empresa: str
    clave: str
    usuario: str
    periodo: str
    fecha: str
    ruc: str
    proveedor: str
    tipo: str
    comprobante: str
    moneda: str
    total: float
    estado: str
    asignada: datetime

    model_config = {"from_attributes": True}


class ClavesIn(BaseModel):
    claves: list[str] = Field(min_length=1)


class EstadoIn(ClavesIn):
    estado: Literal["pendiente", "registrada"]


class ParIn(BaseModel):
    clave: str
    usuario: str


class RevocarIn(BaseModel):
    pares: list[ParIn] = Field(min_length=1)


@router.get("", response_model=list[ItemOut])
def listar(
    todos: bool = Query(False, description="Solo manager: ver las asignaciones de todos"),
    ses: Sesion = Depends(usuario_actual),
    db: Session = Depends(get_db),
) -> list[Asignacion]:
    q = db.query(Asignacion).filter(Asignacion.empresa == ses.empresa)
    if todos:
        if ses.rol != "manager":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el manager ve todas las asignaciones")
        q = q.order_by(Asignacion.usuario, Asignacion.periodo, Asignacion.proveedor)
    else:
        q = q.filter(Asignacion.usuario == ses.usuario).order_by(
            Asignacion.periodo, Asignacion.proveedor
        )
    return q.all()


@router.post("/asignar")
def asignar(items: list[ItemIn], ses: Sesion = Depends(usuario_actual),
            db: Session = Depends(get_db)) -> dict:
    """Toma comprobantes para mi bandeja (dentro de la empresa de mi sesión actual).

    La asignación es EXCLUSIVA: si otra persona ya lo apartó, no se puede tomar.
    Se informa cuáles quedaron fuera y quién los tiene (evita reprocesar la misma factura).
    """
    nuevos = 0
    ya_mios = 0
    tomados: list[dict] = []

    for it in items:
        existente = db.get(Asignacion, {"empresa": ses.empresa, "clave": it.clave})
        if existente:
            if existente.usuario == ses.usuario:
                ya_mios += 1
            else:
                tomados.append({"comprobante": it.comprobante, "usuario": existente.usuario})
            continue
        db.add(Asignacion(empresa=ses.empresa, usuario=ses.usuario, **it.model_dump()))
        db.add(Auditoria(actor=ses.usuario, empresa=ses.empresa, accion="asignar", clave=it.clave,
                         detalle=it.comprobante))
        nuevos += 1

    try:
        db.commit()
    except IntegrityError:
        # Carrera: alguien lo tomó entre el chequeo y el commit. La PK lo impidió.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Otro usuario tomó alguno de esos comprobantes justo ahora. Recarga e inténtalo de nuevo.",
        ) from None

    return {"ok": True, "asignados": nuevos, "ya_mios": ya_mios,
            "tomados_por_otros": tomados, "recibidos": len(items)}


@router.post("/liberar")
def liberar(datos: ClavesIn, ses: Sesion = Depends(usuario_actual),
            db: Session = Depends(get_db)) -> dict:
    """Devuelve comprobantes al pozo común (vuelven a estar disponibles para todos)."""
    n = 0
    for k in datos.claves:
        a = db.get(Asignacion, {"empresa": ses.empresa, "clave": k})
        if a and a.usuario == ses.usuario:          # solo puedo soltar lo mío
            db.delete(a)
            db.add(Auditoria(actor=ses.usuario, empresa=ses.empresa, accion="liberar", clave=k))
            n += 1
    db.commit()
    return {"ok": True, "liberados": n}


@router.post("/estado")
def cambiar_estado(datos: EstadoIn, ses: Sesion = Depends(usuario_actual),
                   db: Session = Depends(get_db)) -> dict:
    n = 0
    for k in datos.claves:
        a = db.get(Asignacion, {"empresa": ses.empresa, "clave": k})
        if a and a.usuario == ses.usuario:
            a.estado = datos.estado
            db.add(Auditoria(actor=ses.usuario, empresa=ses.empresa, accion="estado", clave=k,
                             detalle=datos.estado))
            n += 1
    db.commit()
    return {"ok": True, "actualizados": n}


@router.post("/revocar")
def revocar(datos: RevocarIn, ses: Sesion = Depends(solo_manager),
            db: Session = Depends(get_db)) -> dict:
    """El manager le quita la asignación a quien la tenga: el comprobante vuelve a estar libre."""
    n = 0
    for p in datos.pares:
        a = db.get(Asignacion, {"empresa": ses.empresa, "clave": p.clave})
        if a and a.usuario == p.usuario:            # el dueño sigue siendo el esperado
            db.delete(a)
            db.add(Auditoria(actor=ses.usuario, empresa=ses.empresa, accion="revocar",
                             objetivo=p.usuario, clave=p.clave))
            n += 1
    db.commit()
    return {"ok": True, "revocados": n}

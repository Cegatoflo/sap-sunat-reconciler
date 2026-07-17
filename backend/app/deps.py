"""Dependencias reutilizables de FastAPI."""
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .auth import COOKIE, sesion_valida
from .db import get_db
from .models import Sesion


def usuario_actual(
    sid: str | None = Cookie(default=None, alias=COOKIE),
    db: Session = Depends(get_db),
) -> Sesion:
    ses = sesion_valida(db, sid)
    if not ses:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    return ses


def solo_manager(ses: Sesion = Depends(usuario_actual)) -> Sesion:
    if ses.rol != "manager":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requiere rol de manager")
    return ses

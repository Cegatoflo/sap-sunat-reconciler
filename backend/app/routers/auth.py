from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import COOKIE, autenticar, cerrar_sesion, sesion_valida
from ..config import get_settings
from ..db import get_db
from ..deps import usuario_actual
from ..empresas import listar_empresas_publico
from ..models import Sesion

router = APIRouter(prefix="/api", tags=["auth"])


class EmpresaOut(BaseModel):
    codigo: str
    nombre: str


class LoginIn(BaseModel):
    empresa: str = Field(min_length=1, max_length=20)
    usuario: str = Field(min_length=1, max_length=50)
    clave: str = Field(min_length=1, max_length=200)


class UsuarioOut(BaseModel):
    usuario: str
    nombre: str
    rol: str
    empresa: str
    empresa_nombre: str


@router.get("/empresas", response_model=list[EmpresaOut])
def empresas() -> list[dict]:
    """Público (sin sesión): solo código y nombre, para el selector del login."""
    return listar_empresas_publico()


@router.post("/login", response_model=UsuarioOut)
def login(datos: LoginIn, resp: Response, db: Session = Depends(get_db)) -> UsuarioOut:
    s = get_settings()
    token, info = autenticar(db, datos.empresa, datos.usuario, datos.clave)
    resp.set_cookie(
        COOKIE, token,
        max_age=s.sesion_horas * 3600,
        httponly=True,
        samesite="lax",
        secure=s.es_produccion,      # en producción, solo por HTTPS
        path="/",
    )
    return UsuarioOut(**info)


@router.post("/logout")
def logout(resp: Response, sid: str | None = Cookie(default=None, alias=COOKIE),
           db: Session = Depends(get_db)) -> dict:
    cerrar_sesion(db, sid)
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/sesion")
def sesion(sid: str | None = Cookie(default=None, alias=COOKIE),
           db: Session = Depends(get_db)) -> dict:
    ses = sesion_valida(db, sid)
    if not ses:
        return {"ok": False}
    from ..empresas import obtener_empresa
    return {"ok": True, "usuario": ses.usuario, "nombre": ses.nombre, "rol": ses.rol,
            "empresa": ses.empresa, "empresa_nombre": obtener_empresa(ses.empresa).nombre}


@router.get("/yo", response_model=UsuarioOut)
def yo(ses: Sesion = Depends(usuario_actual)) -> UsuarioOut:
    from ..empresas import obtener_empresa
    return UsuarioOut(usuario=ses.usuario, nombre=ses.nombre, rol=ses.rol,
                      empresa=ses.empresa, empresa_nombre=obtener_empresa(ses.empresa).nombre)

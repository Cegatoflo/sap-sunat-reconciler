"""
Autenticación e identidad.

SAP es la fuente de verdad: la persona entra con SU usuario y clave de SAP, más la
empresa elegida en el login (mismo usuario/clave siempre; lo que cambia es contra
qué Company DB se validan). La contraseña NUNCA se almacena — solo se usa para que
SAP confirme la identidad.

Reglas de acceso (configurables por empresa en .env, con valores por defecto globales):
  · Solo los usuarios de {EMPRESA}_DEPARTAMENTOS_PERMITIDOS (4 = Contabilidad) entran.
  · Los usuarios bloqueados en SAP no entran.
  · Rol manager = Superusuario de SAP (o estar en {EMPRESA}_MANAGERS_EXTRA).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .config import get_settings
from .empresas import obtener_empresa
from .models import Auditoria, Sesion
from .services import sap

COOKIE = "sid"


class ErrorAcceso(HTTPException):
    def __init__(self, detalle: str, code: int = status.HTTP_403_FORBIDDEN) -> None:
        super().__init__(status_code=code, detail=detalle)


def autenticar(db: Session, empresa_codigo: str, usuario: str, clave: str) -> tuple[str, dict]:
    """Valida contra SAP (Company DB de la empresa elegida), aplica las reglas de
    acceso y crea la sesión. Devuelve (token, datos_usuario)."""
    s = get_settings()
    usuario = usuario.strip()
    empresa = obtener_empresa(empresa_codigo)

    faltan = empresa.campos_faltantes()
    if faltan:
        raise ErrorAcceso(
            f"La empresa {empresa.nombre} aún no está completamente configurada "
            f"(falta: {', '.join(faltan)}). Avisa a sistemas.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        ok = sap.validar_credenciales(empresa, usuario, clave)
    except RuntimeError as e:
        raise ErrorAcceso(str(e), status.HTTP_503_SERVICE_UNAVAILABLE) from e
    if not ok:
        raise ErrorAcceso("Usuario o clave incorrectos.", status.HTTP_401_UNAUTHORIZED)

    info = sap.obtener_sap(empresa).usuario_info(usuario)
    if not info:
        raise ErrorAcceso(f"Tu usuario no existe en la maestra de SAP de {empresa.nombre}.")
    if info["bloqueado"]:
        raise ErrorAcceso("Tu usuario de SAP está bloqueado.")

    es_extra = usuario.lower() in {m.lower() for m in empresa.managers_extra}
    if info["departamento"] not in empresa.departamentos_permitidos and not es_extra:
        raise ErrorAcceso(f"Acceso denegado: no perteneces al área de {empresa.nombre_departamento}.")

    rol = "manager" if (info["superusuario"] or es_extra) else "analista"

    token = secrets.token_urlsafe(48)
    ahora = datetime.now(timezone.utc)
    db.add(Sesion(token=token, usuario=usuario, nombre=info["nombre"], rol=rol, empresa=empresa.codigo,
                  creada=ahora, expira=ahora + timedelta(hours=s.sesion_horas)))
    db.add(Auditoria(actor=usuario, empresa=empresa.codigo, accion="login", detalle=f"rol={rol}"))
    # limpiar sesiones vencidas
    db.query(Sesion).filter(Sesion.expira < ahora).delete()
    db.commit()

    return token, {"usuario": usuario, "nombre": info["nombre"], "rol": rol,
                   "empresa": empresa.codigo, "empresa_nombre": empresa.nombre}


def sesion_valida(db: Session, token: str | None) -> Sesion | None:
    if not token:
        return None
    ses = db.get(Sesion, token)
    if not ses:
        return None
    expira = ses.expira if ses.expira.tzinfo else ses.expira.replace(tzinfo=timezone.utc)
    if expira < datetime.now(timezone.utc):
        db.delete(ses)
        db.commit()
        return None
    return ses


def cerrar_sesion(db: Session, token: str | None) -> None:
    if token and (ses := db.get(Sesion, token)):
        db.delete(ses)
        db.commit()

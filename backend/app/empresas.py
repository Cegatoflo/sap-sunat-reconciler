"""
Registro de empresas (multi-tenant).

El mismo usuario/clave de SAP sirve siempre — lo que cambia según la empresa elegida
en el login es CONTRA QUÉ Company DB se valida, y con qué credenciales de SUNAT se
descarga la propuesta RCE. Cada empresa vive en el .env con un prefijo:

    EMPRESAS=EMPRESA1,EMPRESA2

    EMPRESA1_NOMBRE=Empresa Uno S.A.C.
    EMPRESA1_SAP_COMPANY_DB=SBO_EMPRESA1_PROD
    EMPRESA1_SAP_SERVICE_USER=manager
    EMPRESA1_SAP_SERVICE_PASSWORD=...
    EMPRESA1_SUNAT_RUC=...
    EMPRESA1_SUNAT_CLIENT_ID=...
    EMPRESA1_SUNAT_CLIENT_SECRET=...
    EMPRESA1_SUNAT_SOL_USER=...
    EMPRESA1_SUNAT_SOL_PASSWORD=...
    EMPRESA1_DEPARTAMENTOS_PERMITIDOS=4      (opcional, si no usa el global)
    EMPRESA1_MANAGERS_EXTRA=manager          (opcional)

No se exige que todos los campos estén completos al arrancar: una empresa a medio
configurar (ej. mientras se consigue el resto de credenciales) no debe tumbar
la app entera. Se valida recién cuando alguien intenta usarla (login o cruce),
con un mensaje claro de qué falta.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

from .config import get_settings

RAIZ = Path(__file__).resolve().parents[2]


def _valores_env() -> dict[str, str]:
    """.env + variables de entorno reales (estas últimas ganan, igual que pydantic-settings).

    Solo sirve para leer las variables con prefijo por empresa ({CODIGO}_...), que al ser
    dinámicas no pueden declararse como campos fijos de Settings.
    """
    m = dict(dotenv_values(RAIZ / ".env"))
    m.update({k: v for k, v in os.environ.items() if v is not None})
    return {k: v for k, v in m.items() if v is not None}


@dataclass(frozen=True, slots=True)
class Empresa:
    codigo: str
    nombre: str

    sap_company_db: str
    sap_service_user: str
    sap_service_password: str

    sunat_ruc: str
    sunat_client_id: str
    sunat_client_secret: str
    sunat_sol_user: str
    sunat_sol_password: str

    departamentos_permitidos: list[int] = field(default_factory=list)
    nombre_departamento: str = "Contabilidad"
    managers_extra: list[str] = field(default_factory=list)

    def campos_faltantes(self) -> list[str]:
        """Qué le falta para poder usarse. Vacío = está completa."""
        obligatorios = {
            "SAP_COMPANY_DB": self.sap_company_db,
            "SAP_SERVICE_USER": self.sap_service_user,
            "SAP_SERVICE_PASSWORD": self.sap_service_password,
            "SUNAT_RUC": self.sunat_ruc,
            "SUNAT_CLIENT_ID": self.sunat_client_id,
            "SUNAT_CLIENT_SECRET": self.sunat_client_secret,
            "SUNAT_SOL_USER": self.sunat_sol_user,
            "SUNAT_SOL_PASSWORD": self.sunat_sol_password,
        }
        return [f"{self.codigo}_{k}" for k, v in obligatorios.items() if not v]

    @property
    def completa(self) -> bool:
        return not self.campos_faltantes()


def _lista(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


@lru_cache
def cargar_empresas() -> dict[str, Empresa]:
    env = _valores_env()
    codigos = _lista(env.get("EMPRESAS", ""))
    if not codigos:
        raise RuntimeError(
            "Define EMPRESAS en el .env (ej. EMPRESAS=EMPRESA1,EMPRESA2). "
            "Cada código necesita sus variables {CODIGO}_SAP_COMPANY_DB, etc."
        )

    # valores globales por defecto (si una empresa no define los suyos propios)
    s = get_settings()
    deptos_global = s.departamentos_permitidos
    nombre_depto_global = s.nombre_departamento
    managers_global = s.managers_extra

    out: dict[str, Empresa] = {}
    for cod in codigos:
        p = f"{cod}_"
        g = lambda campo, default="": env.get(p + campo, default).strip()  # noqa: E731

        deptos_txt = g("DEPARTAMENTOS_PERMITIDOS")
        managers_txt = g("MANAGERS_EXTRA")

        out[cod] = Empresa(
            codigo=cod,
            nombre=g("NOMBRE", cod) or cod,
            sap_company_db=g("SAP_COMPANY_DB"),
            sap_service_user=g("SAP_SERVICE_USER"),
            sap_service_password=g("SAP_SERVICE_PASSWORD"),
            sunat_ruc=g("SUNAT_RUC"),
            sunat_client_id=g("SUNAT_CLIENT_ID"),
            sunat_client_secret=g("SUNAT_CLIENT_SECRET"),
            sunat_sol_user=g("SUNAT_SOL_USER"),
            sunat_sol_password=g("SUNAT_SOL_PASSWORD"),
            departamentos_permitidos=(
                [int(x) for x in deptos_txt.split(",") if x.strip()] if deptos_txt else deptos_global
            ),
            nombre_departamento=g("NOMBRE_DEPARTAMENTO") or nombre_depto_global,
            managers_extra=_lista(managers_txt) if managers_txt else managers_global,
        )
    return out


def obtener_empresa(codigo: str) -> Empresa:
    emp = cargar_empresas().get(codigo)
    if not emp:
        from fastapi import HTTPException, status
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Empresa desconocida: {codigo}")
    return emp


def listar_empresas_publico() -> list[dict]:
    """Lo mínimo para el selector del login: código y nombre. Nunca credenciales."""
    return [{"codigo": e.codigo, "nombre": e.nombre} for e in cargar_empresas().values()]

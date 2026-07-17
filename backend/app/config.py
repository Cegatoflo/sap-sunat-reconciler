"""
Configuración GLOBAL de la aplicación (compartida por todas las empresas).
Todo sale del archivo .env (nunca del código).

Lo que SÍ cambia por empresa (Company DB de SAP, credenciales de SUNAT, cuenta de
servicio) vive en `empresas.py`, no aquí — ver ese módulo para el detalle.
"""
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# conciliador/backend/app/config.py  ->  conciliador/
RAIZ = Path(__file__).resolve().parents[2]
DATA_DIR = RAIZ / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---------- App ----------
    app_env: str = "development"
    secret_key: str
    sesion_horas: int = 12

    # ---------- SAP: mismo servidor para todas las empresas ----------
    sap_base_url: str
    sap_verify_ssl: bool = False
    sap_ca_bundle: str = ""

    # ---------- Acceso: valores por defecto si una empresa no los redefine ----------
    departamentos_permitidos: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [4])
    nombre_departamento: str = "Contabilidad"
    managers_extra: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # ---------- Correo ----------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "Alertas SUNAT"
    smtp_to: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # ---------- CORS ----------
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:18451"]
    )

    # --- listas separadas por coma en el .env ---
    @field_validator("departamentos_permitidos", mode="before")
    @classmethod
    def _deptos(cls, v):
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v

    @field_validator("managers_extra", "smtp_to", "cors_origins", mode="before")
    @classmethod
    def _lista(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # --- rutas derivadas ---
    @property
    def db_path(self) -> Path:
        return DATA_DIR / "conciliador.db"

    def propuestas_dir(self, empresa_codigo: str) -> Path:
        """Cada empresa tiene su propia caché: las propuestas RCE de dos empresas
        distintas no deben mezclarse aunque compartan proveedores."""
        return DATA_DIR / "propuestas" / empresa_codigo

    @property
    def es_produccion(self) -> bool:
        return self.app_env.lower() in ("production", "produccion", "prod")

    # --- verificación TLS que httpx entiende ---
    @property
    def sap_ssl_verify(self):
        if self.sap_ca_bundle:
            return self.sap_ca_bundle
        return self.sap_verify_ssl


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "propuestas").mkdir(exist_ok=True)
    # Guardarraíl: en producción no se permite ignorar el certificado de SAP
    if s.es_produccion and not s.sap_verify_ssl and not s.sap_ca_bundle:
        raise RuntimeError(
            "APP_ENV=production con SAP_VERIFY_SSL=false: inseguro. "
            "Instala el CA interno y pon SAP_VERIFY_SSL=true (o define SAP_CA_BUNDLE)."
        )
    return s

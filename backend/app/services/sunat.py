"""
Cliente de SUNAT — SIRE / Registro de Compras (RCE).

Multi-empresa: cada empresa tiene su propia app SUNAT (client_id/secret) y su propio
usuario SOL, así que `SunatClient` recibe una `Empresa` explícita. La caché de
propuestas también se guarda separada por empresa (data/propuestas/{CODIGO}/...):
mezclar los CSV de dos empresas produciría un cruce sin sentido.

El límite de frecuencia (rate limit) de SUNAT sí se trata como GLOBAL —el lock y el
intervalo mínimo son compartidos entre empresas— porque probablemente limita por IP
de origen, no por client_id; más vale ser conservador.

Flujo de la propuesta (asíncrono, tal como lo exige SUNAT):
  1) exportacioncomprobantepropuesta  -> devuelve numTicket
  2) consultaestadotickets            -> esperar a "Terminado", da el nombre del ZIP
  3) archivoreporte                   -> descarga el ZIP con el CSV

OJO (no está en el manual de SUNAT, lo descubrimos probando):
  el paso 3 exige además numTicket, perTributario, codLibro y codProceso.
  Sin esos parámetros devuelve HTTP 500.
"""
from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from ..config import get_settings

if TYPE_CHECKING:
    from ..empresas import Empresa

log = logging.getLogger(__name__)

SEG_BASE = "https://api-seguridad.sunat.gob.pe/v1/clientessol"
SIRE = "https://api-sire.sunat.gob.pe/v1/contribuyente/migeigv/libros"
COD_LIBRO_RCE = "080000"
COD_PROCESO_EXPORTA = "10"

# ---------------------------------------------------------------- control de frecuencia
# SIRE limita la cadencia de EXPORTACIONES (exportacioncomprobantepropuesta -> 429),
# probablemente por IP. En la práctica, consultaestadotickets y archivoreporte nunca han
# dado 429 — el límite parece ser específico del endpoint que genera el ticket, no de
# toda la API SIRE. Por eso el intervalo mínimo se aplica SOLO ahí, no al polling.
#
# Dos reglas GLOBALES (compartidas entre empresas, un solo contador):
#   1) las descargas se serializan (un lock: nunca dos a la vez, sea cual sea la empresa),
#   2) se respeta un intervalo mínimo ENTRE LLAMADAS REALES al endpoint de exportación.
#
# Importante: el reloj se actualiza en el momento de CADA intento real (éxito o 429), no
# antes de todo el ciclo. Si no, un 429 con backoff de 30-60s deja el reloj desactualizado
# y el SIGUIENTE periodo dispara casi de inmediato, saltándose el intervalo por completo
# (nos pasó: 202505 salió a los 6s de que 202504 terminara su backoff).
INTERVALO_MIN_SEG = 35
_lock_descarga = threading.Lock()
_ultima_llamada = 0.0


def _esperar_turno() -> None:
    """Espera lo que falte y ACTUALIZA el reloj — debe llamarse justo antes de cada
    intento real contra el endpoint de exportación (inicial y cada reintento por 429)."""
    global _ultima_llamada
    falta = INTERVALO_MIN_SEG - (time.monotonic() - _ultima_llamada)
    if falta > 0:
        log.info("SUNAT: espero %.0fs para no chocar con el rate limit", falta)
        time.sleep(falta)
    _ultima_llamada = time.monotonic()


# ---------------------------------------------------------------- vigencia de la caché
def _meses_atras(periodo: str) -> int:
    """Cuántos meses hay entre `periodo` y el mes en curso."""
    a = date.today()
    y, m = int(periodo[:4]), int(periodo[4:6])
    return (a.year - y) * 12 + (a.month - m)


def ttl_horas(periodo: str) -> float:
    """Cuánto vale la copia en caché antes de refrescarla.

    El mes en curso cambia todos los días (los proveedores siguen declarando);
    los meses ya cerrados prácticamente no se mueven.
    """
    atras = _meses_atras(periodo)
    if atras <= 0:
        return 6          # mes en curso
    if atras <= 2:
        return 24         # meses recientes (aún entran comprobantes atrasados)
    return 24 * 30        # meses antiguos: estables


def _ruta_propuesta(empresa_codigo: str, periodo: str) -> Path:
    d = get_settings().propuestas_dir(empresa_codigo)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"propuesta_rce_{periodo}.csv"


# ---------------------------------------------------------------- ticket pendiente (resumible)
# Si el poll se agota antes de que SUNAT termine, NO hay que pedir un ticket nuevo: además de
# gastar cupo del rate limit, SUNAT puede rechazar (422) una segunda exportación del mismo
# periodo mientras la primera sigue en curso. Se persiste el ticket para retomarlo después.
TICKET_VIGENCIA_SEG = 30 * 60


def _ruta_ticket(empresa_codigo: str, periodo: str) -> Path:
    return get_settings().propuestas_dir(empresa_codigo) / f".ticket_{periodo}.json"


def _leer_ticket_pendiente(empresa_codigo: str, periodo: str) -> str | None:
    p = _ruta_ticket(empresa_codigo, periodo)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - d.get("creado", 0) > TICKET_VIGENCIA_SEG:
        return None                                    # muy viejo, mejor pedir uno nuevo
    return d.get("numTicket")


def _guardar_ticket_pendiente(empresa_codigo: str, periodo: str, num_ticket: str) -> None:
    _ruta_ticket(empresa_codigo, periodo).write_text(
        json.dumps({"numTicket": num_ticket, "creado": time.time()}), encoding="utf-8"
    )


def _borrar_ticket_pendiente(empresa_codigo: str, periodo: str) -> None:
    _ruta_ticket(empresa_codigo, periodo).unlink(missing_ok=True)


def edad_cache_horas(empresa_codigo: str, periodo: str) -> float | None:
    """Antigüedad de la copia local, o None si no existe."""
    p = _ruta_propuesta(empresa_codigo, periodo)
    if not p.exists():
        return None
    return (time.time() - p.stat().st_mtime) / 3600


# SUNAT a veces emite los nombres envueltos en CDATA de XML
_CDATA = re.compile(r"^!?\[?CDATA\[(.*?)\]\]?>?$", re.S)


def limpiar(s: str | None) -> str:
    s = (s or "").strip()
    m = _CDATA.match(s)
    return m.group(1).strip() if m else s


class SunatError(RuntimeError):
    pass


class SunatClient:
    def __init__(self, empresa: Empresa) -> None:
        self._emp = empresa
        self._c = httpx.Client(timeout=httpx.Timeout(90.0, connect=20.0))
        self._token: str | None = None
        self._token_exp: float = 0.0

    def cerrar(self) -> None:
        self._c.close()

    def __enter__(self) -> SunatClient:
        return self

    def __exit__(self, *exc) -> None:
        self.cerrar()

    # ---------- token ----------
    def token(self) -> str:
        """El token dura 1 h; se reutiliza hasta 5 min antes de vencer."""
        if self._token and time.time() < self._token_exp:
            return self._token
        e = self._emp
        r = self._c.post(
            f"{SEG_BASE}/{e.sunat_client_id}/oauth2/token/",
            data={
                "grant_type": "password",          # NO client_credentials
                "scope": "https://api-sire.sunat.gob.pe",
                "client_id": e.sunat_client_id,
                "client_secret": e.sunat_client_secret,
                "username": e.sunat_sol_user,      # RUC + usuario SOL
                "password": e.sunat_sol_password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200 or not r.json().get("access_token"):
            raise SunatError(f"No se obtuvo token de SUNAT para {e.codigo} ({r.status_code})")
        d = r.json()
        self._token = d["access_token"]
        self._token_exp = time.time() + int(d.get("expires_in", 3600)) - 300
        return self._token

    def _hdr(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}

    def _get(self, url: str, binario: bool = False, es_exportacion: bool = False):
        """GET con backoff ante 429/503 (SIRE limita la frecuencia de tickets).

        `es_exportacion=True` (solo el endpoint que genera el ticket) respeta además el
        intervalo mínimo GLOBAL entre llamadas — y lo hace justo antes de CADA intento
        (inicial y cada reintento), para que el reloj siempre refleje la última llamada
        REAL, no el momento en que se empezó a esperar.

        Si SUNAT responde con error, se incluye el CUERPO en el mensaje: httpx.raise_for_status()
        por sí solo solo da el código HTTP, y SUNAT manda el detalle real (codError/desError) en
        el body — sin esto, errores como 422 se ven como un código pelado e indescifrable.
        """
        espera = 30
        for intento in range(1, 6):
            if es_exportacion:
                _esperar_turno()
            r = self._c.get(url, headers=self._hdr())
            if r.status_code in (429, 503) and intento < 5:
                log.warning("SUNAT %s (rate limit) — espero %ss (intento %s/5)",
                            r.status_code, espera, intento)
                time.sleep(espera)
                espera = min(espera * 2, 300)
                continue
            if r.is_error:
                detalle = r.text.strip()[:500]
                log.error("SUNAT %s en %s | body: %s", r.status_code, url, detalle)
                raise SunatError(f"SUNAT devolvió {r.status_code}: {detalle or '(sin cuerpo)'}")
            return r.content if binario else r.json()
        raise SunatError("SUNAT sigue limitando las peticiones (429) tras varios reintentos")

    # ---------- propuesta RCE ----------
    def propuesta_rce(self, periodo: str, forzar: bool = False) -> Path:
        """Ruta del CSV de la propuesta (de ESTA empresa), refrescándolo de SUNAT solo si hace falta.

        · Si la copia local está vigente (según ttl_horas) -> se usa tal cual.
        · Si venció -> se descarga, serializando y espaciando las llamadas a SUNAT.
        · Si SUNAT no responde (429 tras reintentos) pero hay copia local ->
          se devuelve la copia vieja. Mejor un dato de ayer que una pantalla de error.
        """
        cod = self._emp.codigo
        destino = _ruta_propuesta(cod, periodo)
        edad = edad_cache_horas(cod, periodo)

        if not forzar and edad is not None and edad < ttl_horas(periodo):
            return destino                                    # caché vigente

        with _lock_descarga:                                  # una descarga a la vez (global)
            # Otro hilo pudo haberla refrescado mientras esperábamos el lock
            edad = edad_cache_horas(cod, periodo)
            if not forzar and edad is not None and edad < ttl_horas(periodo):
                return destino
            try:
                # el intervalo mínimo se respeta DENTRO de _descargar, justo antes de la
                # llamada real al endpoint de exportación (ver _get con es_exportacion=True)
                return self._descargar(periodo, destino)
            except (SunatError, httpx.HTTPError) as e:
                if destino.exists():
                    log.warning("[%s] No pude refrescar %s (%s). Uso la copia en caché de hace %.1f h.",
                                cod, periodo, e, edad or 0)
                    return destino
                raise

    def _descargar(self, periodo: str, destino: Path) -> Path:
        cod = self._emp.codigo

        # 1) pedir la exportación -> ticket (o reanudar uno pendiente: pedir dos veces para el
        #    mismo periodo mientras el primero sigue en curso hace que SUNAT responda 422)
        ticket = _leer_ticket_pendiente(cod, periodo)
        if ticket:
            log.info("[%s] Reanudando ticket pendiente %s (periodo %s), en vez de pedir uno nuevo",
                     cod, ticket, periodo)
        else:
            url = (f"{SIRE}/rce/propuesta/web/propuesta/{periodo}/exportacioncomprobantepropuesta"
                   f"?codTipoArchivo=1&codOrigenEnvio=2")
            ticket = self._get(url, es_exportacion=True).get("numTicket")
            if not ticket:
                raise SunatError(f"SUNAT no devolvió ticket para el periodo {periodo}")
            log.info("[%s] SUNAT: ticket %s generado (periodo %s)", cod, ticket, periodo)
            _guardar_ticket_pendiente(cod, periodo, ticket)

        # 2) esperar a que el archivo esté listo (hasta ~2.5 min; si no alcanza, el ticket
        #    queda guardado y la PRÓXIMA llamada lo retoma en vez de generar uno nuevo)
        archivo = None
        ultimo_estado = None
        for _ in range(30):
            time.sleep(5)
            est = self._get(
                f"{SIRE}/rvierce/gestionprocesosmasivos/web/masivo/consultaestadotickets"
                f"?perIni={periodo}&perFin={periodo}&page=1&perPage=20&numTicket={ticket}"
            )
            regs = est.get("registros") or []
            if regs:
                ultimo_estado = regs[0].get("desEstadoProceso")
                if regs[0].get("archivoReporte"):
                    archivo = regs[0]["archivoReporte"][0]
                    break
        if not archivo:
            raise SunatError(
                f"El ticket {ticket} sigue en proceso en SUNAT (último estado: "
                f"{ultimo_estado or 'desconocido'}). Se guardó para reanudarlo: vuelve a "
                "intentarlo en un par de minutos, no generará un ticket nuevo."
            )
        _borrar_ticket_pendiente(cod, periodo)   # completado: ya no hace falta conservarlo

        # 3) descargar el ZIP  (los 4 parámetros extra NO están documentados pero son obligatorios)
        dl = (f"{SIRE}/rvierce/gestionprocesosmasivos/web/masivo/archivoreporte"
              f"?nomArchivoReporte={archivo['nomArchivoReporte']}"
              f"&codTipoArchivoReporte={archivo.get('codTipoAchivoReporte') or '00'}"
              f"&numTicket={ticket}&perTributario={periodo}"
              f"&codLibro={COD_LIBRO_RCE}&codProceso={COD_PROCESO_EXPORTA}")
        raw = self._get(dl, binario=True)

        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            z = zipfile.ZipFile(io.BytesIO(raw[4:]))   # a veces trae marca de "spanned archive"
        destino.write_bytes(z.read(z.namelist()[0]))
        log.info("[%s] SUNAT: propuesta %s guardada en %s", self._emp.codigo, periodo, destino)
        return destino

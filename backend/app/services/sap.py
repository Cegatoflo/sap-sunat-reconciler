"""
Cliente del SAP Business One Service Layer.

Multi-empresa: el servidor (`sap_base_url`) es el mismo para todas, pero cada empresa
tiene su propio Company DB y su propia cuenta de servicio.

⚠️ Gestión de sesiones (crítico): el Service Layer tiene un número LIMITADO de sesiones
licenciadas. Hacer un `Login` por cada petición y no cerrarlo las agota bajo carga —
SAP empieza a devolver 503 / desconexiones y el sistema entero cae. Por eso:

  1) La cuenta de servicio usa UNA sesión larga por empresa, reutilizada entre peticiones
     (SapSession, del pool `obtener_sap`). Se re-loguea sola si expira (401).
  2) validar_credenciales() cierra (Logout) la sesión que crea para validar, en vez de
     dejarla colgada.

Dos usos distintos, no mezclarlos:
  · validar_credenciales(): comprueba la identidad de UNA persona con SUS credenciales.
  · SapSession (cuenta de servicio): lee datos (facturas, usuarios) para la app.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

import httpx

from ..config import get_settings

if TYPE_CHECKING:
    from ..empresas import Empresa

log = logging.getLogger(__name__)

# Documentos de compra que se cruzan, con su tipo de comprobante SUNAT equivalente
DOCS_COMPRA: list[tuple[str, str]] = [
    ("PurchaseInvoices", "01"),     # Facturas
    ("PurchaseCreditNotes", "07"),  # Notas de crédito
]


def _cliente(verify) -> httpx.Client:
    # El pool por empresa es COMPARTIDO entre todos los usuarios concurrentes de esa
    # empresa (SapSession es única y reutilizada). Con pocas conexiones, varios analistas
    # consultando a la vez terminan esperando turno por el pool en vez de por SAP mismo
    # (medido: 6 a la vez subían la latencia individual a ~10s). Es tráfico LOCAL hacia el
    # propio Service Layer, no hacia SUNAT, así que no hay riesgo de bloqueo externo al subirlo.
    return httpx.Client(
        verify=verify,
        timeout=httpx.Timeout(60.0, connect=15.0),
        limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
    )


def _intentar_login(c: httpx.Client, s, empresa: Empresa, usuario: str, clave: str) -> httpx.Response:
    try:
        return c.post(
            f"{s.sap_base_url}/Login",
            json={"CompanyDB": empresa.sap_company_db, "UserName": usuario, "Password": clave},
        )
    except httpx.HTTPError as e:
        log.warning("Error de conexión hacia SAP en Login (%s): %s", type(e).__name__, e)
        raise RuntimeError(f"No se pudo contactar a SAP: {e}") from e


def validar_credenciales(empresa: Empresa, usuario: str, clave: str) -> bool:
    """True si SAP acepta ese usuario/clave para el Company DB de `empresa`.
    Nunca almacenamos la contraseña, y cerramos la sesión que se crea al validar.

    Bajo logins concurrentes SAP a veces da un traspié transitorio (5xx/timeout) sin que
    sea culpa de la clave — se reintenta una vez antes de darlo por error real.
    """
    s = get_settings()
    with _cliente(s.sap_ssl_verify) as c:
        r = _intentar_login(c, s, empresa, usuario, clave)
        if r.status_code >= 500:
            log.warning("SAP dio %s en Login (posible traspié bajo carga), reintento una vez. Body: %s",
                       r.status_code, r.text[:300])
            r = _intentar_login(c, s, empresa, usuario, clave)

        if r.status_code == 200:
            # cerrar la sesión recién abierta: SAP tiene sesiones limitadas, no dejarla colgada
            try:
                c.post(f"{s.sap_base_url}/Logout")
            except httpx.HTTPError:
                pass
            return True
        if r.status_code in (401, 403):
            return False
        log.error("SAP respuesta inesperada en Login: %s | body: %s", r.status_code, r.text[:300])
        raise RuntimeError(f"Respuesta inesperada de SAP ({r.status_code}): {r.text[:200]}")


class SapSession:
    """Sesión de servicio LARGA y reutilizada por empresa. Thread-safe.

    Un solo login vivo por empresa: httpx.Client es seguro entre hilos (pool de conexiones),
    y sólo el (re)login se serializa con un lock para que dos hilos no lo hagan a la vez.
    """

    def __init__(self, empresa: Empresa) -> None:
        self._emp = empresa
        self._s = get_settings()
        self._c = _cliente(self._s.sap_ssl_verify)
        self._lock = threading.Lock()
        self._logueado = False

    # ---------- sesión ----------
    def _login(self) -> None:
        r = self._c.post(
            f"{self._s.sap_base_url}/Login",
            json={
                "CompanyDB": self._emp.sap_company_db,
                "UserName": self._emp.sap_service_user,
                "Password": self._emp.sap_service_password,
            },
        )
        r.raise_for_status()
        self._logueado = True
        log.info("[%s] Sesión de servicio SAP iniciada (reutilizable)", self._emp.codigo)

    def _asegurar_login(self) -> None:
        if self._logueado:
            return
        with self._lock:
            if not self._logueado:
                self._login()

    def _get(self, path: str, page_size: int = 500) -> dict[str, Any]:
        self._asegurar_login()
        url = f"{self._s.sap_base_url}/{path}"
        headers = {"Prefer": f"odata.maxpagesize={page_size}"}
        r = self._c.get(url, headers=headers)
        if r.status_code == 401:          # sesión vencida -> re-login (una vez) y reintento
            with self._lock:
                self._login()
            r = self._c.get(url, headers=headers)
        r.raise_for_status()
        return r.json() if r.content else {}

    # ---------- paginación ----------
    def _todos(self, path: str, pagina: int = 500) -> list[dict]:
        """Pagina con $skip explícito, en páginas grandes para minimizar viajes de red.

        El Service Layer trae hasta ~4.800 proveedores o ~1.300 facturas por mes; a 100 por
        página eran decenas de round-trips por consulta. A 500 se reducen 5x, sin efecto en
        los datos (es solo cuántos vienen por respuesta).

        OJO: el Service Layer NO devuelve '@odata.nextLink' de forma fiable. Si te confías
        en él, te quedas solo con la primera página (nos pasó: 100 proveedores de 4.819).
        """
        out: list[dict] = []
        skip = 0
        sep = "&" if "?" in path else "?"
        while True:
            d = self._get(f"{path}{sep}$skip={skip}", page_size=pagina)
            vals = d.get("value", [])
            out.extend(vals)
            if len(vals) < pagina:          # última página
                break
            skip += len(vals)
        return out

    # ---------- consultas de negocio ----------
    def usuario_info(self, usercode: str) -> dict | None:
        """Atributos del usuario en SAP: nombre, departamento, superusuario, bloqueo."""
        q = ("Users?$select=UserCode,UserName,Superuser,Department,Branch,Locked,eMail"
             f"&$filter=UserCode eq '{usercode}'")
        vals = self._get(q).get("value", [])
        if not vals:
            return None
        u = vals[0]
        return {
            "usuario": u.get("UserCode"),
            "nombre": u.get("UserName") or u.get("UserCode"),
            "departamento": u.get("Department"),
            "superusuario": u.get("Superuser") == "tYES",
            "bloqueado": u.get("Locked") == "tYES",
            "email": u.get("eMail"),
        }

    def proveedores_nacionales(self) -> dict[str, str]:
        """CardCode -> RUC, solo proveedores con Country = PE."""
        bps = self._todos(
            "BusinessPartners?$select=CardCode,FederalTaxID"
            "&$filter=Country eq 'PE' and CardType eq 'cSupplier'"
        )
        return {b["CardCode"]: b["FederalTaxID"] for b in bps if b.get("FederalTaxID")}

    def documentos_compra(self, fec_ini: str, fec_fin: str) -> list[dict]:
        """Facturas (01) y notas de crédito (07) del periodo, por **fecha de contabilización**
        (DocDate), NO por fecha de emisión (TaxDate).

        Por qué DocDate y no TaxDate: SUNAT arma el Registro de Compras (RCE) por **periodo de
        anotación**, no de emisión. Una factura emitida en marzo pero anotada en junio (algo
        legal: hay hasta 12 meses para tomar el crédito fiscal) aparece en la propuesta RCE de
        JUNIO. En SAP, esa "fecha de anotación" es la de contabilización = DocDate. Si filtramos
        por TaxDate (emisión = marzo), no la encontramos en el cruce de junio y sale como un
        falso "Solo SUNAT", aunque sí esté registrada.
        Se sigue trayendo TaxDate para MOSTRARLA (la fecha de emisión es la que el usuario espera
        ver, igual que la columna de emisión de SUNAT).
        """
        out: list[dict] = []
        for entidad, tipo in DOCS_COMPRA:
            docs = self._todos(
                f"{entidad}?$select=DocEntry,DocNum,CardCode,CardName,DocDate,TaxDate,"
                f"DocTotal,DocCurrency,NumAtCard"
                f"&$filter=DocDate ge '{fec_ini}' and DocDate le '{fec_fin}'&$orderby=DocDate"
            )
            for d in docs:
                d["_tipo"] = tipo
            out.extend(docs)
        return out


# ---------------------------------------------------------------- pool de sesiones por empresa
_pool: dict[str, SapSession] = {}
_pool_lock = threading.Lock()


def obtener_sap(empresa: Empresa) -> SapSession:
    """Devuelve la sesión de servicio (larga, reutilizada) de la empresa. La crea si no existe."""
    with _pool_lock:
        ses = _pool.get(empresa.codigo)
        if ses is None:
            ses = SapSession(empresa)
            _pool[empresa.codigo] = ses
        return ses

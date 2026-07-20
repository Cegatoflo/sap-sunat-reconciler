"""
Motor de conciliación SAP ↔ SUNAT.

Emparejamiento por clave idéntica en ambos lados:

        RUC | tipo_comprobante | SERIE-NÚMERO

  · RUC:    SAP -> FederalTaxID del proveedor (solo Country=PE)
            SUNAT -> "Nro Doc Identidad" (tipo doc 6 = RUC)
  · Tipo:   SAP -> PurchaseInvoices=01, PurchaseCreditNotes=07
            SUNAT -> columna "Tipo CP"
  · Serie-Nº: SAP -> campo NumAtCard (nº del comprobante del proveedor)
              SUNAT -> columnas Serie + Número

Es el mismo comprobante físico, así que el número debe coincidir en ambos lados.
Cuando no coincide, es un hallazgo real (reemisión o error de digitación), no un fallo del cruce.
"""
from __future__ import annotations

import calendar
import csv
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from .sap import SapSession, obtener_sap
from .sunat import SunatClient, edad_cache_horas, estado_refresco, limpiar

if TYPE_CHECKING:
    from ..empresas import Empresa

# ---------------------------------------------------------------- caché del padrón de proveedores
# proveedores_nacionales() hace ~48 llamadas al Service Layer (4.800 proveedores / 100 por página).
# El maestro casi no cambia, así que cachearlo en memoria por empresa evita repetir eso en CADA
# cruce (era el grueso de los 4-6 s por consulta). TTL corto: si aparece un proveedor nuevo,
# en el peor caso se ve tras unos minutos.
_RUC_TTL_SEG = 30 * 60
_ruc_cache: dict[str, tuple[float, dict[str, str]]] = {}
_ruc_lock = threading.Lock()


def _proveedores_nacionales_cache(sap: SapSession, empresa_codigo: str) -> dict[str, str]:
    ahora = time.time()
    hit = _ruc_cache.get(empresa_codigo)
    if hit and (ahora - hit[0]) < _RUC_TTL_SEG:
        return hit[1]
    with _ruc_lock:                                   # que solo un hilo lo baje si varios coinciden
        hit = _ruc_cache.get(empresa_codigo)
        if hit and (time.time() - hit[0]) < _RUC_TTL_SEG:
            return hit[1]
        rucs = sap.proveedores_nacionales()
        _ruc_cache[empresa_codigo] = (time.time(), rucs)
        return rucs

# Estados del cruce
EN_AMBOS, SOLO_SAP, SOLO_SUNAT = 0, 1, 2

# Columnas del CSV de la propuesta RCE
C_FEC_EMISION, C_TIPO_CP, C_SERIE, C_NUM = 4, 6, 7, 9
C_TIPO_DOC, C_RUC, C_PROVEEDOR, C_TOTAL, C_MONEDA = 11, 12, 13, 24, 25

_SERIE_NUM = re.compile(r"([A-Za-z0-9]+)[-\s]+0*(\d+)")


def clave(ruc: str, tipo: str, serie: str, numero: str | int) -> str:
    """Normaliza: serie en mayúsculas, número sin ceros a la izquierda."""
    serie = (serie or "").strip().upper()
    num = str(numero).strip().lstrip("0") or "0"
    return f"{ruc}|{tipo}|{serie}-{num}"


def _fecha_iso(s: str) -> str:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", (s or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else (s or "")[:10]


def _num(x) -> float:
    try:
        return round(float(x or 0), 2)
    except (TypeError, ValueError):
        return 0.0


@dataclass(slots=True)
class Fila:
    clave: str
    periodo: str
    estado: int          # 0 en ambos | 1 solo SAP | 2 solo SUNAT
    fecha: str
    ruc: str
    proveedor: str
    tipo: str
    comprobante: str
    moneda: str
    total: float
    docnum_sap: int | None = None


def cargar_sunat(csv_path: Path) -> dict[str, dict]:
    """Comprobantes de proveedores NACIONALES (tipo doc 6 = RUC) del CSV de la propuesta."""
    out: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for r in list(csv.reader(f))[1:]:
            if len(r) <= C_MONEDA or r[C_TIPO_DOC].strip() != "6":
                continue
            ruc, serie, num = r[C_RUC].strip(), r[C_SERIE].strip(), r[C_NUM].strip()
            tipo = r[C_TIPO_CP].strip()
            if not (ruc and serie and num):
                continue
            out[clave(ruc, tipo, serie, num)] = {
                "ruc": ruc,
                "proveedor": limpiar(r[C_PROVEEDOR]),
                "tipo": tipo,
                "comprobante": f"{serie}-{num}",
                "fecha": _fecha_iso(r[C_FEC_EMISION]),
                "moneda": r[C_MONEDA].strip(),
                "total": _num(r[C_TOTAL]),
            }
    return out


def cargar_sap(sap: SapSession, periodo: str, ruc_por_cardcode: dict[str, str]) -> dict[str, dict]:
    """Facturas y NC de proveedores nacionales del periodo (por fecha de emisión)."""
    y, m = int(periodo[:4]), int(periodo[4:6])
    ini = f"{y:04d}-{m:02d}-01"
    fin = f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"

    out: dict[str, dict] = {}
    for d in sap.documentos_compra(ini, fin):
        ruc = ruc_por_cardcode.get(d["CardCode"])
        if not ruc:                                   # proveedor no nacional
            continue
        ref = (d.get("NumAtCard") or "").strip()
        m2 = _SERIE_NUM.match(ref)
        if not m2:                                    # sin serie-número utilizable
            continue
        tipo = d["_tipo"]
        out[clave(ruc, tipo, m2.group(1), m2.group(2))] = {
            "ruc": ruc,
            "proveedor": d.get("CardName") or "",
            "tipo": tipo,
            "comprobante": ref,
            "fecha": (d.get("TaxDate") or "")[:10],
            "moneda": d.get("DocCurrency") or "",
            "total": _num(d.get("DocTotal")),
            "docnum": d.get("DocNum"),
        }
    return out


def cruzar_periodo(sap: SapSession, sunat: SunatClient, periodo: str,
                   ruc_por_cardcode: dict[str, str], forzar: bool = False) -> list[Fila]:
    csv_path = sunat.propuesta_rce(periodo, forzar=forzar)
    lado_sunat = cargar_sunat(csv_path)
    lado_sap = cargar_sap(sap, periodo, ruc_por_cardcode)

    ambos = lado_sap.keys() & lado_sunat.keys()
    filas: list[Fila] = []
    for k in lado_sunat.keys() | lado_sap.keys():
        estado = EN_AMBOS if k in ambos else (SOLO_SAP if k in lado_sap else SOLO_SUNAT)
        base = lado_sunat.get(k) or lado_sap[k]      # SUNAT manda cuando existe en ambos
        filas.append(Fila(
            clave=k, periodo=periodo, estado=estado,
            fecha=base["fecha"], ruc=base["ruc"], proveedor=base["proveedor"],
            tipo=base["tipo"], comprobante=base["comprobante"],
            moneda=base["moneda"], total=base["total"],
            docnum_sap=lado_sap.get(k, {}).get("docnum"),
        ))
    filas.sort(key=lambda f: (f.estado, f.proveedor))
    return filas


def meses_rango(desde: str, hasta: str) -> list[str]:
    y, m = int(desde[:4]), int(desde[4:6])
    y2, m2 = int(hasta[:4]), int(hasta[4:6])
    out: list[str] = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def cruzar_rango(
    empresa: Empresa, desde: str, hasta: str, forzar: bool = False,
) -> tuple[list[Fila], dict[str, float | None], dict[str, str | None]]:
    """Devuelve (filas, antigüedad de la caché por periodo en horas, estado de refresco por
    periodo), para UNA empresa.

    `forzar=True` dispara el refresco desde SUNAT aunque la caché esté vigente (botón
    "Actualizar"). El refresco corre en segundo plano: `estados[periodo]` dice si ese periodo
    está 'actualizando' / 'listo' / 'error' / None, para que el frontend sondee y recargue.
    """
    filas: list[Fila] = []
    cache: dict[str, float | None] = {}
    estados: dict[str, str | None] = {}
    sap = obtener_sap(empresa)                    # sesión de servicio reutilizada (no se cierra)
    with SunatClient(empresa) as sunat:
        ruc_cc = _proveedores_nacionales_cache(sap, empresa.codigo)
        for periodo in meses_rango(desde, hasta):
            filas.extend(cruzar_periodo(sap, sunat, periodo, ruc_cc, forzar=forzar))
            cache[periodo] = edad_cache_horas(empresa.codigo, periodo)
            estados[periodo] = estado_refresco(empresa.codigo, periodo)
    return filas, cache, estados


def periodo_valido(p: str) -> bool:
    if not re.fullmatch(r"\d{6}", p):
        return False
    y, m = int(p[:4]), int(p[4:6])
    return 2000 <= y <= date.today().year + 1 and 1 <= m <= 12

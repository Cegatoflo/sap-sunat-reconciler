"""
Pruebas de carga y latencia del cruce.

Objetivo: garantizar que el USUARIO FINAL no vea fallas ni esperas excesivas.

Filosofía de las pruebas:
  · La ruta normal del usuario usa la CACHÉ de propuestas (el job nocturno la mantiene
    caliente), así que la carga pesada / concurrencia / rangos grandes se prueban contra
    esa ruta — NO se martilla SUNAT (eso bloquearía las credenciales de producción).
  · SUNAT se caracteriza aparte, con pocas llamadas medidas, para conocer su latencia y
    confirmar el manejo de rate limit — sin abusar.

Uso:
    python pruebas_carga.py --empresa MIEMPRESA --usuario manager --clave ***   # todo, bien cacheado
    python pruebas_carga.py --sunat         # incluye la caracterización de SUNAT (toca la API real)
    python pruebas_carga.py --url http://localhost:18450

Credenciales: por argumento, o por variables de entorno PC_EMPRESA / PC_USUARIO / PC_CLAVE.
Nunca las hardcodees aquí — este archivo se versiona en git.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


EMPRESA = USUARIO = CLAVE = ""  # se completan en main() desde --args o variables de entorno


def percentiles(muestras: list[float]) -> str:
    if not muestras:
        return "sin datos"
    s = sorted(muestras)
    p = lambda q: s[min(len(s) - 1, int(q * len(s)))]  # noqa: E731
    return (f"min {min(s):.2f}s · p50 {p(0.5):.2f}s · p95 {p(0.95):.2f}s · "
            f"max {max(s):.2f}s · prom {statistics.mean(s):.2f}s")


def login(base: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=180)
    r = c.post("/api/login", json={"empresa": EMPRESA, "usuario": USUARIO, "clave": CLAVE})
    r.raise_for_status()
    return c


def cruce(c: httpx.Client, desde: str, hasta: str, refrescar: bool = False):
    """Devuelve (segundos, ok, n_filas, error)."""
    t0 = time.perf_counter()
    try:
        r = c.get("/api/cruce", params={"desde": desde, "hasta": hasta, "refrescar": refrescar})
        dt = time.perf_counter() - t0
        if r.status_code == 200:
            return dt, True, len(r.json()["filas"]), None
        return dt, False, 0, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:  # noqa: BLE001
        return time.perf_counter() - t0, False, 0, str(e)[:120]


# --------------------------------------------------------------------------- pruebas
def prueba_latencia_repetida(c: httpx.Client, n: int = 15) -> None:
    print(f"\n[1] LATENCIA — mismo periodo cacheado, {n} veces seguidas (calienta y mide estabilidad)")
    lat, fallos = [], 0
    for i in range(n):
        dt, ok, filas, err = cruce(c, "202606", "202606")
        lat.append(dt)
        if not ok:
            fallos += 1
            print(f"    #{i + 1} FALLO: {err}")
    print(f"    filas: {filas} | fallos: {fallos}/{n}")
    print(f"    {percentiles(lat)}")


def prueba_por_rango(c: httpx.Client) -> None:
    print("\n[2] LATENCIA POR TAMAÑO DE RANGO (todo cacheado)")
    rangos = [
        ("1 mes", "202607", "202607"),
        ("3 meses", "202605", "202607"),
        ("6 meses", "202602", "202607"),
        ("12 meses", "202508", "202607"),
        ("19 meses (todo)", "202501", "202607"),
    ]
    for nombre, d, h in rangos:
        dt, ok, filas, err = cruce(c, d, h)
        estado = f"OK · {filas:,} filas" if ok else f"FALLO: {err}"
        print(f"    {nombre:<18} {dt:6.2f}s   {estado}")


def prueba_concurrencia(base: str, usuarios: int = 6) -> None:
    print(f"\n[3] CONCURRENCIA — {usuarios} analistas consultando A LA VEZ (cada uno su sesión)")
    # cada "analista" tiene su propia sesión/cliente, como en la realidad
    clientes = [login(base) for _ in range(usuarios)]
    rangos = [("202606", "202606"), ("202601", "202603"), ("202604", "202607")]

    def tarea(idx: int):
        c = clientes[idx % len(clientes)]
        d, h = rangos[idx % len(rangos)]
        return cruce(c, d, h)

    t0 = time.perf_counter()
    lat, fallos = [], 0
    with ThreadPoolExecutor(max_workers=usuarios) as ex:
        futs = [ex.submit(tarea, i) for i in range(usuarios)]
        for f in as_completed(futs):
            dt, ok, _, err = f.result()
            lat.append(dt)
            if not ok:
                fallos += 1
                print(f"    FALLO: {err}")
    total = time.perf_counter() - t0
    for c in clientes:
        c.close()
    print(f"    {usuarios} peticiones simultáneas resueltas en {total:.2f}s de pared | fallos: {fallos}")
    print(f"    latencia individual: {percentiles(lat)}")


def prueba_sostenida(c: httpx.Client, n: int = 30) -> None:
    print(f"\n[4] CARGA SOSTENIDA — {n} peticiones seguidas sin pausa (un solo usuario insistente)")
    lat, fallos = [], 0
    rangos = [("202606", "202606"), ("202601", "202601"), ("202603", "202605")]
    t0 = time.perf_counter()
    for i in range(n):
        d, h = rangos[i % len(rangos)]
        dt, ok, _, err = cruce(c, d, h)
        lat.append(dt)
        if not ok:
            fallos += 1
            print(f"    #{i + 1} FALLO: {err}")
    total = time.perf_counter() - t0
    print(f"    {n} peticiones en {total:.1f}s ({n / total:.1f} req/s) | fallos: {fallos}/{n}")
    print(f"    {percentiles(lat)}")


def prueba_sunat_controlada(c: httpx.Client) -> None:
    print("\n[5] SUNAT (CONTROLADO) — toca la API real, pocas llamadas medidas")
    print("    a) refrescar 1 periodo (fuerza descarga real desde SUNAT)")
    dt, ok, filas, err = cruce(c, "202606", "202606", refrescar=True)
    print(f"       {'OK' if ok else 'FALLO'} · {dt:.1f}s · {filas} filas" + (f" · {err}" if err else ""))
    print("    b) el MISMO periodo sin refrescar (debe salir de caché, instantáneo)")
    dt2, ok2, _, _ = cruce(c, "202606", "202606")
    print(f"       {'OK' if ok2 else 'FALLO'} · {dt2:.2f}s")
    factor = dt / dt2 if dt2 > 0 else 0
    print(f"    -> la caché es ~{factor:.0f}x más rápida; el usuario final casi nunca espera a SUNAT")


def main() -> int:
    global EMPRESA, USUARIO, CLAVE
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:18450")
    ap.add_argument("--empresa", default=os.environ.get("PC_EMPRESA", ""))
    ap.add_argument("--usuario", default=os.environ.get("PC_USUARIO", "manager"))
    ap.add_argument("--clave", default=os.environ.get("PC_CLAVE", ""))
    ap.add_argument("--sunat", action="store_true", help="incluye la caracterización de SUNAT (API real)")
    args = ap.parse_args()
    EMPRESA, USUARIO, CLAVE = args.empresa, args.usuario, args.clave
    if not EMPRESA or not CLAVE:
        print("Falta --empresa/--clave (o PC_EMPRESA/PC_CLAVE en el entorno). "
              "Ver --help.")
        return 1

    print(f"Pruebas de carga contra {args.url} (empresa {EMPRESA})")
    try:
        c = login(args.url)
    except Exception as e:  # noqa: BLE001
        print(f"No pude iniciar sesión: {e}")
        return 1

    prueba_latencia_repetida(c)
    prueba_por_rango(c)
    prueba_sostenida(c)
    c.close()
    prueba_concurrencia(args.url)

    if args.sunat:
        c2 = login(args.url)
        prueba_sunat_controlada(c2)
        c2.close()
    else:
        print("\n[5] SUNAT: omitido (usa --sunat para caracterizar la API real, con moderación)")

    print("\nListo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

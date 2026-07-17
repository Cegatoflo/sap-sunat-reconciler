"""
Precalienta la caché de propuestas RCE desde SUNAT, para TODAS las empresas configuradas
(las que estén completas — una empresa a medio configurar se salta con un aviso).

Pensado para correr de madrugada (Programador de tareas de Windows), cuando nadie
está usando la app: así los usuarios siempre encuentran el dato listo y las consultas
interactivas NUNCA chocan con el rate limit de SUNAT.

Uso:
    python refrescar_propuestas.py                    # todas las empresas: mes en curso + 2 anteriores
    python refrescar_propuestas.py --empresa MIEMPRESA  # solo una empresa
    python refrescar_propuestas.py 202601 202607       # rango explícito (todas las empresas)
    python refrescar_propuestas.py --forzar            # ignora el TTL y baja todo de nuevo

Programar (1 vez al día, 03:00): ver deploy/instalar_tarea_refrescar.ps1
(no uses `schtasks` a mano — corta mal las rutas con espacios, ej. "Cesar Torres").
"""
import logging
import sys
from datetime import date

from app.empresas import cargar_empresas
from app.services.conciliacion import meses_rango
from app.services.sunat import SunatClient, edad_cache_horas, ttl_horas

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("refrescar")


def periodos_por_defecto() -> list[str]:
    """El mes en curso y los 2 anteriores: es donde el dato todavía se mueve."""
    h = date.today()
    out = []
    y, m = h.year, h.month
    for _ in range(3):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return sorted(out)


def refrescar_empresa(empresa, periodos: list[str], forzar: bool) -> tuple[int, int, int]:
    ok = fallos = omitidos = 0
    with SunatClient(empresa) as sunat:
        for p in periodos:
            edad = edad_cache_horas(empresa.codigo, p)
            if not forzar and edad is not None and edad < ttl_horas(p):
                log.info("[%s] %s: al día (%.1f h, vence a las %.0f h) — no lo toco",
                         empresa.codigo, p, edad, ttl_horas(p))
                omitidos += 1
                continue
            try:
                sunat.propuesta_rce(p, forzar=forzar)
                log.info("[%s] %s: actualizado", empresa.codigo, p)
                ok += 1
            except Exception as e:  # noqa: BLE001
                log.error("[%s] %s: FALLO — %s", empresa.codigo, p, e)
                fallos += 1
    return ok, omitidos, fallos


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    forzar = "--forzar" in sys.argv
    solo_empresa = None
    if "--empresa" in sys.argv:
        solo_empresa = sys.argv[sys.argv.index("--empresa") + 1]

    periodos = meses_rango(args[0], args[1]) if len(args) == 2 else periodos_por_defecto()

    empresas = cargar_empresas()
    if solo_empresa:
        if solo_empresa not in empresas:
            log.error("Empresa desconocida: %s (disponibles: %s)", solo_empresa, ", ".join(empresas))
            return 1
        empresas = {solo_empresa: empresas[solo_empresa]}

    log.info("Empresas: %s | Periodos: %s%s", ", ".join(empresas), ", ".join(periodos),
             " (forzado)" if forzar else "")

    tot_ok = tot_om = tot_fa = 0
    for cod, emp in empresas.items():
        faltan = emp.campos_faltantes()
        if faltan:
            log.warning("[%s] Empresa incompleta, se salta (falta: %s)", cod, ", ".join(faltan))
            continue
        ok, om, fa = refrescar_empresa(emp, periodos, forzar)
        tot_ok += ok; tot_om += om; tot_fa += fa

    log.info("Listo. Actualizados: %d · Ya al día: %d · Fallos: %d", tot_ok, tot_om, tot_fa)
    return 1 if tot_fa else 0


if __name__ == "__main__":
    raise SystemExit(main())

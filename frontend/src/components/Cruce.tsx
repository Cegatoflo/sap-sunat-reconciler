import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { asignar, obtenerCruce } from "../api";
import { EN_AMBOS, MESES, SOLO_SAP, SOLO_SUNAT, TIPO_CP, etiquetaPeriodo, textoAntiguedad } from "../types";
import type { Estado, Fila, Usuario } from "../types";

const nf = new Intl.NumberFormat("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const PERIODOS: string[] = [];
for (let y = 2025; y <= 2026; y++)
  for (let m = 1; m <= 12; m++) PERIODOS.push(`${y}${String(m).padStart(2, "0")}`);

const CLASE_ESTADO: Record<Estado, string> = { 0: "ok", 1: "sap", 2: "sun" };
const TEXTO_ESTADO: Record<Estado, string> = {
  0: "En ambos",
  1: "Solo SAP",
  2: "Solo SUNAT",
};

export default function Cruce({ yo }: { yo: Usuario }) {
  const qc = useQueryClient();
  const [desde, setDesde] = useState("202606");
  const [hasta, setHasta] = useState("202606");
  const [rango, setRango] = useState({ desde: "202606", hasta: "202606" });

  const [verEstado, setVerEstado] = useState<Record<Estado, boolean>>({ 0: true, 1: true, 2: true });
  const [mesFiltro, setMesFiltro] = useState<string | null>(null);   // periodo "yyyymm" o null = Todos
  const [moneda, setMoneda] = useState("");
  const [busca, setBusca] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [pagina, setPagina] = useState(0);
  const TAM = 100;

  // `refrescar` solo se activa al pulsar "Actualizar datos": la carga normal usa la caché.
  const refrescar = useRef(false);

  const q = useQuery({
    queryKey: ["cruce", rango.desde, rango.hasta],
    queryFn: async () => {
      const forzar = refrescar.current;
      refrescar.current = false;
      return obtenerCruce(rango.desde, rango.hasta, forzar);
    },
  });

  const mAsignar = useMutation({
    mutationFn: (items: unknown[]) => asignar(items),
    onSuccess: (r) => {
      setSel(new Set());
      if (r.tomados_por_otros.length) {
        const quienes = r.tomados_por_otros
          .map((t) => `${t.comprobante} (${t.usuario})`)
          .join(", ");
        alert(
          `Se asignaron ${r.asignados}.\n\n` +
            `No se pudieron tomar ${r.tomados_por_otros.length} porque ya están en la bandeja de otra persona:\n${quienes}`,
        );
      }
      qc.invalidateQueries({ queryKey: ["cruce"] });
      qc.invalidateQueries({ queryKey: ["bandeja"] });
    },
  });

  /** Dato de SUNAT más antiguo del rango cargado. */
  const antiguedad = useMemo(() => {
    const v = Object.values(q.data?.cache_horas ?? {}).filter((h): h is number => h != null);
    return v.length ? Math.max(...v) : null;
  }, [q.data]);

  const mias = useMemo(() => new Set(q.data?.mi_bandeja ?? []), [q.data]);

  // meses (periodos) presentes en el rango YA cargado, para el filtro rápido "Mes"
  const mesesPresentes = useMemo(() => {
    const s = new Set((q.data?.filas ?? []).map((f) => f.periodo));
    return [...s].sort();
  }, [q.data]);

  // al cargar un rango nuevo, el filtro de mes vuelve a "Todos"
  useEffect(() => {
    setMesFiltro(null);
  }, [rango.desde, rango.hasta]);

  const filtradas = useMemo(() => {
    const filas = q.data?.filas ?? [];
    const t = busca.trim().toLowerCase();
    return filas.filter((f) => {
      if (mesFiltro && f.periodo !== mesFiltro) return false;
      if (!verEstado[f.estado]) return false;
      if (moneda && f.moneda !== moneda) return false;
      if (t && !`${f.ruc} ${f.proveedor} ${f.comprobante}`.toLowerCase().includes(t)) return false;
      return true;
    });
  }, [q.data, mesFiltro, verEstado, moneda, busca]);

  // base para los KPIs: todo lo que aplica mes/moneda/búsqueda, SIN el filtro de estado
  // (así el desglose por estado sigue sumando el 100% del total mostrado)
  const base = useMemo(() => {
    const filas = q.data?.filas ?? [];
    const t = busca.trim().toLowerCase();
    return filas.filter((f) => {
      if (mesFiltro && f.periodo !== mesFiltro) return false;
      if (moneda && f.moneda !== moneda) return false;
      if (t && !`${f.ruc} ${f.proveedor} ${f.comprobante}`.toLowerCase().includes(t)) return false;
      return true;
    });
  }, [q.data, mesFiltro, moneda, busca]);

  const conteos = useMemo(() => {
    const c = { 0: 0, 1: 0, 2: 0 } as Record<Estado, number>;
    base.forEach((f) => c[f.estado]++);
    return c;
  }, [base]);

  const paginas = Math.max(1, Math.ceil(filtradas.length / TAM));
  const pag = Math.min(pagina, paginas - 1);
  const visibles = filtradas.slice(pag * TAM, pag * TAM + TAM);
  const total = base.length;
  const pct = (n: number) => (total ? ((100 * n) / total).toFixed(1) + "% del total" : "");

  // solo se pueden asignar los "Solo en SUNAT" que no estén ya en mi bandeja
  const asignables = visibles.filter((f) => f.estado === SOLO_SUNAT && !mias.has(f.clave));

  const alternar = (clave: string) =>
    setSel((s) => {
      const n = new Set(s);
      n.has(clave) ? n.delete(clave) : n.add(clave);
      return n;
    });

  const confirmarAsignacion = () => {
    const filas = (q.data?.filas ?? []).filter((f) => sel.has(f.clave));
    mAsignar.mutate(
      filas.map((f) => ({
        clave: f.clave, periodo: f.periodo, fecha: f.fecha, ruc: f.ruc,
        proveedor: f.proveedor, tipo: f.tipo, comprobante: f.comprobante,
        moneda: f.moneda, total: f.total,
      })),
    );
  };

  return (
    <>
      <div className="kpis">
        <Kpi lbl="Total comprobantes" val={total} />
        <Kpi lbl="En ambos" val={conteos[EN_AMBOS]} sub={pct(conteos[EN_AMBOS])} cls="ok" />
        <Kpi lbl="Solo SAP" val={conteos[SOLO_SAP]} sub={pct(conteos[SOLO_SAP])} cls="sap" />
        <Kpi lbl="Solo SUNAT" val={conteos[SOLO_SUNAT]} sub={pct(conteos[SOLO_SUNAT])} cls="sun" />
      </div>

      <div className="panel">
        <div className="bar">
          <div className="field">
            <label htmlFor="d">Desde</label>
            <select id="d" value={desde} onChange={(e) => setDesde(e.target.value)}>
              {PERIODOS.map((p) => (
                <option key={p} value={p}>{etiquetaPeriodo(p)}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="h">Hasta</label>
            <select id="h" value={hasta} onChange={(e) => setHasta(e.target.value)}>
              {PERIODOS.map((p) => (
                <option key={p} value={p}>{etiquetaPeriodo(p)}</option>
              ))}
            </select>
          </div>
          <button
            className="btn"
            disabled={q.isFetching}
            onClick={() => {
              if (desde > hasta) return alert('El "Desde" no puede ser mayor que el "Hasta".');
              setPagina(0);
              setRango({ desde, hasta });
            }}
          >
            Cargar rango
          </button>

          {/* Trae datos frescos de SUNAT. La carga normal usa la caché para no chocar
              con el rate limit; esto la salta a propósito. */}
          <button
            className="btn ghost"
            disabled={q.isFetching}
            title="Vuelve a descargar la propuesta desde SUNAT (puede tardar)"
            onClick={() => {
              refrescar.current = true;
              qc.invalidateQueries({ queryKey: ["cruce", rango.desde, rango.hasta] });
            }}
          >
            {q.isFetching && refrescar.current ? "Actualizando…" : "↻ Actualizar datos"}
          </button>

          {antiguedad != null && (
            <span className="msg" title="Antigüedad del dato descargado de SUNAT">
              Datos SUNAT: <strong>{textoAntiguedad(antiguedad)}</strong>
            </span>
          )}

          <div className="field" style={{ marginLeft: "auto" }}>
            <label htmlFor="q">Buscar</label>
            <input
              id="q" className="search" placeholder="RUC, proveedor o comprobante…"
              value={busca}
              onChange={(e) => { setBusca(e.target.value); setPagina(0); }}
            />
          </div>
        </div>

        <div className="filters">
          <div className="fgroup">
            <span className="flab">Mes</span>
            <button
              className={`chip ${mesFiltro === null ? "on" : ""}`}
              onClick={() => { setMesFiltro(null); setPagina(0); }}
            >
              Todos
            </button>
            {mesesPresentes.map((p) => (
              <button
                key={p}
                className={`chip ${mesFiltro === p ? "on" : ""}`}
                onClick={() => { setMesFiltro(p); setPagina(0); }}
              >
                {MESES[Number(p.slice(4)) - 1]}
              </button>
            ))}
          </div>
          <div className="fgroup">
            <span className="flab">Estado</span>
            {([0, 1, 2] as Estado[]).map((e) => (
              <button
                key={e}
                className={`chip ${CLASE_ESTADO[e]} ${verEstado[e] ? "on" : ""}`}
                onClick={() => { setVerEstado((v) => ({ ...v, [e]: !v[e] })); setPagina(0); }}
              >
                {TEXTO_ESTADO[e]}
              </button>
            ))}
          </div>
          <div className="fgroup">
            <span className="flab">Moneda</span>
            <select value={moneda} onChange={(e) => { setMoneda(e.target.value); setPagina(0); }}>
              <option value="">Todas</option>
              <option>PEN</option>
              <option>USD</option>
            </select>
          </div>
        </div>

        {sel.size > 0 && (
          <div className="actionbar">
            <span className="cnt">{sel.size} seleccionado{sel.size === 1 ? "" : "s"}</span>
            <button className="btn" disabled={mAsignar.isPending} onClick={confirmarAsignacion}>
              {mAsignar.isPending ? "Asignando…" : "Asignar a mi bandeja"}
            </button>
            <button className="btn ghost" onClick={() => setSel(new Set())}>Limpiar selección</button>
            {mAsignar.isError && <span className="msg">Error: {(mAsignar.error as Error).message}</span>}
          </div>
        )}

        <div className="tablewrap">
          {q.isError && <div className="empty">Error: {(q.error as Error).message}</div>}
          {!q.isError && (
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      title="Seleccionar los Solo-SUNAT visibles"
                      checked={asignables.length > 0 && asignables.every((f) => sel.has(f.clave))}
                      onChange={(e) =>
                        setSel((s) => {
                          const n = new Set(s);
                          asignables.forEach((f) => (e.target.checked ? n.add(f.clave) : n.delete(f.clave)));
                          return n;
                        })
                      }
                    />
                  </th>
                  <th>Estado</th><th>Fecha</th><th>RUC</th><th>Proveedor</th>
                  <th>Tipo</th><th>Comprobante</th><th>Mon.</th>
                  <th style={{ textAlign: "right" }}>Total</th>
                  <th style={{ textAlign: "right" }}>Doc. SAP</th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((f: Fila) => {
                  const mia = mias.has(f.clave);
                  const duenos = yo.rol === "manager" ? q.data?.asignaciones[f.clave] : undefined;
                  return (
                    <tr key={f.clave} className={`e${f.estado} ${mia ? "mia" : ""}`}>
                      <td className="chk">
                        {f.estado === SOLO_SUNAT && (
                          <input
                            type="checkbox"
                            checked={sel.has(f.clave)}
                            disabled={mia}
                            title={mia ? "Ya está en tu bandeja" : undefined}
                            onChange={() => alternar(f.clave)}
                          />
                        )}
                      </td>
                      <td>
                        {mia ? (
                          <span className="pill mine">Mi bandeja</span>
                        ) : (
                          <span className={`pill ${CLASE_ESTADO[f.estado]}`}>{TEXTO_ESTADO[f.estado]}</span>
                        )}{" "}
                        {duenos?.map((d) => (
                          <span key={d.usuario} className="owner" title={d.estado}>{d.usuario}</span>
                        ))}
                      </td>
                      <td>{f.fecha}</td>
                      <td className="ruc">{f.ruc}</td>
                      <td className="prov">{f.proveedor}</td>
                      <td><span className="tag">{TIPO_CP[f.tipo] ?? f.tipo}</span></td>
                      <td className="cmp">{f.comprobante}</td>
                      <td>{f.moneda}</td>
                      <td className="num">{nf.format(f.total)}</td>
                      <td className="num">{f.docnum_sap ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {!q.isLoading && !q.isError && filtradas.length === 0 && (
            <div className="empty">Sin resultados para el filtro actual.</div>
          )}
        </div>

        <div className="foot">
          <div className="legend">
            <span className="item"><span className="sw ok" /> En ambos</span>
            <span className="item"><span className="sw sap" /> Solo en SAP</span>
            <span className="item"><span className="sw sun" /> Solo en SUNAT (libre)</span>
            <span className="item"><span className="sw mine" /> En mi bandeja</span>
            {yo.rol !== "manager" && (
              <span className="item msg">
                · Lo que otra persona ya apartó no aparece aquí
              </span>
            )}
          </div>
          <div className="fgroup">
            <button className="btn ghost" disabled={pag <= 0} onClick={() => setPagina(pag - 1)}>‹ Anterior</button>
            <span className="msg">
              {filtradas.length
                ? `${pag * TAM + 1}–${Math.min((pag + 1) * TAM, filtradas.length)} de ${filtradas.length.toLocaleString("es-PE")}`
                : "0"}
            </span>
            <button className="btn ghost" disabled={pag >= paginas - 1} onClick={() => setPagina(pag + 1)}>Siguiente ›</button>
          </div>
        </div>

        {q.isFetching && (
          <div className="overlay">
            <div className="spin" />
            <div className="msg">Consultando SAP y SUNAT…</div>
          </div>
        )}
      </div>
    </>
  );
}

function Kpi({ lbl, val, sub = "", cls = "" }: { lbl: string; val: number; sub?: string; cls?: string }) {
  return (
    <div className={`kpi ${cls}`}>
      <div className="lbl">{lbl}</div>
      <div className="val">{val.toLocaleString("es-PE")}</div>
      <div className="sub">{sub}</div>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { cambiarEstado, liberar, obtenerBandeja, revocar } from "../api";
import { TIPO_CP, etiquetaPeriodo } from "../types";
import type { ItemBandeja, Usuario } from "../types";

const nf = new Intl.NumberFormat("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** id de selección: un mismo comprobante puede estar en la bandeja de varias personas. */
const sid = (i: ItemBandeja) => `${i.clave}||${i.usuario}`;

export default function Bandeja({ yo, gestion }: { yo: Usuario; gestion: boolean }) {
  const qc = useQueryClient();
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [fUser, setFUser] = useState("");
  const [fEstado, setFEstado] = useState("");
  const [fPeriodo, setFPeriodo] = useState("");
  const [busca, setBusca] = useState("");

  const q = useQuery({
    queryKey: ["bandeja", gestion],
    queryFn: () => obtenerBandeja(gestion),
  });

  const tras = () => {
    setSel(new Set());
    qc.invalidateQueries({ queryKey: ["bandeja"] });
    qc.invalidateQueries({ queryKey: ["cruce"] });
  };
  const mEstado = useMutation({ mutationFn: (c: string[]) => cambiarEstado(c, "registrada"), onSuccess: tras });
  const mLiberar = useMutation({ mutationFn: (c: string[]) => liberar(c), onSuccess: tras });
  const mRevocar = useMutation({
    mutationFn: (p: { clave: string; usuario: string }[]) => revocar(p),
    onSuccess: tras,
  });

  const items = q.data ?? [];
  const usuarios = useMemo(() => [...new Set(items.map((i) => i.usuario))].sort(), [items]);
  const periodos = useMemo(() => [...new Set(items.map((i) => i.periodo))].sort(), [items]);

  const filtrados = useMemo(() => {
    const t = busca.trim().toLowerCase();
    return items.filter((i) => {
      if (fUser && i.usuario !== fUser) return false;
      if (fEstado && i.estado !== fEstado) return false;
      if (fPeriodo && i.periodo !== fPeriodo) return false;
      if (t && !`${i.ruc} ${i.proveedor} ${i.comprobante}`.toLowerCase().includes(t)) return false;
      return true;
    });
  }, [items, fUser, fEstado, fPeriodo, busca]);

  const pendientes = filtrados.filter((i) => i.estado === "pendiente").length;
  const pares = () =>
    [...sel].map((s) => {
      const [clave, usuario] = s.split("||");
      return { clave, usuario };
    });

  return (
    <>
      <div className="kpis">
        <Kpi lbl={gestion ? "Asignaciones" : "En mi bandeja"} val={filtrados.length} cls="mine" />
        <Kpi lbl="Pendientes" val={pendientes} cls="sun" />
        <Kpi lbl="Registradas" val={filtrados.length - pendientes} cls="ok" />
        <Kpi lbl="Usuarios" val={new Set(filtrados.map((i) => i.usuario)).size} />
      </div>

      <div className="panel">
        <div className="bar">
          <strong>{gestion ? "Gestión — todas las asignaciones" : "Mi bandeja de trabajo"}</strong>
          <span className="msg">
            {gestion
              ? `${filtrados.length} asignación(es) · ${new Set(filtrados.map((i) => i.usuario)).size} usuario(s)`
              : `${filtrados.length} comprobante(s) asignados a ti`}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            {!gestion && (
              <>
                <button className="btn" disabled={!sel.size || mEstado.isPending}
                  onClick={() => mEstado.mutate(pares().map((p) => p.clave))}>
                  Marcar como registrada
                </button>
                <button className="btn ghost" disabled={!sel.size || mLiberar.isPending}
                  onClick={() => {
                    if (confirm(`¿Quitar ${sel.size} comprobante(s) de tu bandeja?`))
                      mLiberar.mutate(pares().map((p) => p.clave));
                  }}>
                  Quitar de mi bandeja
                </button>
              </>
            )}
            {gestion && yo.rol === "manager" && (
              <button className="btn" disabled={!sel.size || mRevocar.isPending}
                onClick={() => {
                  const p = pares();
                  const quienes = [...new Set(p.map((x) => x.usuario))].join(", ");
                  if (confirm(`¿Quitar ${p.length} asignación(es) a: ${quienes}?`)) mRevocar.mutate(p);
                }}>
                Quitar asignación al usuario
              </button>
            )}
          </div>
        </div>

        <div className="filters">
          {gestion && (
            <div className="fgroup">
              <span className="flab">Usuario</span>
              <select value={fUser} onChange={(e) => setFUser(e.target.value)}>
                <option value="">Todos</option>
                {usuarios.map((u) => <option key={u}>{u}</option>)}
              </select>
            </div>
          )}
          <div className="fgroup">
            <span className="flab">Estado</span>
            <select value={fEstado} onChange={(e) => setFEstado(e.target.value)}>
              <option value="">Todos</option>
              <option value="pendiente">Pendiente</option>
              <option value="registrada">Registrada</option>
            </select>
          </div>
          <div className="fgroup">
            <span className="flab">Periodo</span>
            <select value={fPeriodo} onChange={(e) => setFPeriodo(e.target.value)}>
              <option value="">Todos</option>
              {periodos.map((p) => <option key={p} value={p}>{etiquetaPeriodo(p)}</option>)}
            </select>
          </div>
          <div className="fgroup" style={{ marginLeft: "auto" }}>
            <input className="search" placeholder="RUC, proveedor o comprobante…"
              value={busca} onChange={(e) => setBusca(e.target.value)} />
          </div>
        </div>

        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>
                  <input type="checkbox"
                    checked={filtrados.length > 0 && filtrados.every((i) => sel.has(sid(i)))}
                    onChange={(e) =>
                      setSel(() => (e.target.checked ? new Set(filtrados.map(sid)) : new Set()))
                    } />
                </th>
                <th>Estado</th>
                {gestion && <th>Usuario</th>}
                <th>Periodo</th><th>Fecha</th><th>RUC</th><th>Proveedor</th>
                <th>Tipo</th><th>Comprobante</th><th>Mon.</th>
                <th style={{ textAlign: "right" }}>Total</th><th>Asignada</th>
              </tr>
            </thead>
            <tbody>
              {filtrados.map((i) => (
                <tr key={sid(i)}>
                  <td className="chk">
                    <input type="checkbox" checked={sel.has(sid(i))}
                      onChange={() =>
                        setSel((s) => {
                          const n = new Set(s);
                          n.has(sid(i)) ? n.delete(sid(i)) : n.add(sid(i));
                          return n;
                        })
                      } />
                  </td>
                  <td>
                    <span className={`pill ${i.estado === "registrada" ? "ok" : "sun"}`}>
                      {i.estado === "registrada" ? "Registrada" : "Pendiente"}
                    </span>
                  </td>
                  {gestion && <td><span className="owner">{i.usuario}</span></td>}
                  <td>{etiquetaPeriodo(i.periodo)}</td>
                  <td>{i.fecha}</td>
                  <td className="ruc">{i.ruc}</td>
                  <td className="prov">{i.proveedor}</td>
                  <td><span className="tag">{TIPO_CP[i.tipo] ?? i.tipo}</span></td>
                  <td className="cmp">{i.comprobante}</td>
                  <td>{i.moneda}</td>
                  <td className="num">{nf.format(i.total)}</td>
                  <td>{i.asignada?.slice(0, 16).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!q.isLoading && filtrados.length === 0 && (
            <div className="empty">
              {gestion
                ? "No hay asignaciones."
                : "Tu bandeja está vacía. Ve a Cruce, filtra por “Solo en SUNAT” y asígnate los comprobantes que vas a registrar."}
            </div>
          )}
        </div>

        {q.isFetching && (
          <div className="overlay"><div className="spin" /></div>
        )}
      </div>
    </>
  );
}

function Kpi({ lbl, val, cls = "" }: { lbl: string; val: number; cls?: string }) {
  return (
    <div className={`kpi ${cls}`}>
      <div className="lbl">{lbl}</div>
      <div className="val">{val.toLocaleString("es-PE")}</div>
      <div className="sub" />
    </div>
  );
}

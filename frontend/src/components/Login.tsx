import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { login, obtenerEmpresas } from "../api";
import type { Usuario } from "../types";

export default function Login({ onEntrar }: { onEntrar: (u: Usuario) => void }) {
  const [empresa, setEmpresa] = useState("");
  const [usuario, setUsuario] = useState("");
  const [clave, setClave] = useState("");

  const empresas = useQuery({ queryKey: ["empresas"], queryFn: obtenerEmpresas });

  // preselecciona la primera empresa en cuanto llega la lista
  useEffect(() => {
    if (!empresa && empresas.data?.length) setEmpresa(empresas.data[0].codigo);
  }, [empresas.data, empresa]);

  const m = useMutation({
    mutationFn: () => login(empresa, usuario, clave),
    onSuccess: (u) => {
      setClave("");
      onEntrar(u);
    },
  });

  return (
    <div className="login">
      <form
        className="lcard"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <h1>Conciliación SAP ↔ SUNAT</h1>
        <p className="sub">
          Ingresa con tu usuario de <strong>SAP Business One</strong>
        </p>

        {m.isError && <div className="err">{(m.error as Error).message}</div>}
        {empresas.isError && (
          <div className="err">No se pudo cargar la lista de empresas. Recarga la página.</div>
        )}

        <div className="field">
          <label htmlFor="empresa">Empresa</label>
          <select
            id="empresa"
            value={empresa}
            onChange={(e) => setEmpresa(e.target.value)}
            disabled={empresas.isLoading || !empresas.data?.length}
            required
          >
            {empresas.isLoading && <option>Cargando…</option>}
            {empresas.data?.map((e) => (
              <option key={e.codigo} value={e.codigo}>{e.nombre}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="usuario">Usuario SAP</label>
          <input
            id="usuario"
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </div>

        <div className="field">
          <label htmlFor="clave">Contraseña SAP</label>
          <input
            id="clave"
            type="password"
            value={clave}
            onChange={(e) => setClave(e.target.value)}
            autoComplete="current-password"
            required
          />
        </div>

        <button className="btn full" disabled={m.isPending || !empresa}>
          {m.isPending ? "Validando con SAP…" : "Ingresar"}
        </button>

        <p className="lnote">
          El usuario y la clave son siempre los mismos de SAP; lo único que cambia según la empresa
          elegida es la base de datos contra la que se validan. Tus credenciales se validan
          directamente contra el Service Layer de SAP. El sistema{" "}
          <strong>no almacena tu contraseña</strong>: en la sesión solo queda tu nombre de usuario.
          Acceso restringido al área de Contabilidad.
        </p>
      </form>
    </div>
  );
}

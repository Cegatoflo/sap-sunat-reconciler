import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { logout, obtenerBandeja, sesionActual } from "./api";
import Bandeja from "./components/Bandeja";
import Cruce from "./components/Cruce";
import Login from "./components/Login";
import type { Usuario } from "./types";

type Vista = "cruce" | "bandeja" | "gestion";

export default function App() {
  const qc = useQueryClient();
  const [vista, setVista] = useState<Vista>("cruce");
  const [saliendo, setSaliendo] = useState(false);

  const sesion = useQuery({ queryKey: ["sesion"], queryFn: sesionActual });

  // contador de "Mi bandeja" en la pestaña
  const mia = useQuery({
    queryKey: ["bandeja", false],
    queryFn: () => obtenerBandeja(false),
    enabled: !!sesion.data,
  });

  if (sesion.isLoading) return <div className="login"><div className="spin" /></div>;

  const yo = sesion.data;
  if (!yo) {
    return <Login onEntrar={(u: Usuario) => qc.setQueryData(["sesion"], u)} />;
  }

  const salir = async () => {
    setSaliendo(true);
    try {
      await logout();
    } catch {
      // aunque falle la llamada al backend (red, etc.), igual cerramos la sesión en el cliente
    } finally {
      // Ojo: NUNCA usar qc.clear() aquí — borra también la propia query "sesion", y como
      // el useQuery(["sesion"]) sigue montado, dispara un refetch que compite con este
      // setQueryData y puede "revivir" la sesión visualmente. Solo limpiamos lo demás.
      qc.setQueryData(["sesion"], null);
      qc.removeQueries({ queryKey: ["bandeja"] });
      qc.removeQueries({ queryKey: ["cruce"] });
      setSaliendo(false);
    }
  };

  return (
    <div className="wrap">
      <header className="top">
        <div>
          <h1>Conciliación de Compras · SAP ↔ SUNAT</h1>
          <p>
            <span className="accent">{yo.empresa_nombre}</span> · Registro de Compras (RCE) ·
            proveedores nacionales
          </p>
        </div>
        <div className="user">
          <span className="who">
            {yo.nombre} ({yo.usuario})
          </span>
          <span className={`rol ${yo.rol === "manager" ? "mgr" : ""}`}>{yo.rol}</span>
          <button className="btn ghost" onClick={salir} disabled={saliendo}>
            {saliendo ? "Saliendo…" : "Salir"}
          </button>
        </div>
      </header>

      <div className="tabs">
        <button className={`tab ${vista === "cruce" ? "on" : ""}`} onClick={() => setVista("cruce")}>
          Cruce
        </button>
        <button className={`tab ${vista === "bandeja" ? "on" : ""}`} onClick={() => setVista("bandeja")}>
          Mi bandeja <span className="badge">{mia.data?.length ?? 0}</span>
        </button>
        {yo.rol === "manager" && (
          <button className={`tab ${vista === "gestion" ? "on" : ""}`} onClick={() => setVista("gestion")}>
            Gestión
          </button>
        )}
      </div>

      {vista === "cruce" && <Cruce yo={yo} />}
      {vista === "bandeja" && <Bandeja yo={yo} gestion={false} />}
      {vista === "gestion" && yo.rol === "manager" && <Bandeja yo={yo} gestion />}
    </div>
  );
}

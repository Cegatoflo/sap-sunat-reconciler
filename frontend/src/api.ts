import type { Cruce, Empresa, ItemBandeja, ResultadoAsignar, Usuario } from "./types";

/** Error con el mensaje que devuelve el backend (campo `detail` de FastAPI). */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function pedir<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    credentials: "include", // manda la cookie de sesión
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!r.ok) {
    let msg = `Error ${r.status}`;
    try {
      const d = await r.json();
      if (typeof d.detail === "string") msg = d.detail;
      else if (Array.isArray(d.detail)) msg = d.detail[0]?.msg ?? msg;
    } catch {
      /* respuesta sin JSON */
    }
    throw new ApiError(msg, r.status);
  }
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T);
}

// ---------- sesión ----------
/** Lista pública de empresas para el selector del login (código + nombre, sin credenciales). */
export const obtenerEmpresas = () => pedir<Empresa[]>("/api/empresas");

export const login = (empresa: string, usuario: string, clave: string) =>
  pedir<Usuario>("/api/login", {
    method: "POST",
    body: JSON.stringify({ empresa, usuario, clave }),
  });

export const logout = () => pedir<{ ok: boolean }>("/api/logout", { method: "POST" });

export async function sesionActual(): Promise<Usuario | null> {
  const d = await pedir<{ ok: boolean } & Partial<Usuario>>("/api/sesion");
  return d.ok
    ? ({
        usuario: d.usuario!, nombre: d.nombre!, rol: d.rol!,
        empresa: d.empresa!, empresa_nombre: d.empresa_nombre!,
      } as Usuario)
    : null;
}

// ---------- cruce ----------
/** `refrescar` fuerza la descarga desde SUNAT (ignora la caché). Úsalo con criterio. */
export const obtenerCruce = (desde: string, hasta: string, refrescar = false) =>
  pedir<Cruce>(`/api/cruce?desde=${desde}&hasta=${hasta}${refrescar ? "&refrescar=true" : ""}`);

// ---------- bandeja ----------
export const obtenerBandeja = (todos = false) =>
  pedir<ItemBandeja[]>(`/api/bandeja${todos ? "?todos=true" : ""}`);

export const asignar = (items: unknown[]) =>
  pedir<ResultadoAsignar>("/api/bandeja/asignar", {
    method: "POST",
    body: JSON.stringify(items),
  });

export const liberar = (claves: string[]) =>
  pedir<{ liberados: number }>("/api/bandeja/liberar", {
    method: "POST",
    body: JSON.stringify({ claves }),
  });

export const cambiarEstado = (claves: string[], estado: "pendiente" | "registrada") =>
  pedir<{ actualizados: number }>("/api/bandeja/estado", {
    method: "POST",
    body: JSON.stringify({ claves, estado }),
  });

/** Solo manager: le quita la asignación a la persona que la tiene. */
export const revocar = (pares: { clave: string; usuario: string }[]) =>
  pedir<{ revocados: number }>("/api/bandeja/revocar", {
    method: "POST",
    body: JSON.stringify({ pares }),
  });

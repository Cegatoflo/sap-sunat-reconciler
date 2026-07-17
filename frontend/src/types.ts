/** Estado del cruce de un comprobante. */
export const EN_AMBOS = 0;
export const SOLO_SAP = 1;
export const SOLO_SUNAT = 2;

export type Estado = typeof EN_AMBOS | typeof SOLO_SAP | typeof SOLO_SUNAT;

export interface Usuario {
  usuario: string;
  nombre: string;
  rol: "analista" | "manager";
  empresa: string;
  empresa_nombre: string;
}

export interface Empresa {
  codigo: string;
  nombre: string;
}

export interface Fila {
  clave: string;
  periodo: string;
  estado: Estado;
  fecha: string;
  ruc: string;
  proveedor: string;
  tipo: string;
  comprobante: string;
  moneda: string;
  total: number;
  docnum_sap: number | null;
}

export interface Asignado {
  usuario: string;
  estado: string;
}

export interface Cruce {
  desde: string;
  hasta: string;
  filas: Fila[];
  mi_bandeja: string[];
  asignaciones: Record<string, Asignado[]>;
  /** Antigüedad del dato de SUNAT, en horas, por periodo. */
  cache_horas: Record<string, number | null>;
}

export interface ResultadoAsignar {
  asignados: number;
  ya_mios: number;
  tomados_por_otros: { comprobante: string; usuario: string }[];
  recibidos: number;
}

/** "3.7" -> "hace 3 h" · "0.3" -> "hace 18 min" */
export function textoAntiguedad(horas: number | null | undefined): string {
  if (horas == null) return "sin datos";
  if (horas < 1) return `hace ${Math.max(1, Math.round(horas * 60))} min`;
  if (horas < 48) return `hace ${Math.round(horas)} h`;
  return `hace ${Math.round(horas / 24)} d`;
}

export interface ItemBandeja {
  clave: string;
  usuario: string;
  periodo: string;
  fecha: string;
  ruc: string;
  proveedor: string;
  tipo: string;
  comprobante: string;
  moneda: string;
  total: number;
  estado: "pendiente" | "registrada";
  asignada: string;
}

export const TIPO_CP: Record<string, string> = {
  "01": "Factura",
  "07": "N. Crédito",
  "08": "N. Débito",
  "50": "DAM",
};

export const MESES = [
  "Ene", "Feb", "Mar", "Abr", "May", "Jun",
  "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
];

/** "202606" -> "Jun 2026" */
export function etiquetaPeriodo(p: string): string {
  return `${MESES[Number(p.slice(4)) - 1]} ${p.slice(0, 4)}`;
}

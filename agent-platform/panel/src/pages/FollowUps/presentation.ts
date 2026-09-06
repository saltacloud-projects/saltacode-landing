import type { FollowUpKind, FollowUpStatus } from "./types";

export const STATUS_LABELS: Record<FollowUpStatus, string> = {
  scheduled: "Programado",
  dispatch_queued: "Entrega en cola",
  in_progress: "En ejecución",
  completed: "Completado",
  cancelled: "Cancelado",
  review_required: "Revisión requerida",
};

export const KIND_LABELS: Record<FollowUpKind, string> = {
  commercial_follow_up: "Seguimiento comercial",
  meeting_coordination: "Coordinación de reunión",
  proposal_reminder: "Recordatorio de presupuesto",
};

const OUTBOUND_STATUS_LABELS: Record<string, string> = {
  queued: "En cola",
  processing: "En preparación",
  accepted: "Aceptada por el proveedor",
  sent: "Enviada",
  delivered: "Entregada",
  read: "Leída",
  failed: "Fallida",
  cancelled: "Cancelada",
  delivery_unknown: "Resultado incierto",
};

const ACTOR_LABELS: Record<string, string> = {
  agent: "agente",
  admin: "operador",
  worker: "worker automático",
  system: "sistema",
};

export function statusTone(status: FollowUpStatus): string {
  if (status === "completed") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-400";
  }
  if (status === "review_required") {
    return "border-[var(--error)]/40 bg-[var(--error)]/10 text-[var(--error)]";
  }
  if (status === "dispatch_queued" || status === "in_progress") {
    return "border-[var(--warning)]/40 bg-[var(--warning)]/10 text-[var(--warning)]";
  }
  return "border-[var(--border-color)] bg-[var(--bg-hover)] text-[var(--text-secondary)]";
}

export function dateTime(value: string | null): string {
  if (!value) return "No registrado";
  return new Intl.DateTimeFormat("es-AR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function shortId(value: string): string {
  return value.slice(0, 8);
}

export function outboundStatus(value: string | null): string {
  if (!value) return "Todavía no creada";
  return OUTBOUND_STATUS_LABELS[value] ?? `Estado técnico: ${value}`;
}

export function actorType(value: string): string {
  return ACTOR_LABELS[value] ?? value;
}

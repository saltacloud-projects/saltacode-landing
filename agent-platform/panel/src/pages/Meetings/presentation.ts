import type { MeetingStatus } from "./types";

export const STATUS_LABELS: Record<MeetingStatus, string> = {
  requested: "Solicitada",
  slots_proposed: "Horarios propuestos",
  awaiting_response: "Esperando respuesta",
  slot_selected: "Horario elegido",
  calendar_pending: "Estado no operable",
  scheduled: "Confirmada",
  reschedule_requested: "Reprogramación solicitada",
  cancelled: "Cancelada",
  review_required: "Revisión requerida",
};

export function statusTone(status: MeetingStatus): string {
  if (status === "scheduled") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-400";
  }
  if (status === "cancelled") {
    return "border-[var(--border-color)] bg-[var(--bg-hover)] text-[var(--text-muted)]";
  }
  if (status === "review_required" || status === "calendar_pending") {
    return "border-[var(--error)]/40 bg-[var(--error)]/10 text-[var(--error)]";
  }
  if (status === "awaiting_response" || status === "reschedule_requested") {
    return "border-[var(--warning)]/40 bg-[var(--warning)]/10 text-[var(--warning)]";
  }
  return "border-[var(--accent)]/40 bg-[var(--accent)]/10 text-[var(--accent-hover)]";
}

export function dateTime(value: string): string {
  return new Intl.DateTimeFormat("es-AR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function slotTime(startsAt: string, endsAt: string, timezone: string): string {
  const formatter = new Intl.DateTimeFormat("es-AR", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  });
  return `${formatter.format(new Date(startsAt))} – ${formatter.format(new Date(endsAt))}`;
}

export function shortId(value: string): string {
  return value.slice(0, 8);
}

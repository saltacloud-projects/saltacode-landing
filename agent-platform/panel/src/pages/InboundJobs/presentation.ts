import type { InboundJobStatus } from "./types";

export const STATUS_LABELS: Record<InboundJobStatus, string> = {
  queued: "En cola",
  processing: "Procesando",
  completed: "Completado",
  routed_to_human: "Derivado a una persona",
  ignored: "Reconocido y descartado",
  review_required: "Revisión requerida",
  cancelled: "Cancelado",
};

const PHASE_LABELS: Record<string, string> = {
  accepted: "Aceptado",
  legacy_quarantined: "Ingreso anterior aislado",
  claimed: "Tomado por un worker",
  normalized: "Normalizado",
  routed: "Enrutado",
  replied: "Respuesta emitida",
  terminal: "Finalizado",
};

const ACTOR_LABELS: Record<string, string> = {
  system: "sistema",
  worker: "worker automático",
  operator: "operador",
};

export function statusTone(status: InboundJobStatus): string {
  if (status === "completed" || status === "routed_to_human") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-400";
  }
  if (status === "review_required") {
    return "border-[var(--error)]/40 bg-[var(--error)]/10 text-[var(--error)]";
  }
  if (status === "queued" || status === "processing") {
    return "border-[var(--warning)]/40 bg-[var(--warning)]/10 text-[var(--warning)]";
  }
  return "border-[var(--border-color)] bg-[var(--bg-hover)] text-[var(--text-secondary)]";
}

export function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? `Fase técnica: ${phase}`;
}

export function actorLabel(actor: string): string {
  return ACTOR_LABELS[actor] ?? actor;
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

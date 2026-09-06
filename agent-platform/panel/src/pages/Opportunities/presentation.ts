import type { FollowUpKind, FollowUpStatus, OpportunityStage, QuoteRequestStatus } from "./types";

export const STAGE_LABELS: Record<OpportunityStage, string> = {
  new: "Nueva",
  qualified: "Calificada",
  proposal_requested: "Presupuesto solicitado",
  proposal_preparing: "Presupuesto en preparación",
  proposal_sent: "Presupuesto enviado",
  negotiation: "Negociación",
  meeting_scheduled: "Reunión programada",
  won: "Ganada",
  lost: "Perdida",
  paused: "Pausada",
};

export const FOLLOW_UP_KIND_LABELS: Record<FollowUpKind, string> = {
  commercial_follow_up: "Seguimiento comercial",
  meeting_coordination: "Coordinar reunión",
  proposal_reminder: "Recordatorio de presupuesto",
};

export const FOLLOW_UP_STATUS_LABELS: Record<FollowUpStatus, string> = {
  scheduled: "Programada",
  in_progress: "En curso",
  completed: "Completada",
  cancelled: "Cancelada",
  review_required: "Revisión necesaria",
};

export const QUOTE_STATUS_LABELS: Record<QuoteRequestStatus, string> = {
  unavailable: "Proveedor no disponible",
  review_required: "Revisión necesaria",
  issued: "Versión autoritativa registrada",
  cancelled: "Cancelada",
};

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("es-AR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function stageTone(stage: OpportunityStage): string {
  if (stage === "won") return "border-green-500/35 bg-green-500/10 text-green-400";
  if (stage === "lost") return "border-red-500/35 bg-red-500/10 text-red-400";
  if (stage === "paused") return "border-amber-500/35 bg-amber-500/10 text-amber-300";
  return "border-[var(--accent)]/35 bg-[var(--accent)]/10 text-[var(--accent-hover)]";
}

export function contactName(contact: {
  display_name: string | null;
  company_name: string | null;
  principal_id: string;
}): string {
  return (
    contact.display_name || contact.company_name || `Contacto ${contact.principal_id.slice(0, 8)}`
  );
}

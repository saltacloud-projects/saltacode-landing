import type {
  ConversationControlMode,
  InboxConversation,
  InboxMessage,
  MessageAuthorType,
} from "../../inbox/types";

export const CONTROL_LABELS: Record<ConversationControlMode, string> = {
  automated: "Automático",
  paused: "Pausado",
  human: "Atención manual",
  closed: "Cerrado",
};

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("es-AR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function controlTone(mode: ConversationControlMode): string {
  if (mode === "human") return "border-pink-500/35 bg-pink-500/10 text-pink-300";
  if (mode === "paused") return "border-amber-500/35 bg-amber-500/10 text-amber-300";
  if (mode === "closed") return "border-slate-500/35 bg-slate-500/10 text-slate-300";
  return "border-emerald-500/35 bg-emerald-500/10 text-emerald-300";
}

export function conversationName(conversation: InboxConversation): string {
  return conversation.display_name || `Visitante ${conversation.principal_id.slice(0, 8)}`;
}

export function calendarDay(value: string): string {
  const date = new Date(value);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

export function dayLabel(value: string, now = new Date()): string {
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (calendarDay(value) === calendarDay(now.toISOString())) return "Hoy";
  if (calendarDay(value) === calendarDay(yesterday.toISOString())) return "Ayer";
  return new Intl.DateTimeFormat("es-AR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(value));
}

export function messageTime(value: string): string {
  return new Intl.DateTimeFormat("es-AR", { hour: "2-digit", minute: "2-digit" }).format(
    new Date(value),
  );
}

export function listMessageTime(value: string): string {
  const label = dayLabel(value);
  if (label === "Hoy") return messageTime(value);
  if (label === "Ayer") return label;
  return new Intl.DateTimeFormat("es-AR", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
  }).format(new Date(value));
}

export function messageAuthor(message: InboxMessage): MessageAuthorType {
  return (
    message.author_type ??
    (message.role === "user" ? "visitor" : message.origin === "operator" ? "operator" : "unknown")
  );
}

export const AUTHOR_LABELS: Record<MessageAuthorType, string> = {
  visitor: "Visitante",
  agent: "Agente",
  operator: "Operador",
  system: "Sistema",
  unknown: "SaltaCode",
};

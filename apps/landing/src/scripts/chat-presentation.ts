import type { ChatTranscriptMessage } from "./chat-transcript";

export type ChatAuthorType = "visitor" | "agent" | "operator" | "system" | "unknown";

export function parseChatAuthor(value: unknown): ChatAuthorType | undefined {
  return value === "visitor" || value === "agent" || value === "operator" ||
    value === "system" || value === "unknown" ? value : undefined;
}

export function chatAuthorLabel(message: Pick<ChatTranscriptMessage, "role" | "authorType">): string {
  if (message.role === "user") return "Vos";
  if (message.authorType === "agent") return "Asistente IA";
  if (message.authorType === "operator") return "Operador";
  if (message.authorType === "system") return "Sistema";
  return "SaltaCode";
}

export function chatMessageStatus(message: Pick<ChatTranscriptMessage, "role" | "state">): string {
  if (message.state === "error") return "No completado";
  if (message.role !== "user") return "";
  return message.state === "pending" ? "Enviando…" : "Recibido";
}

export function chatMessageTime(createdAt: string): { label: string; title: string } | null {
  const date = new Date(createdAt);
  if (!Number.isFinite(date.getTime())) return null;
  return {
    label: date.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" }),
    title: date.toLocaleString("es-AR", { dateStyle: "medium", timeStyle: "short" }),
  };
}

import type { ChatControlMode } from "./chat-transcript";

export interface ChatActivity {
  status: "queued" | "running";
}

export function parseChatActivity(value: unknown): ChatActivity | null {
  if (!value || typeof value !== "object") return null;
  const status = (value as { status?: unknown }).status;
  return status === "queued" || status === "running" ? { status } : null;
}

export function chatActivityLabel(activity: ChatActivity | null, mode: ChatControlMode): string {
  if (mode !== "automated" || !activity) return "";
  return activity.status === "running"
    ? "El asistente IA está preparando una respuesta…"
    : "Tu mensaje está en espera para ser atendido.";
}

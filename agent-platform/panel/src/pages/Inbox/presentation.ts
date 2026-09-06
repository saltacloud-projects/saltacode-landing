import type { ConversationControlMode } from "../../inbox/types";

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

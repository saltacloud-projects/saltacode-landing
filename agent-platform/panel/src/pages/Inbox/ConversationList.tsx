import { LoaderCircle } from "lucide-react";
import type { InboxConversation } from "../../inbox/types";
import { CONTROL_LABELS, controlTone, formatDate } from "./presentation";

interface ConversationListProps {
  items: InboxConversation[];
  selectedId?: string;
  loading: boolean;
  hiddenOnMobile: boolean;
  onSelect: (conversation: InboxConversation) => void;
}

export function ConversationList({
  items,
  selectedId,
  loading,
  hiddenOnMobile,
  onSelect,
}: ConversationListProps) {
  return (
    <section
      aria-label="Conversaciones"
      className={`${hiddenOnMobile ? "hidden lg:block" : "block"} overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]`}
    >
      {loading ? (
        <p className="flex items-center gap-2 p-4 text-sm text-[var(--text-muted)]" role="status">
          <LoaderCircle className="animate-spin" size={16} /> Cargando…
        </p>
      ) : (
        <div className="max-h-[72vh] divide-y divide-[var(--border-color)] overflow-y-auto">
          {items.map((item) => (
            <button
              type="button"
              key={item.id}
              onClick={() => onSelect(item)}
              aria-pressed={selectedId === item.id}
              className={`w-full p-4 text-left transition-colors hover:bg-[var(--bg-hover)] ${selectedId === item.id ? "bg-[var(--bg-hover)]" : ""}`}
            >
              <div className="flex items-start gap-2">
                <strong className="min-w-0 flex-1 truncate text-sm">
                  {item.display_name || `Visitante ${item.principal_id.slice(0, 8)}`}
                </strong>
                <span className="rounded bg-[var(--accent)]/15 px-2 py-0.5 text-[10px] uppercase text-[var(--accent)]">
                  {item.channel}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span
                  className={`rounded border px-2 py-0.5 text-[10px] ${controlTone(item.control_mode)}`}
                >
                  {CONTROL_LABELS[item.control_mode]}
                </span>
                {item.assigned_operator && (
                  <span className="truncate text-xs text-[var(--text-secondary)]">
                    {item.assigned_operator.name}
                  </span>
                )}
              </div>
              <p className="mt-2 text-xs text-[var(--text-muted)]">
                {item.message_count} mensajes · {formatDate(item.last_activity_at)}
              </p>
            </button>
          ))}
          {items.length === 0 && (
            <p className="p-5 text-sm text-[var(--text-muted)]">
              No hay conversaciones para estos filtros.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

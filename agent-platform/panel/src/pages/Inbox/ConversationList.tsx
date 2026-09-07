import { LoaderCircle, MessageSquare } from "lucide-react";
import { useInboxLive } from "../../inbox/InboxLiveContext";
import type { InboxConversation } from "../../inbox/types";
import {
  AUTHOR_LABELS,
  CONTROL_LABELS,
  conversationName,
  formatDate,
  listMessageTime,
} from "./presentation";

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
  const { connected, revision } = useInboxLive();
  return (
    <section
      aria-label="Conversaciones"
      className={`${hiddenOnMobile ? "hidden lg:block" : "block"} min-h-0 flex-1 overflow-y-auto overscroll-contain border-t border-[var(--border-color)]`}
    >
      {loading ? (
        <p
          className="flex items-center gap-2 p-4 text-sm text-[var(--text-secondary)]"
          role="status"
        >
          <LoaderCircle className="animate-spin" size={16} />
          Cargando…
        </p>
      ) : (
        <div className="divide-y divide-[var(--border-color)]">
          {items.map((item) => {
            const name = conversationName(item);
            const activity =
              connected &&
              item.observedLiveRevision === revision &&
              document.visibilityState === "visible" &&
              item.control_mode === "automated"
                ? item.agent_activity
                : null;
            const author = item.last_message_author_type;
            const unread = item.unread_count ?? 0;
            return (
              <button
                type="button"
                key={item.id}
                onClick={() => onSelect(item)}
                aria-pressed={selectedId === item.id}
                className={`flex w-full min-w-0 gap-3 border-l-2 px-3 py-3.5 text-left transition-colors hover:bg-[var(--bg-hover)] ${selectedId === item.id ? "border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_10%,transparent)]" : "border-transparent"}`}
              >
                <span
                  aria-hidden="true"
                  className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--bg-secondary)] text-sm font-semibold text-[var(--accent-hover)]"
                >
                  {name.slice(0, 1).toLocaleUpperCase()}
                </span>
                <span className="block min-w-0 flex-1">
                  <span className="flex min-w-0 items-start justify-between gap-2">
                    <strong
                      className={`truncate text-sm ${unread ? "text-[var(--text-primary)]" : "font-medium text-[var(--text-secondary)]"}`}
                    >
                      {name}
                    </strong>
                    {item.last_message_at && (
                      <time
                        dateTime={item.last_message_at}
                        title={`Último mensaje: ${formatDate(item.last_message_at)}`}
                        className={`shrink-0 text-[10px] ${unread ? "text-[var(--accent-hover)]" : "text-[var(--text-secondary)]"}`}
                      >
                        {listMessageTime(item.last_message_at)}
                      </time>
                    )}
                  </span>
                  <span className="mt-1 flex min-w-0 items-center gap-2">
                    <span
                      className={`block min-w-0 flex-1 truncate text-xs ${activity ? "text-amber-300" : "text-[var(--text-secondary)]"}`}
                    >
                      {activity
                        ? activity.status === "queued"
                          ? "Respuesta en cola…"
                          : "Agente preparando respuesta…"
                        : item.last_message_preview
                          ? `${author && author !== "unknown" ? `${AUTHOR_LABELS[author]}: ` : ""}${item.last_message_preview}`
                          : "Sin vista previa disponible"}
                    </span>
                    {unread > 0 && (
                      <span
                        role="status"
                        aria-label={`${unread} mensajes del visitante sin leer`}
                        className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] px-1 text-[10px] font-semibold text-white"
                      >
                        {unread > 99 ? "99+" : unread}
                      </span>
                    )}
                  </span>
                  <span className="mt-2 flex min-w-0 items-center gap-1.5 text-[10px] text-[var(--text-secondary)]">
                    <span className="shrink-0 rounded bg-[var(--bg-secondary)] px-1.5 py-0.5 uppercase">
                      {item.channel}
                    </span>
                    <span
                      className="truncate"
                      title={`Agente de ingreso: ${item.routing_agent.name}; agente automático: ${item.automation_agent.name}`}
                    >
                      {item.automation_agent.name}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span className="shrink-0">{CONTROL_LABELS[item.control_mode]}</span>
                  </span>
                </span>
              </button>
            );
          })}
          {items.length === 0 && (
            <div className="flex flex-col items-center gap-3 p-6 text-center text-sm text-[var(--text-secondary)]">
              <MessageSquare size={25} aria-hidden="true" />
              <p>No hay conversaciones para estos filtros.</p>
              <p className="text-xs">Probá otra búsqueda o ajustá el alcance.</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

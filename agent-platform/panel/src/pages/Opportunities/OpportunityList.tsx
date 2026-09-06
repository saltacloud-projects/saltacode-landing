import { LoaderCircle } from "lucide-react";
import { contactName, formatDate, STAGE_LABELS, stageTone } from "./presentation";
import type { OpportunitySummary } from "./types";

interface Props {
  items: OpportunitySummary[];
  selectedId?: string;
  loading: boolean;
  hiddenOnMobile: boolean;
  onSelect: (item: OpportunitySummary) => void;
}

export function OpportunityList({ items, selectedId, loading, hiddenOnMobile, onSelect }: Props) {
  return (
    <section
      aria-label="Oportunidades"
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
                <strong className="min-w-0 flex-1 text-sm">{item.title}</strong>
                <span
                  className={`shrink-0 rounded border px-2 py-0.5 text-[10px] ${stageTone(item.stage)}`}
                >
                  {STAGE_LABELS[item.stage]}
                </span>
              </div>
              <p className="mt-2 truncate text-xs text-[var(--text-secondary)]">
                {contactName(item.contact)}
                {item.contact.company_name ? ` · ${item.contact.company_name}` : ""}
              </p>
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                {item.pending_follow_up_count} tareas · {item.linked_conversation_count} chats ·{" "}
                {formatDate(item.updated_at)}
              </p>
              <p className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
                {item.assigned_operator?.name || "Sin operador asignado"}
              </p>
            </button>
          ))}
          {items.length === 0 && (
            <p className="p-5 text-sm text-[var(--text-muted)]">
              No hay oportunidades para estos filtros.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

import { LoaderCircle } from "lucide-react";
import {
  dateTime,
  KIND_LABELS,
  outboundStatus,
  STATUS_LABELS,
  shortId,
  statusTone,
} from "./presentation";
import type { FollowUpQueueItem } from "./types";

interface Props {
  items: FollowUpQueueItem[];
  selectedId?: string;
  loading: boolean;
  hiddenOnMobile: boolean;
  onSelect: (item: FollowUpQueueItem) => void;
}

export function FollowUpList({ items, selectedId, loading, hiddenOnMobile, onSelect }: Props) {
  return (
    <section
      aria-label="Cola de seguimientos"
      className={`${hiddenOnMobile ? "hidden lg:block" : "block"} min-w-0`}
    >
      {loading ? (
        <p
          className="flex items-center gap-2 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 text-sm text-[var(--text-muted)]"
          role="status"
        >
          <LoaderCircle className="animate-spin" size={16} /> Cargando seguimientos…
        </p>
      ) : (
        <div className="max-h-[72vh] space-y-2 overflow-y-auto pr-1">
          {items.map((item) => (
            <button
              type="button"
              key={item.id}
              onClick={() => onSelect(item)}
              aria-pressed={selectedId === item.id}
              className={`w-full rounded-lg border p-4 text-left transition-colors ${
                selectedId === item.id
                  ? "border-[var(--accent)] bg-[var(--bg-hover)]"
                  : "border-[var(--border-color)] bg-[var(--bg-card)] hover:border-[var(--text-muted)]"
              }`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <strong className="text-sm">Seguimiento {shortId(item.id)}</strong>
                <span
                  className={`rounded border px-2 py-0.5 text-[11px] ${statusTone(item.status)}`}
                >
                  {STATUS_LABELS[item.status]}
                </span>
              </div>
              <p className="mt-2 text-xs text-[var(--text-secondary)]">
                {KIND_LABELS[item.kind]} · oportunidad {shortId(item.opportunity_id)}
              </p>
              <p className="mt-2 text-sm">Programado: {dateTime(item.due_at)}</p>
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                Intentos {item.attempts}/{item.max_attempts} · estado v{item.state_version}
                {item.is_leased ? " · lease registrado" : ""}
              </p>
              {item.outbound_status && (
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  Entrega asociada: {outboundStatus(item.outbound_status)}
                </p>
              )}
              {item.safe_code && (
                <code className="mt-1 block break-all text-xs text-[var(--error)]">
                  {item.safe_code}
                </code>
              )}
            </button>
          ))}
          {items.length === 0 && (
            <p className="rounded-lg border border-dashed border-[var(--border-color)] p-6 text-center text-sm text-[var(--text-muted)]">
              No hay seguimientos para estos filtros.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

import { LoaderCircle } from "lucide-react";
import { dateTime, phaseLabel, STATUS_LABELS, shortId, statusTone } from "./presentation";
import type { InboundJobSummary } from "./types";

interface Props {
  items: InboundJobSummary[];
  selectedId?: string;
  loading: boolean;
  hiddenOnMobile: boolean;
  onSelect: (item: InboundJobSummary) => void;
}

export function InboundJobList({ items, selectedId, loading, hiddenOnMobile, onSelect }: Props) {
  return (
    <section
      aria-label="Cola de ingresos externos"
      className={`${hiddenOnMobile ? "hidden lg:block" : "block"} min-w-0`}
    >
      {loading ? (
        <p
          className="flex items-center gap-2 rounded-lg border border-[var(--border-color)] p-4 text-sm text-[var(--text-muted)]"
          role="status"
        >
          <LoaderCircle className="animate-spin" size={16} /> Cargando ingresos…
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
                <strong className="text-sm">Ingreso {shortId(item.id)}</strong>
                <span
                  className={`rounded border px-2 py-0.5 text-[11px] ${statusTone(item.status)}`}
                >
                  {STATUS_LABELS[item.status]}
                </span>
              </div>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">
                Canal {item.channel} · {phaseLabel(item.phase)}
              </p>
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                {item.attempts} intento(s) · estado v{item.state_version} · actualizado{" "}
                {dateTime(item.updated_at)}
              </p>
              {item.safe_code && (
                <code className="mt-1 block break-all text-xs text-[var(--error)]">
                  {item.safe_code}
                </code>
              )}
            </button>
          ))}
          {items.length === 0 && (
            <p className="rounded-lg border border-dashed border-[var(--border-color)] p-6 text-center text-sm text-[var(--text-muted)]">
              No hay ingresos externos para este filtro.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

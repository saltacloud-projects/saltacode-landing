import { LoaderCircle } from "lucide-react";
import { dateTime, STATUS_LABELS, shortId, slotTime, statusTone } from "./presentation";
import type { MeetingSummary } from "./types";

interface Props {
  items: MeetingSummary[];
  selectedId?: string;
  loading: boolean;
  hiddenOnMobile: boolean;
  onSelect: (meeting: MeetingSummary) => void;
}

export function MeetingList({ items, selectedId, loading, hiddenOnMobile, onSelect }: Props) {
  return (
    <section
      aria-label="Reuniones"
      className={`${hiddenOnMobile ? "hidden lg:block" : "block"} min-w-0`}
    >
      {loading ? (
        <p
          className="flex items-center gap-2 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 text-sm text-[var(--text-muted)]"
          role="status"
        >
          <LoaderCircle className="animate-spin" size={16} /> Cargando reuniones…
        </p>
      ) : (
        <div className="max-h-[72vh] space-y-2 overflow-y-auto pr-1">
          {items.map((meeting) => (
            <button
              type="button"
              key={meeting.id}
              onClick={() => onSelect(meeting)}
              aria-pressed={selectedId === meeting.id}
              className={`w-full rounded-lg border p-4 text-left transition-colors ${
                selectedId === meeting.id
                  ? "border-[var(--accent)] bg-[var(--bg-hover)]"
                  : "border-[var(--border-color)] bg-[var(--bg-card)] hover:border-[var(--text-muted)]"
              }`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <strong className="text-sm">Reunión {shortId(meeting.id)}</strong>
                <span
                  className={`rounded border px-2 py-0.5 text-[11px] ${statusTone(meeting.status)}`}
                >
                  {STATUS_LABELS[meeting.status]}
                </span>
              </div>
              <p className="mt-2 text-xs text-[var(--text-secondary)]">
                Oportunidad {shortId(meeting.opportunity_id)}
              </p>
              <p className="mt-2 text-sm text-[var(--text-primary)]">
                {meeting.selected_slot
                  ? slotTime(
                      meeting.selected_slot.starts_at,
                      meeting.selected_slot.ends_at,
                      meeting.selected_slot.timezone,
                    )
                  : "Sin horario seleccionado"}
              </p>
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                Estado v{meeting.state_version} · propuesta v{meeting.proposal_version} ·
                actualizada {dateTime(meeting.updated_at)}
              </p>
            </button>
          ))}
          {items.length === 0 && (
            <p className="rounded-lg border border-dashed border-[var(--border-color)] p-6 text-center text-sm text-[var(--text-muted)]">
              No hay reuniones para estos filtros.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

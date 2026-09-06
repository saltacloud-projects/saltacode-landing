import { ArrowLeft, ExternalLink, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { MeetingActions } from "./MeetingActions";
import { dateTime, STATUS_LABELS, shortId, slotTime, statusTone } from "./presentation";
import type { MeetingDetail as MeetingDetailType, SlotProposalInput } from "./types";

interface Props {
  agentId: string;
  meeting: MeetingDetailType | null;
  loading: boolean;
  busy: boolean;
  canManage: boolean;
  onBack: () => void;
  onProposeSlots: (slots: SlotProposalInput[], reason?: string) => Promise<unknown>;
  onMarkAwaiting: (reason?: string) => Promise<unknown>;
  onSelectSlot: (slotId: string, reason?: string) => Promise<unknown>;
  onScheduleManually: (input: {
    expected_opportunity_version: number;
    slot_id: string;
    evidence_type: string;
    evidence_reference: string;
    reason?: string;
  }) => Promise<unknown>;
  onRequestReschedule: (reason?: string) => Promise<unknown>;
  onCancel: (reason?: string) => Promise<unknown>;
  onRequireReview: (reason?: string) => Promise<unknown>;
}

export function MeetingDetail({
  agentId,
  meeting,
  loading,
  busy,
  canManage,
  onBack,
  onProposeSlots,
  onMarkAwaiting,
  onSelectSlot,
  onScheduleManually,
  onRequestReschedule,
  onCancel,
  onRequireReview,
}: Props) {
  return (
    <section
      aria-label="Detalle de reunión"
      className={`${meeting ? "block" : "hidden lg:block"} min-w-0 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]`}
    >
      {!meeting ? (
        <div className="grid min-h-[520px] place-items-center p-6 text-center text-sm text-[var(--text-muted)]">
          Seleccioná una reunión para revisar su coordinación e historial.
        </div>
      ) : (
        <div className="space-y-5 p-4 sm:p-5">
          <header className="flex items-start gap-3">
            <button
              type="button"
              onClick={onBack}
              className="rounded p-1.5 hover:bg-[var(--bg-hover)] lg:hidden"
              aria-label="Volver a reuniones"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="min-w-0 flex-1">
              <h3 className="text-lg font-semibold">Reunión {shortId(meeting.id)}</h3>
              <Link
                to={`/agents/${agentId}/opportunities`}
                className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--accent-hover)]"
              >
                Oportunidad {shortId(meeting.opportunity_id)}
                <ExternalLink size={12} aria-hidden="true" />
              </Link>
            </div>
            <span className={`rounded border px-2 py-1 text-xs ${statusTone(meeting.status)}`}>
              {STATUS_LABELS[meeting.status]}
            </span>
          </header>

          {loading && (
            <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status">
              <LoaderCircle size={16} className="animate-spin" /> Actualizando reunión…
            </p>
          )}

          <dl className="grid gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Estado</dt>
              <dd className="mt-1">v{meeting.state_version}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Propuesta</dt>
              <dd className="mt-1">v{meeting.proposal_version}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Creada</dt>
              <dd className="mt-1">{dateTime(meeting.created_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Actualizada</dt>
              <dd className="mt-1">{dateTime(meeting.updated_at)}</dd>
            </div>
          </dl>

          {meeting.selected_slot && (
            <section
              aria-labelledby="selected-slot-title"
              className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3"
            >
              <h4 id="selected-slot-title" className="text-sm font-semibold">
                Horario seleccionado
              </h4>
              <p className="mt-1 text-sm">
                {slotTime(
                  meeting.selected_slot.starts_at,
                  meeting.selected_slot.ends_at,
                  meeting.selected_slot.timezone,
                )}
              </p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {meeting.selected_slot.timezone}
              </p>
            </section>
          )}

          <SlotHistory meeting={meeting} />
          <MeetingActions
            key={`${meeting.id}:${meeting.state_version}:${meeting.proposal_version}`}
            meeting={meeting}
            busy={busy}
            canManage={canManage}
            onProposeSlots={onProposeSlots}
            onMarkAwaiting={onMarkAwaiting}
            onSelectSlot={onSelectSlot}
            onScheduleManually={onScheduleManually}
            onRequestReschedule={onRequestReschedule}
            onCancel={onCancel}
            onRequireReview={onRequireReview}
          />
          <EventTimeline meeting={meeting} />
        </div>
      )}
    </section>
  );
}

function SlotHistory({ meeting }: { meeting: MeetingDetailType }) {
  const versions = [...new Set(meeting.slots.map((slot) => slot.proposal_version))].sort(
    (left, right) => right - left,
  );
  return (
    <section aria-labelledby="meeting-slots-title">
      <h4 id="meeting-slots-title" className="font-semibold">
        Propuestas de horario
      </h4>
      <div className="mt-2 space-y-3">
        {versions.map((version) => (
          <section
            key={version}
            aria-labelledby={`proposal-${version}`}
            className="rounded-lg border border-[var(--border-color)] p-3"
          >
            <h5
              id={`proposal-${version}`}
              className="text-xs font-semibold text-[var(--text-muted)]"
            >
              Propuesta v{version}{" "}
              {version === meeting.proposal_version ? "· vigente" : "· histórica"}
            </h5>
            <ol className="mt-2 grid gap-2 sm:grid-cols-2">
              {meeting.slots
                .filter((slot) => slot.proposal_version === version)
                .map((slot) => (
                  <li
                    key={slot.id}
                    className={`rounded border p-2 text-sm ${
                      meeting.selected_slot_id === slot.id
                        ? "border-emerald-500/40 bg-emerald-500/5"
                        : "border-[var(--border-color)]"
                    }`}
                  >
                    <span className="text-xs text-[var(--text-muted)]">Opción {slot.position}</span>
                    <p className="mt-1">{slotTime(slot.starts_at, slot.ends_at, slot.timezone)}</p>
                    <p className="mt-1 text-xs text-[var(--text-muted)]">{slot.timezone}</p>
                  </li>
                ))}
            </ol>
          </section>
        ))}
        {versions.length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">Todavía no hay horarios propuestos.</p>
        )}
      </div>
    </section>
  );
}

function EventTimeline({ meeting }: { meeting: MeetingDetailType }) {
  return (
    <section aria-labelledby="meeting-events-title">
      <h4 id="meeting-events-title" className="font-semibold">
        Historial inmutable
      </h4>
      <ol className="mt-2 space-y-2">
        {[...meeting.events].reverse().map((event) => (
          <li key={event.id} className="rounded border border-[var(--border-color)] p-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <span>
                {event.from_status ? `${STATUS_LABELS[event.from_status]} → ` : ""}
                {STATUS_LABELS[event.to_status]}
              </span>
              <time className="text-xs text-[var(--text-muted)]">{dateTime(event.created_at)}</time>
            </div>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Estado v{event.state_version} · propuesta v{event.proposal_version} · oportunidad v
              {event.opportunity_control_version} ·{" "}
              {event.actor_type === "operator" ? "operador" : "agente"}
            </p>
            {event.evidence_recorded && (
              <p className="mt-1 text-xs text-emerald-400">
                Evidencia registrada{event.evidence_type ? ` · ${event.evidence_type}` : ""}
              </p>
            )}
            {event.safe_code && (
              <code className="mt-1 block break-all text-xs text-[var(--error)]">
                {event.safe_code}
              </code>
            )}
          </li>
        ))}
        {meeting.events.length === 0 && (
          <li className="text-sm text-[var(--text-muted)]">Sin eventos disponibles.</li>
        )}
      </ol>
    </section>
  );
}

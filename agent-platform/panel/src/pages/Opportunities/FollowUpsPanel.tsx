import { useMemo, useState } from "react";
import { FOLLOW_UP_KIND_LABELS, FOLLOW_UP_STATUS_LABELS, formatDate } from "./presentation";
import type { FollowUpKind, FollowUpStatus, OpportunityDetail } from "./types";

interface Props {
  opportunity: OpportunityDetail;
  busy: boolean;
  canManage: boolean;
  onCreate: (input: {
    contact_point_id: string;
    kind: FollowUpKind;
    due_at: string;
    note?: string;
  }) => void;
  onTransition: (taskId: string, status: FollowUpStatus, expectedVersion: number) => void;
}

export function FollowUpsPanel({ opportunity, busy, canManage, onCreate, onTransition }: Props) {
  const eligiblePoints = useMemo(
    () => opportunity.contact.contact_points.filter((point) => point.commercial_follow_up_allowed),
    [opportunity.contact.contact_points],
  );
  const [contactPointId, setContactPointId] = useState(eligiblePoints[0]?.id ?? "");
  const [kind, setKind] = useState<FollowUpKind>("commercial_follow_up");
  const [dueAt, setDueAt] = useState("");
  const [note, setNote] = useState("");

  return (
    <section
      aria-labelledby="follow-ups-title"
      className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
    >
      <h3 id="follow-ups-title" className="font-semibold">
        Seguimientos
      </h3>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Cada tarea conserva la evidencia de consentimiento usada al programarla.
      </p>

      {canManage && (
        <form
          className="mt-4 grid gap-3 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!contactPointId || !dueAt) return;
            onCreate({
              contact_point_id: contactPointId,
              kind,
              due_at: new Date(dueAt).toISOString(),
              note: note.trim() || undefined,
            });
          }}
        >
          <label className="text-xs text-[var(--text-muted)]">
            Contacto autorizado
            <select
              value={contactPointId}
              onChange={(event) => setContactPointId(event.target.value)}
              className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
            >
              <option value="">Seleccionar…</option>
              {eligiblePoints.map((point) => (
                <option key={point.id} value={point.id}>
                  {point.kind} · {point.masked_value}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-[var(--text-muted)]">
            Tipo
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as FollowUpKind)}
              className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
            >
              {Object.entries(FOLLOW_UP_KIND_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-[var(--text-muted)]">
            Fecha y hora
            <input
              required
              type="datetime-local"
              value={dueAt}
              onChange={(event) => setDueAt(event.target.value)}
              className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
            />
          </label>
          <label className="text-xs text-[var(--text-muted)]">
            Nota
            <input
              maxLength={8_000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
            />
          </label>
          {eligiblePoints.length === 0 && (
            <p className="text-sm text-[var(--warning)] md:col-span-2" role="status">
              Bloqueado: no hay un punto de contacto con consentimiento vigente para seguimiento
              comercial.
            </p>
          )}
          <button
            type="submit"
            disabled={busy || !contactPointId || !dueAt}
            className="rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50 md:col-span-2"
          >
            Programar seguimiento
          </button>
        </form>
      )}

      <div className="mt-4 space-y-2">
        {opportunity.follow_ups.map((task) => (
          <article key={task.id} className="rounded border border-[var(--border-color)] p-3">
            <div className="flex flex-wrap items-start gap-2">
              <strong className="min-w-0 flex-1 text-sm">{FOLLOW_UP_KIND_LABELS[task.kind]}</strong>
              <span className="rounded bg-[var(--bg-hover)] px-2 py-1 text-[10px]">
                {FOLLOW_UP_STATUS_LABELS[task.status]}
              </span>
            </div>
            <p className="mt-2 text-xs text-[var(--text-secondary)]">
              Vence {formatDate(task.due_at)}
            </p>
            {task.note && (
              <p className="mt-1 whitespace-pre-wrap text-xs text-[var(--text-muted)]">
                {task.note}
              </p>
            )}
            {canManage && (
              <FollowUpTransitions task={task} busy={busy} onTransition={onTransition} />
            )}
          </article>
        ))}
        {opportunity.follow_ups.length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">Todavía no hay seguimientos.</p>
        )}
      </div>
    </section>
  );
}

function FollowUpTransitions({
  task,
  busy,
  onTransition,
}: {
  task: OpportunityDetail["follow_ups"][number];
  busy: boolean;
  onTransition: (taskId: string, status: FollowUpStatus, expectedVersion: number) => void;
}) {
  const transitions: Partial<Record<FollowUpStatus, FollowUpStatus[]>> = {
    scheduled: ["in_progress", "review_required", "cancelled"],
    in_progress: ["completed", "review_required", "cancelled"],
    review_required: ["scheduled", "cancelled"],
  };
  const targets = transitions[task.status] ?? [];
  if (targets.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {targets.map((status) => (
        <button
          type="button"
          key={status}
          disabled={busy}
          onClick={() => onTransition(task.id, status, task.state_version)}
          className="rounded border border-[var(--border-color)] px-2 py-1 text-xs disabled:opacity-50"
        >
          {FOLLOW_UP_STATUS_LABELS[status]}
        </button>
      ))}
    </div>
  );
}

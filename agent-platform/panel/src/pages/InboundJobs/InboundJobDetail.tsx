import { ArrowLeft, LoaderCircle } from "lucide-react";
import {
  actorLabel,
  dateTime,
  phaseLabel,
  STATUS_LABELS,
  shortId,
  statusTone,
} from "./presentation";
import type { InboundJobDetail as InboundJobDetailType, InboundJobEvent } from "./types";

const REQUEUE_PHASES = new Set(["accepted", "legacy_quarantined", "claimed"]);

interface Props {
  detail: InboundJobDetailType | null;
  events: InboundJobEvent[];
  loading: boolean;
  busy: boolean;
  canReview: boolean;
  onBack: () => void;
  onRequeue: () => Promise<boolean>;
  onCancel: () => Promise<boolean>;
  onAcknowledge: () => Promise<boolean>;
}

export function InboundJobDetail({
  detail,
  events,
  loading,
  busy,
  canReview,
  onBack,
  onRequeue,
  onCancel,
  onAcknowledge,
}: Props) {
  return (
    <section
      aria-label="Detalle de ingreso externo"
      className={`${detail ? "block" : "hidden lg:block"} min-w-0 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]`}
    >
      {!detail ? (
        <div className="grid min-h-[520px] place-items-center p-6 text-center text-sm text-[var(--text-muted)]">
          Seleccioná un ingreso para revisar su estado y trazabilidad segura.
        </div>
      ) : (
        <div className="space-y-5 p-4 sm:p-5">
          <header className="flex items-start gap-3">
            <button
              type="button"
              onClick={onBack}
              className="rounded p-1.5 hover:bg-[var(--bg-hover)] lg:hidden"
              aria-label="Volver a ingresos externos"
            >
              <ArrowLeft size={18} aria-hidden="true" />
            </button>
            <div className="min-w-0 flex-1">
              <h3 className="text-lg font-semibold">Ingreso {shortId(detail.id)}</h3>
              <p className="mt-1 text-xs text-[var(--text-muted)]">Canal {detail.channel}</p>
            </div>
            <span className={`rounded border px-2 py-1 text-xs ${statusTone(detail.status)}`}>
              {STATUS_LABELS[detail.status]}
            </span>
          </header>

          {loading && (
            <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status">
              <LoaderCircle size={16} className="animate-spin" /> Actualizando ingreso…
            </p>
          )}

          <ExecutionSummary detail={detail} />
          <InboundJobActions
            detail={detail}
            busy={busy || loading}
            canReview={canReview}
            onRequeue={onRequeue}
            onCancel={onCancel}
            onAcknowledge={onAcknowledge}
          />
          <EventTimeline events={events} />
        </div>
      )}
    </section>
  );
}

function ExecutionSummary({ detail }: { detail: InboundJobDetailType }) {
  return (
    <section aria-labelledby="inbound-execution-title">
      <h4 id="inbound-execution-title" className="font-semibold">
        Ejecución
      </h4>
      <dl className="mt-2 grid gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 text-sm sm:grid-cols-2 xl:grid-cols-3">
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Fase</dt>
          <dd className="mt-1">{phaseLabel(detail.phase)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Intentos</dt>
          <dd className="mt-1">{detail.attempts}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Estado</dt>
          <dd className="mt-1">v{detail.state_version}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Creado</dt>
          <dd className="mt-1">{dateTime(detail.created_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Actualizado</dt>
          <dd className="mt-1">{dateTime(detail.updated_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Finalizado</dt>
          <dd className="mt-1">{dateTime(detail.terminal_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Control de conversación</dt>
          <dd className="mt-1">
            {detail.conversation_control_version === null
              ? "No vinculado"
              : `v${detail.conversation_control_version}`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Automatización</dt>
          <dd className="mt-1">
            {detail.conversation_automation_version === null
              ? "No vinculada"
              : `v${detail.conversation_automation_version}`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Ingreso anterior aislado</dt>
          <dd className="mt-1">{detail.legacy_payload_quarantined ? "Sí" : "No"}</dd>
        </div>
      </dl>
      {detail.safe_code && (
        <p className="mt-2 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm">
          Código seguro: <code className="break-all text-[var(--error)]">{detail.safe_code}</code>
        </p>
      )}
      <p className="mt-2 text-xs text-[var(--text-muted)]">
        Esta vista no expone mensajes, contactos, identificadores de proveedor ni payloads.
      </p>
    </section>
  );
}

function InboundJobActions({
  detail,
  busy,
  canReview,
  onRequeue,
  onCancel,
  onAcknowledge,
}: Pick<Props, "busy" | "canReview" | "onRequeue" | "onCancel" | "onAcknowledge"> & {
  detail: InboundJobDetailType;
}) {
  if (!canReview) {
    return (
      <p className="rounded border border-[var(--border-color)] p-3 text-sm text-[var(--text-muted)]">
        Tu rol permite revisar el ingreso, pero no resolverlo.
      </p>
    );
  }

  const canRequeue = detail.status === "review_required" && REQUEUE_PHASES.has(detail.phase);
  const canCancel = detail.status === "queued" || detail.status === "review_required";
  const canAcknowledge = detail.status === "review_required";
  if (!canRequeue && !canCancel && !canAcknowledge) {
    return (
      <p className="rounded border border-[var(--border-color)] p-3 text-sm text-[var(--text-muted)]">
        Este estado no admite una resolución manual segura.
      </p>
    );
  }

  return (
    <section aria-labelledby="inbound-actions-title">
      <h4 id="inbound-actions-title" className="font-semibold">
        Resolución
      </h4>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Reencolar sólo está disponible antes de un efecto externo. Reconocer descarta el contenido
        retenido y conserva únicamente la trazabilidad segura.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {canRequeue && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onRequeue()}
            className="rounded border border-[var(--accent)]/50 px-3 py-2 text-sm text-[var(--accent-hover)] disabled:opacity-50"
          >
            Reencolar ingreso
          </button>
        )}
        {canCancel && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onCancel()}
            className="rounded border border-[var(--error)]/50 px-3 py-2 text-sm text-[var(--error)] disabled:opacity-50"
          >
            Cancelar ingreso
          </button>
        )}
        {canAcknowledge && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onAcknowledge()}
            className="rounded border border-[var(--border-color)] px-3 py-2 text-sm text-[var(--text-secondary)] disabled:opacity-50"
          >
            Reconocer y descartar
          </button>
        )}
      </div>
    </section>
  );
}

function EventTimeline({ events }: { events: InboundJobEvent[] }) {
  return (
    <section aria-labelledby="inbound-events-title">
      <h4 id="inbound-events-title" className="font-semibold">
        Historial inmutable
      </h4>
      <ol className="mt-2 space-y-2">
        {[...events].reverse().map((event) => (
          <li key={event.id} className="rounded border border-[var(--border-color)] p-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <span>
                {event.from_status
                  ? `${event.from_status === "failed" ? "Fallo previo" : STATUS_LABELS[event.from_status]} → `
                  : ""}
                {STATUS_LABELS[event.to_status]}
              </span>
              <time className="text-xs text-[var(--text-muted)]">{dateTime(event.created_at)}</time>
            </div>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Estado v{event.state_version} · {phaseLabel(event.phase)} · actor{" "}
              {actorLabel(event.actor_type)}
              {event.has_actor_admin ? " verificado" : ""}
            </p>
            {event.safe_code && (
              <code className="mt-1 block break-all text-xs text-[var(--error)]">
                {event.safe_code}
              </code>
            )}
          </li>
        ))}
        {events.length === 0 && (
          <li className="text-sm text-[var(--text-muted)]">Sin eventos disponibles.</li>
        )}
      </ol>
    </section>
  );
}

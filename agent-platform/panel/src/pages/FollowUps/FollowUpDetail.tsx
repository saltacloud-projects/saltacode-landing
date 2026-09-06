import { ArrowLeft, ExternalLink, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
import {
  actorType,
  dateTime,
  KIND_LABELS,
  outboundStatus,
  STATUS_LABELS,
  shortId,
  statusTone,
} from "./presentation";
import type { FollowUpDetail as FollowUpDetailType, FollowUpEvent } from "./types";

interface Props {
  agentId: string;
  detail: FollowUpDetailType | null;
  events: FollowUpEvent[];
  loading: boolean;
  busy: boolean;
  canManage: boolean;
  canReview: boolean;
  onBack: () => void;
  onCancel: () => Promise<boolean>;
  onRequeue: () => Promise<boolean>;
  onResolveReview: (resolution: "requeue" | "cancel") => Promise<boolean>;
}

export function FollowUpDetail({
  agentId,
  detail,
  events,
  loading,
  busy,
  canManage,
  canReview,
  onBack,
  onCancel,
  onRequeue,
  onResolveReview,
}: Props) {
  return (
    <section
      aria-label="Detalle de seguimiento"
      className={`${detail ? "block" : "hidden lg:block"} min-w-0 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]`}
    >
      {!detail ? (
        <div className="grid min-h-[520px] place-items-center p-6 text-center text-sm text-[var(--text-muted)]">
          Seleccioná un seguimiento para revisar su ejecución y evidencia.
        </div>
      ) : (
        <div className="space-y-5 p-4 sm:p-5">
          <header className="flex items-start gap-3">
            <button
              type="button"
              onClick={onBack}
              className="rounded p-1.5 hover:bg-[var(--bg-hover)] lg:hidden"
              aria-label="Volver a seguimientos"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="min-w-0 flex-1">
              <h3 className="text-lg font-semibold">Seguimiento {shortId(detail.id)}</h3>
              <Link
                to={`/agents/${agentId}/opportunities`}
                className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--accent-hover)]"
              >
                Oportunidad {shortId(detail.opportunity_id)}
                <ExternalLink size={12} aria-hidden="true" />
              </Link>
            </div>
            <span className={`rounded border px-2 py-1 text-xs ${statusTone(detail.status)}`}>
              {STATUS_LABELS[detail.status]}
            </span>
          </header>

          {loading && (
            <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status">
              <LoaderCircle size={16} className="animate-spin" /> Actualizando seguimiento…
            </p>
          )}

          <ExecutionSummary detail={detail} />
          <EvidenceSummary detail={detail} />
          <FollowUpActions
            detail={detail}
            busy={busy || loading}
            canManage={canManage}
            canReview={canReview}
            onCancel={onCancel}
            onRequeue={onRequeue}
            onResolveReview={onResolveReview}
          />
          <EventTimeline events={events} />
        </div>
      )}
    </section>
  );
}

function ExecutionSummary({ detail }: { detail: FollowUpDetailType }) {
  return (
    <section aria-labelledby="follow-up-execution-title">
      <h4 id="follow-up-execution-title" className="font-semibold">
        Ejecución
      </h4>
      <dl className="mt-2 grid gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 text-sm sm:grid-cols-2 xl:grid-cols-3">
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Tipo</dt>
          <dd className="mt-1">{KIND_LABELS[detail.kind]}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Programado</dt>
          <dd className="mt-1">{dateTime(detail.due_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Disponible desde</dt>
          <dd className="mt-1">{dateTime(detail.available_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Intentos</dt>
          <dd className="mt-1">
            {detail.attempts} de {detail.max_attempts}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Lease de worker</dt>
          <dd className="mt-1">{detail.is_leased ? "Registrado" : "Sin lease"}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Entrega asociada</dt>
          <dd className="mt-1">{outboundStatus(detail.outbound_status)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Estado</dt>
          <dd className="mt-1">v{detail.state_version}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Política programada</dt>
          <dd className="mt-1">
            {detail.scheduled_policy_version === null
              ? "No registrada"
              : `v${detail.scheduled_policy_version}`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Política ejecutada</dt>
          <dd className="mt-1">
            {detail.executed_policy_version === null
              ? "No ejecutada"
              : `v${detail.executed_policy_version}`}
          </dd>
        </div>
      </dl>
      {detail.safe_code && (
        <p className="mt-2 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm">
          Código seguro: <code className="break-all text-[var(--error)]">{detail.safe_code}</code>
        </p>
      )}
      {detail.review_required_at && (
        <p className="mt-2 text-sm text-[var(--warning)]">
          Revisión requerida desde {dateTime(detail.review_required_at)}.
        </p>
      )}
    </section>
  );
}

function EvidenceSummary({ detail }: { detail: FollowUpDetailType }) {
  const evidence = [
    ["Consentimiento programado", detail.has_consent_evidence],
    ["Consentimiento usado", detail.has_executed_consent_evidence],
    ["Mensaje de chat", detail.has_chat_message_evidence],
    ["Mensaje de salida", detail.has_outbound_message_evidence],
    ["Conversación fuente retenida", detail.has_retained_source_conversation],
    ["Presupuesto vinculado", detail.quote_version_id !== null],
  ] as const;
  return (
    <section aria-labelledby="follow-up-evidence-title">
      <h4 id="follow-up-evidence-title" className="font-semibold">
        Evidencia disponible
      </h4>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {evidence.map(([label, available]) => (
          <li
            key={label}
            className="rounded border border-[var(--border-color)] p-2 text-sm text-[var(--text-secondary)]"
          >
            {label}: {available ? "sí" : "no"}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-[var(--text-muted)]">
        El panel confirma existencia de evidencia, pero no expone contenido, contactos ni
        identificadores sensibles.
      </p>
    </section>
  );
}

function FollowUpActions({
  detail,
  busy,
  canManage,
  canReview,
  onCancel,
  onRequeue,
  onResolveReview,
}: Pick<
  Props,
  "busy" | "canManage" | "canReview" | "onCancel" | "onRequeue" | "onResolveReview"
> & {
  detail: FollowUpDetailType;
}) {
  if (detail.status === "scheduled" && canManage) {
    return (
      <section aria-labelledby="follow-up-actions-title">
        <h4 id="follow-up-actions-title" className="font-semibold">
          Acciones
        </h4>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onCancel()}
          className="mt-2 rounded border border-[var(--error)]/50 px-3 py-2 text-sm text-[var(--error)] disabled:opacity-50"
        >
          Cancelar seguimiento
        </button>
      </section>
    );
  }

  if (detail.status === "review_required") {
    if (!canReview) {
      return (
        <p className="rounded border border-[var(--warning)]/35 bg-[var(--warning)]/5 p-3 text-sm text-[var(--text-secondary)]">
          Este seguimiento requiere una revisión autorizada. Tu rol puede observarlo, pero no
          resolverlo.
        </p>
      );
    }
    return (
      <section aria-labelledby="follow-up-actions-title">
        <h4 id="follow-up-actions-title" className="font-semibold">
          Resolver revisión
        </h4>
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          Reencolar vuelve a validar consentimiento, política, ownership y disponibilidad de
          entrega. Cancelar conserva todo el historial.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void onRequeue()}
            className="rounded border border-[var(--accent)]/50 px-3 py-2 text-sm text-[var(--accent-hover)] disabled:opacity-50"
          >
            Reencolar después de revisar
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void onResolveReview("cancel")}
            className="rounded border border-[var(--error)]/50 px-3 py-2 text-sm text-[var(--error)] disabled:opacity-50"
          >
            Resolver revisión cancelando
          </button>
        </div>
      </section>
    );
  }

  return (
    <p className="rounded border border-[var(--border-color)] p-3 text-sm text-[var(--text-muted)]">
      Este estado no admite acciones manuales. La ejecución y la entrega permanecen bajo control de
      los workers.
    </p>
  );
}

function EventTimeline({ events }: { events: FollowUpEvent[] }) {
  return (
    <section aria-labelledby="follow-up-events-title">
      <h4 id="follow-up-events-title" className="font-semibold">
        Historial inmutable
      </h4>
      <ol className="mt-2 space-y-2">
        {[...events].reverse().map((event) => (
          <li key={event.id} className="rounded border border-[var(--border-color)] p-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <span>
                {event.from_status ? `${STATUS_LABELS[event.from_status]} → ` : ""}
                {STATUS_LABELS[event.to_status]}
              </span>
              <time className="text-xs text-[var(--text-muted)]">{dateTime(event.created_at)}</time>
            </div>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Estado v{event.state_version} · actor {actorType(event.actor_type)}
              {event.target_channel ? ` · canal ${event.target_channel}` : ""}
            </p>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Control {event.control_version ?? "—"} · automatización{" "}
              {event.automation_version ?? "—"}
              {event.scheduled_policy_version !== null
                ? ` · política programada v${event.scheduled_policy_version}`
                : ""}
              {event.executed_policy_version !== null
                ? ` · política ejecutada v${event.executed_policy_version}`
                : ""}
            </p>
            {(event.has_consent_evidence ||
              event.has_executed_consent_evidence ||
              event.has_causal_consent_evidence ||
              event.has_chat_message_evidence ||
              event.has_outbound_message_evidence) && (
              <p className="mt-1 text-xs text-emerald-400">Evidencia vinculada y preservada</p>
            )}
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

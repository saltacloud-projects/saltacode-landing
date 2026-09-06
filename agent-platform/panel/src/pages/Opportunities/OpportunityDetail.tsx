import { ArrowLeft, LoaderCircle } from "lucide-react";
import type { AgentProfile } from "../../agents/types";
import { FollowUpsPanel } from "./FollowUpsPanel";
import { OpportunityActions } from "./OpportunityActions";
import { contactName, formatDate, STAGE_LABELS, stageTone } from "./presentation";
import { QuotesPanel } from "./QuotesPanel";
import type {
  CommercialOperator,
  FollowUpKind,
  FollowUpStatus,
  OpportunityDetail as OpportunityDetailType,
  OpportunityStage,
} from "./types";

interface Props {
  opportunity: OpportunityDetailType | null;
  agents: AgentProfile[];
  operators: CommercialOperator[];
  loading: boolean;
  busy: boolean;
  canManage: boolean;
  canRegisterAuthority: boolean;
  onBack: () => void;
  onStage: (stage: OpportunityStage, reason?: string) => void;
  onReassign: (agentId: string, operatorId?: string, reason?: string) => void;
  onLinkConversation: (conversationId: string) => void;
  onCreateFollowUp: (input: {
    contact_point_id: string;
    kind: FollowUpKind;
    due_at: string;
    note?: string;
  }) => void;
  onTransitionFollowUp: (taskId: string, status: FollowUpStatus, version: number) => void;
  onRequestQuote: (input: {
    requirements: Record<string, unknown>;
    status: "unavailable" | "review_required";
    failure_code: string;
  }) => void;
  onRegisterQuoteVersion: (
    requestId: string,
    input: {
      expected_version: number;
      authority_name: string;
      authority_version: string;
      external_reference: string;
      content_hash: string;
      issued_at: string;
    },
  ) => void;
}

export function OpportunityDetail({
  opportunity,
  agents,
  operators,
  loading,
  busy,
  canManage,
  canRegisterAuthority,
  onBack,
  onStage,
  onReassign,
  onLinkConversation,
  onCreateFollowUp,
  onTransitionFollowUp,
  onRequestQuote,
  onRegisterQuoteVersion,
}: Props) {
  return (
    <section
      aria-label="Detalle de oportunidad"
      className={`${opportunity ? "block" : "hidden lg:block"} min-w-0 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]`}
    >
      {!opportunity ? (
        <div className="grid min-h-[520px] place-items-center p-6 text-center text-sm text-[var(--text-muted)]">
          Seleccioná una oportunidad para gestionar su expediente.
        </div>
      ) : (
        <div className="space-y-4 p-4 sm:p-5">
          <header className="flex items-start gap-3">
            <button
              type="button"
              onClick={onBack}
              className="rounded p-1.5 hover:bg-[var(--bg-hover)] lg:hidden"
              aria-label="Volver a oportunidades"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="min-w-0 flex-1">
              <h3 className="text-lg font-semibold">{opportunity.title}</h3>
              <p className="mt-1 text-sm text-[var(--text-secondary)]">
                {contactName(opportunity.contact)}
              </p>
            </div>
            <span className={`rounded border px-2 py-1 text-xs ${stageTone(opportunity.stage)}`}>
              {STAGE_LABELS[opportunity.stage]}
            </span>
          </header>

          {loading && (
            <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status">
              <LoaderCircle size={16} className="animate-spin" /> Actualizando expediente…
            </p>
          )}

          <ContactCard opportunity={opportunity} />
          <OpportunityActions
            key={`${opportunity.id}:${opportunity.control_version}`}
            opportunity={opportunity}
            agents={agents}
            operators={operators}
            busy={busy}
            canManage={canManage}
            onStage={onStage}
            onReassign={onReassign}
            onLinkConversation={onLinkConversation}
          />
          <div className="grid gap-4 2xl:grid-cols-2">
            <FollowUpsPanel
              key={`follow-ups:${opportunity.id}:${opportunity.contact.contact_points.length}`}
              opportunity={opportunity}
              busy={busy}
              canManage={canManage}
              onCreate={onCreateFollowUp}
              onTransition={onTransitionFollowUp}
            />
            <QuotesPanel
              opportunity={opportunity}
              busy={busy}
              canManage={canManage}
              canRegisterAuthority={canRegisterAuthority}
              onRequest={onRequestQuote}
              onRegisterVersion={onRegisterQuoteVersion}
            />
          </div>
          <HistoryPanel opportunity={opportunity} />
        </div>
      )}
    </section>
  );
}

function ContactCard({ opportunity }: { opportunity: OpportunityDetailType }) {
  return (
    <section
      aria-labelledby="commercial-contact-title"
      className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h4 id="commercial-contact-title" className="text-sm font-semibold">
            Contacto comercial
          </h4>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {[opportunity.contact.company_name, opportunity.contact.job_title]
              .filter(Boolean)
              .join(" · ") || "Sin empresa o cargo registrados"}
          </p>
        </div>
        <span className="text-xs text-[var(--text-muted)]">
          Responsable: {opportunity.assigned_operator?.name || "sin operador"}
        </span>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {opportunity.contact.contact_points.map((point) => (
          <article
            key={point.id}
            className="rounded border border-[var(--border-color)] p-2 text-xs"
          >
            <p>
              {point.kind.toUpperCase()} · {point.masked_value}
            </p>
            <p className="mt-1 text-[var(--text-muted)]">
              Verificación: {point.verification_status}
            </p>
            <p
              className={
                point.commercial_follow_up_allowed
                  ? "mt-1 text-green-400"
                  : "mt-1 text-[var(--warning)]"
              }
            >
              Seguimiento:{" "}
              {point.commercial_follow_up_allowed ? "consentido" : "sin consentimiento vigente"}
            </p>
            <p
              className={
                point.quote_delivery_allowed ? "mt-1 text-green-400" : "mt-1 text-[var(--warning)]"
              }
            >
              Entrega de presupuesto:{" "}
              {point.quote_delivery_allowed ? "consentida" : "sin consentimiento vigente"}
            </p>
          </article>
        ))}
        {opportunity.contact.contact_points.length === 0 && (
          <p className="text-xs text-[var(--warning)]">No hay puntos de contacto registrados.</p>
        )}
      </div>
      <p className="mt-3 text-xs text-[var(--text-muted)]">
        {opportunity.conversations.length} conversaciones vinculadas. Los datos sensibles permanecen
        cifrados; este panel sólo muestra valores enmascarados.
      </p>
    </section>
  );
}

function HistoryPanel({ opportunity }: { opportunity: OpportunityDetailType }) {
  return (
    <section
      aria-labelledby="opportunity-history-title"
      className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
    >
      <h3 id="opportunity-history-title" className="font-semibold">
        Historial inmutable
      </h3>
      <div className="mt-3 grid gap-4 xl:grid-cols-2">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
            Etapas
          </h4>
          <ol className="mt-2 space-y-2">
            {opportunity.stage_events.map((event) => (
              <li
                key={event.id}
                className="rounded border border-[var(--border-color)] p-2 text-xs"
              >
                <p>
                  {event.from_stage ? `${STAGE_LABELS[event.from_stage]} → ` : ""}
                  {STAGE_LABELS[event.to_stage]}
                </p>
                <p className="mt-1 text-[var(--text-muted)]">
                  v{event.control_version} · {formatDate(event.created_at)}
                </p>
                {event.reason && (
                  <p className="mt-1 text-[var(--text-secondary)]">{event.reason}</p>
                )}
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
            Ownership
          </h4>
          <ol className="mt-2 space-y-2">
            {opportunity.ownership_events.map((event) => (
              <li
                key={event.id}
                className="rounded border border-[var(--border-color)] p-2 text-xs"
              >
                <p>{event.event_type === "created" ? "Asignación inicial" : "Reasignación"}</p>
                <p className="mt-1 break-all text-[var(--text-muted)]">
                  Agente {event.to_agent_id} · v{event.control_version}
                </p>
                {event.reason && (
                  <p className="mt-1 text-[var(--text-secondary)]">{event.reason}</p>
                )}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}

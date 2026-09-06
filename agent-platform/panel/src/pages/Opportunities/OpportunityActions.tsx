import { useState } from "react";
import type { AgentProfile } from "../../agents/types";
import { STAGE_LABELS } from "./presentation";
import type { CommercialOperator, OpportunityDetail, OpportunityStage } from "./types";

interface Props {
  opportunity: OpportunityDetail;
  agents: AgentProfile[];
  operators: CommercialOperator[];
  busy: boolean;
  canManage: boolean;
  onStage: (stage: OpportunityStage, reason?: string) => void;
  onReassign: (agentId: string, operatorId?: string, reason?: string) => void;
  onLinkConversation: (conversationId: string) => void;
}

export function OpportunityActions({
  opportunity,
  agents,
  operators,
  busy,
  canManage,
  onStage,
  onReassign,
  onLinkConversation,
}: Props) {
  const [stage, setStage] = useState<OpportunityStage>(opportunity.stage);
  const [stageReason, setStageReason] = useState("");
  const [agentId, setAgentId] = useState(opportunity.assigned_agent.id);
  const [operatorId, setOperatorId] = useState(opportunity.assigned_operator?.id ?? "");
  const [assignmentReason, setAssignmentReason] = useState("");
  const [conversationId, setConversationId] = useState("");
  const closed = opportunity.stage === "won" || opportunity.stage === "lost";

  if (!canManage) {
    return (
      <p className="rounded border border-[var(--border-color)] p-3 text-sm text-[var(--text-muted)]">
        Tu rol permite revisar el expediente, pero no modificarlo.
      </p>
    );
  }

  return (
    <section aria-labelledby="opportunity-actions-title" className="grid gap-3 xl:grid-cols-3">
      <h3 id="opportunity-actions-title" className="sr-only">
        Acciones de oportunidad
      </h3>
      <form
        className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
        onSubmit={(event) => {
          event.preventDefault();
          onStage(stage, stageReason.trim() || undefined);
        }}
      >
        <h4 className="text-sm font-semibold">Cambiar etapa</h4>
        <label className="mt-3 block text-xs text-[var(--text-muted)]">
          Nueva etapa
          <select
            value={stage}
            disabled={closed}
            onChange={(event) => setStage(event.target.value as OpportunityStage)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
          >
            {Object.entries(STAGE_LABELS).map(([value, label]) => (
              <option key={value} value={value} disabled={value === "new"}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="mt-2 block text-xs text-[var(--text-muted)]">
          Motivo
          <input
            value={stageReason}
            maxLength={8_000}
            onChange={(event) => setStageReason(event.target.value)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
          />
        </label>
        <ActionSubmit
          disabled={busy || closed || stage === opportunity.stage}
          label="Actualizar etapa"
        />
      </form>

      <form
        className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
        onSubmit={(event) => {
          event.preventDefault();
          onReassign(agentId, operatorId || undefined, assignmentReason.trim() || undefined);
        }}
      >
        <h4 className="text-sm font-semibold">Handoff y responsable</h4>
        <label className="mt-3 block text-xs text-[var(--text-muted)]">
          Agente
          <select
            value={agentId}
            onChange={(event) => {
              setAgentId(event.target.value);
              if (event.target.value !== opportunity.assigned_agent.id) setOperatorId("");
            }}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
          >
            {agents
              .filter((agent) => agent.is_active)
              .map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
          </select>
        </label>
        <label className="mt-2 block text-xs text-[var(--text-muted)]">
          Operador
          <select
            value={operatorId}
            disabled={agentId !== opportunity.assigned_agent.id}
            onChange={(event) => setOperatorId(event.target.value)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
          >
            <option value="">Sin operador</option>
            {operators.map((operator) => (
              <option key={operator.id} value={operator.id}>
                {operator.name}
              </option>
            ))}
          </select>
        </label>
        {agentId !== opportunity.assigned_agent.id && (
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            El handoff deja la oportunidad sin operador; el agente de destino podrá asignar uno con
            acceso.
          </p>
        )}
        <label className="mt-2 block text-xs text-[var(--text-muted)]">
          Motivo
          <input
            value={assignmentReason}
            maxLength={8_000}
            onChange={(event) => setAssignmentReason(event.target.value)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
          />
        </label>
        <ActionSubmit
          disabled={
            busy ||
            (agentId === opportunity.assigned_agent.id &&
              operatorId === (opportunity.assigned_operator?.id ?? ""))
          }
          label="Reasignar"
        />
      </form>

      <form
        className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (conversationId) onLinkConversation(conversationId);
        }}
      >
        <h4 className="text-sm font-semibold">Vincular conversación</h4>
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          El vínculo no cambia el agente que atiende el chat.
        </p>
        <label className="mt-3 block text-xs text-[var(--text-muted)]">
          Conversación del contacto
          <select
            value={conversationId}
            onChange={(event) => setConversationId(event.target.value)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
          >
            <option value="">Seleccionar…</option>
            {opportunity.available_conversations.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>
                {conversation.channel} · {conversation.route_key}
              </option>
            ))}
          </select>
        </label>
        {opportunity.available_conversations.length === 0 && (
          <p className="mt-3 text-xs text-[var(--text-muted)]">
            No hay otras conversaciones disponibles.
          </p>
        )}
        <ActionSubmit disabled={busy || !conversationId} label="Vincular" />
      </form>
    </section>
  );
}

function ActionSubmit({ disabled, label }: { disabled: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="mt-3 w-full rounded border border-[var(--accent)]/50 px-3 py-2 text-sm text-[var(--accent-hover)] disabled:opacity-50"
    >
      {label}
    </button>
  );
}

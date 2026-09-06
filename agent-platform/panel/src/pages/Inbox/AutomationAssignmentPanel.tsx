import { Bot, ChevronDown, History, LoaderCircle } from "lucide-react";
import type { AgentProfile } from "../../agents/types";
import type {
  AutomationAssignmentEvent,
  ConversationControlMode,
  InboxAgent,
} from "../../inbox/types";
import { formatDate } from "./presentation";

interface AutomationAssignmentPanelProps {
  automationAgent: InboxAgent;
  automationVersion: number;
  controlMode: ConversationControlMode;
  agents: AgentProfile[];
  selectedAgentId: string;
  canAssign: boolean;
  busy: boolean;
  historyVisible: boolean;
  historyLoading: boolean;
  historyItems: AutomationAssignmentEvent[];
  historyTotal: number;
  onAgentChange: (agentId: string) => void;
  onAssign: () => void;
  onToggleHistory: () => void;
  onLoadMoreHistory: () => void;
}

export function AutomationAssignmentPanel({
  automationAgent,
  automationVersion,
  controlMode,
  agents,
  selectedAgentId,
  canAssign,
  busy,
  historyVisible,
  historyLoading,
  historyItems,
  historyTotal,
  onAgentChange,
  onAssign,
  onToggleHistory,
  onLoadMoreHistory,
}: AutomationAssignmentPanelProps) {
  const isClosed = controlMode === "closed";
  const isAutomationStopped = controlMode === "paused" || controlMode === "human";
  const hasChangedAgent = selectedAgentId !== automationAgent.id;
  const currentAgentIsAvailable = agents.some((agent) => agent.id === automationAgent.id);

  return (
    <section
      aria-labelledby="automation-assignment-title"
      className="border-b border-[var(--border-color)] bg-[var(--bg-secondary)]/35 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4
            id="automation-assignment-title"
            className="flex items-center gap-2 text-sm font-semibold"
          >
            <Bot size={16} className="text-[var(--accent)]" /> Respuesta automática
          </h4>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            Agente actual: {automationAgent.name} · versión {automationVersion}
          </p>
        </div>
        <button
          type="button"
          onClick={onToggleHistory}
          aria-expanded={historyVisible}
          aria-controls="automation-assignment-history"
          className="inline-flex min-h-9 items-center gap-1.5 rounded border border-[var(--border-color)] px-2.5 text-xs"
        >
          <History size={14} /> {historyVisible ? "Ocultar historial" : "Ver historial"}
          <ChevronDown
            size={14}
            aria-hidden="true"
            className={`transition-transform ${historyVisible ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {canAssign && (
        <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <label className="text-xs text-[var(--text-muted)]">
            Agente que responde automáticamente
            <select
              value={selectedAgentId}
              onChange={(event) => onAgentChange(event.target.value)}
              disabled={busy || isClosed}
              className="mt-1 min-h-11 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 text-sm text-[var(--text-primary)] disabled:opacity-50"
            >
              {!currentAgentIsAvailable && (
                <option value={automationAgent.id} disabled>
                  {automationAgent.name} (no disponible)
                </option>
              )}
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || isClosed || !selectedAgentId || !hasChangedAgent}
            onClick={onAssign}
            className="min-h-11 rounded bg-[var(--accent)] px-4 text-sm font-medium text-white disabled:opacity-50"
          >
            Asignar respuesta automática
          </button>
        </div>
      )}

      {isAutomationStopped && (
        <p className="mt-2 text-xs text-amber-300">
          Podés preparar otro agente, pero esta acción no reanuda la automatización ni cambia al
          operador responsable.
        </p>
      )}
      {isClosed && (
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          La conversación está cerrada y no admite nuevas asignaciones.
        </p>
      )}
      {!canAssign && !isClosed && (
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          Tu acceso permite ver el agente automático, pero no cambiarlo.
        </p>
      )}

      {historyVisible && (
        <div id="automation-assignment-history" className="mt-4">
          {historyLoading && historyItems.length === 0 ? (
            <p role="status" className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
              <LoaderCircle className="animate-spin" size={14} /> Cargando historial…
            </p>
          ) : historyItems.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">Todavía no hay reasignaciones.</p>
          ) : (
            <ol className="space-y-2">
              {historyItems.map((event) => (
                <li
                  key={event.event_id}
                  className="rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-3 text-xs"
                >
                  <p className="font-medium text-[var(--text-primary)]">
                    {event.from_automation_agent.name} → {event.to_automation_agent.name}
                  </p>
                  <p className="mt-1 text-[var(--text-muted)]">
                    Versión {event.automation_version} · {formatDate(event.created_at)}
                    {!event.applied && " · Sin cambios"}
                  </p>
                  {event.reason && (
                    <p className="mt-1 break-words text-[var(--text-secondary)]">{event.reason}</p>
                  )}
                </li>
              ))}
            </ol>
          )}
          {historyItems.length < historyTotal && (
            <button
              type="button"
              disabled={historyLoading}
              onClick={onLoadMoreHistory}
              className="mt-3 min-h-9 rounded border border-[var(--border-color)] px-3 text-xs disabled:opacity-50"
            >
              {historyLoading ? "Cargando…" : "Cargar más"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

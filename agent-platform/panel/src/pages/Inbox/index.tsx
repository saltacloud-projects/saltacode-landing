import { Inbox, RefreshCw } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { CrmPagination, CrmScopeFilter, canOperateItem, useCrmScope } from "../../crm/operations";
import { useInboxLive } from "../../inbox/InboxLiveContext";
import { InboxFiltersForm } from "./InboxFilters";
import { InboxShell } from "./InboxShell";
import { useInboxState } from "./useInboxState";

export default function InboxPage() {
  const scope = useCrmScope("inbox");
  const { snapshot, connected } = useInboxLive();
  const { selectedAgent } = scope;
  const { profiles } = useAgentWorkspace();
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.CONVERSATIONS_MANAGE);
  const canAssignAutomation = canManage && hasPermission(user, PERMISSIONS.RUNTIME_MANAGE);
  const automationAgents = scope.global
    ? scope.agents.filter(
        (agent) =>
          agent.is_active &&
          agent.capabilities.includes(PERMISSIONS.RUNTIME_MANAGE) &&
          agent.capabilities.includes(PERMISSIONS.CONVERSATIONS_MANAGE),
      )
    : profiles.filter((profile) => profile.is_active);
  const inbox = useInboxState({
    agentId: scope.agentId,
    global: scope.global,
    offset: scope.offset,
    user,
    canManage,
  });

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <Inbox size={23} className="text-[var(--accent)]" />
        <div>
          <h2 className="text-xl font-semibold">
            Inbox{selectedAgent ? ` de ${selectedAgent.name}` : ""}
          </h2>
          <p className="text-sm text-[var(--text-muted)]">
            Atención multicanal con control humano por conversación.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void inbox.refreshList()}
          className="ml-auto inline-flex items-center gap-2 rounded border border-[var(--border-color)] px-3 py-2 text-sm"
        >
          <RefreshCw size={16} /> Actualizar
        </button>
      </header>
      <p role="status" className="mb-3 text-xs text-[var(--text-muted)]">
        {connected
          ? "Actualización en tiempo real"
          : "Reconectando actualización en vivo; revisión automática de respaldo activa."}
      </p>
      <fieldset aria-label="Vista de conversaciones" className="mb-2 flex flex-wrap gap-2">
        {(
          [
            ["active", "Activas"],
            ["history", "Históricas"],
            ["all", "Todas"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={inbox.filters.lifecycle === value}
            onClick={() => {
              scope.setOffset(0);
              inbox.setFilters({ ...inbox.filters, lifecycle: value, status: "", controlMode: "" });
            }}
            className={`min-h-11 rounded-lg border px-4 text-sm ${inbox.filters.lifecycle === value ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]" : "border-[var(--border-color)]"}`}
          >
            {label}
            {!scope.agentId && snapshot && value !== "all"
              ? ` (${value === "active" ? snapshot.active_conversations : snapshot.historical_conversations})`
              : ""}
          </button>
        ))}
      </fieldset>
      <p className="mb-4 max-w-3xl text-xs text-[var(--text-muted)]">
        Activas: conversaciones abiertas, incluso pausadas o en atención manual. Históricas:
        conversaciones cerradas. El indicador cuenta conversaciones activas con mensajes del
        visitante sin leer por vos; no personas conectadas.
      </p>
      <CrmScopeFilter scope={scope} label="Agente de ingreso" />

      <CrmPagination
        offset={scope.offset}
        total={inbox.total}
        loading={inbox.loadingList}
        onChange={scope.setOffset}
      />
      <InboxFiltersForm
        filters={inbox.filters}
        operators={inbox.operators}
        onChange={(filters) => {
          scope.setOffset(0);
          inbox.setFilters(filters);
        }}
      />

      {inbox.error && (
        <p
          role="alert"
          className="mb-4 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]"
        >
          {inbox.error}
        </p>
      )}

      <InboxShell
        items={inbox.items}
        thread={inbox.thread}
        operators={inbox.operators}
        currentAdminId={user?.id ?? ""}
        canManage={canOperateItem(
          scope.global,
          inbox.thread?.conversation,
          user,
          PERMISSIONS.CONVERSATIONS_MANAGE,
        )}
        canAssignAutomation={
          canAssignAutomation &&
          canOperateItem(scope.global, inbox.thread?.conversation, user, PERMISSIONS.RUNTIME_MANAGE)
        }
        automationAgents={automationAgents}
        ownsConversation={inbox.ownsConversation}
        loadingList={inbox.loadingList}
        loadingThread={inbox.loadingThread}
        busy={inbox.busy}
        draft={inbox.draft}
        reassignTo={inbox.reassignTo}
        automationAgentTo={inbox.automationAgentTo}
        automationAssignmentNotice={inbox.automationAssignmentNotice}
        assignmentHistoryVisible={inbox.assignmentHistoryVisible}
        assignmentHistoryLoading={inbox.assignmentHistoryLoading}
        assignmentHistoryItems={inbox.assignmentHistoryItems}
        assignmentHistoryTotal={inbox.assignmentHistoryTotal}
        onMessagesRead={inbox.markVisibleMessagesRead}
        onSelect={inbox.openConversation}
        onDraftChange={inbox.setDraft}
        onReassignChange={inbox.setReassignTo}
        onAutomationAgentChange={inbox.selectAutomationAgent}
        onBack={inbox.closeThread}
        onSend={() => void inbox.sendMessage()}
        onTransition={(transition) => void inbox.runTransition(transition)}
        onAssignAutomation={() => void inbox.assignAutomationAgent()}
        onToggleAssignmentHistory={() => void inbox.toggleAssignmentHistory()}
        onLoadMoreAssignmentHistory={() => void inbox.loadMoreAssignmentHistory()}
      />
    </div>
  );
}

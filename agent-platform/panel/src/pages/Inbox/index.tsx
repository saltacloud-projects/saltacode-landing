import { Inbox, RefreshCw, SlidersHorizontal } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { CrmPagination, CrmScopeFilter, canOperateItem, useCrmScope } from "../../crm/operations";
import { useInboxLive } from "../../inbox/InboxLiveContext";
import { InboxFiltersForm, InboxSearch } from "./InboxFilters";
import { InboxShell } from "./InboxShell";
import { useInboxState } from "./useInboxState";

export default function InboxPage() {
  const scope = useCrmScope("inbox");
  const { connected } = useInboxLive();
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
    <div className="mx-auto flex h-full min-h-0 w-full max-w-[1700px] flex-col">
      {inbox.error && (
        <p
          role="alert"
          className="mb-2 shrink-0 rounded border border-[color-mix(in_srgb,var(--error)_35%,transparent)] bg-[color-mix(in_srgb,var(--error)_5%,transparent)] p-3 text-sm text-[var(--error)]"
        >
          {inbox.error}
        </p>
      )}

      <InboxShell
        listHeader={
          <>
            <header className="flex items-center gap-3 p-4 pb-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] text-[var(--accent-hover)]">
                <Inbox size={21} />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-lg font-semibold">
                  Inbox{selectedAgent ? ` de ${selectedAgent.name}` : ""}
                </h2>
                <p
                  role="status"
                  aria-label={
                    connected
                      ? "Actualización en tiempo real"
                      : "Reconectando actualización en vivo"
                  }
                  className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]"
                >
                  <span
                    aria-hidden="true"
                    className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-amber-300"}`}
                  />
                  {connected ? "En vivo" : "Reconectando…"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void inbox.refreshList()}
                aria-label="Actualizar conversaciones"
                title="Actualizar conversaciones"
                className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
              >
                <RefreshCw size={18} />
              </button>
            </header>
            <div className="space-y-3 px-3 pb-3">
              <InboxSearch
                value={inbox.filters.search ?? ""}
                onChange={(search) => {
                  scope.setOffset(0);
                  inbox.setFilters({ ...inbox.filters, search });
                }}
              />
              <fieldset
                aria-label="Vista de conversaciones"
                className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4"
              >
                {(
                  [
                    ["active", "Activas"],
                    ["unread", "No leídas"],
                    ["history", "Historial"],
                    ["all", "Todas"],
                  ] as const
                ).map(([value, label]) => {
                  const pressed =
                    value === "unread"
                      ? Boolean(inbox.filters.unreadOnly)
                      : !inbox.filters.unreadOnly && inbox.filters.lifecycle === value;
                  return (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={pressed}
                      onClick={() => {
                        scope.setOffset(0);
                        inbox.setFilters({
                          ...inbox.filters,
                          lifecycle: value === "unread" ? "active" : value,
                          unreadOnly: value === "unread",
                          status: "",
                          controlMode: "",
                        });
                      }}
                      className={`min-h-11 rounded-full border px-2 text-xs font-medium ${pressed ? "border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] text-[var(--accent-hover)]" : "border-[var(--border-color)] text-[var(--text-secondary)]"}`}
                    >
                      {label}
                    </button>
                  );
                })}
              </fieldset>
              <details
                className="group"
                onToggle={(event) => {
                  if (!event.currentTarget.open)
                    event.currentTarget.querySelector("summary")?.focus();
                }}
              >
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 rounded-lg px-1 text-xs font-medium text-[var(--text-secondary)]">
                  <span className="flex items-center gap-2">
                    <SlidersHorizontal size={15} />
                    Filtros y alcance
                  </span>
                  <span className="text-[var(--text-secondary)]">
                    {[
                      inbox.filters.channel,
                      inbox.filters.controlMode,
                      inbox.filters.owner,
                      scope.agentId,
                      inbox.filters.lastMessagePeriod !== "all" && inbox.filters.lastMessagePeriod,
                    ].filter(Boolean).length || ""}
                  </span>
                </summary>
                <div className="max-h-[40dvh] space-y-3 overflow-y-auto overscroll-contain rounded-lg border border-[var(--border-color)] p-3">
                  <CrmScopeFilter scope={scope} label="Agente de ingreso" />
                  <InboxFiltersForm
                    filters={inbox.filters}
                    operators={inbox.operators}
                    onChange={(filters) => {
                      scope.setOffset(0);
                      inbox.setFilters(filters);
                    }}
                  />
                  <p className="text-[11px] leading-relaxed text-[var(--text-secondary)]">
                    Activas: conversaciones abiertas, incluso pausadas o en atención manual.
                    Historial: cerradas. No leídas: abiertas con mensajes del visitante sin leer por
                    vos, no personas conectadas.
                  </p>
                </div>
              </details>
            </div>
          </>
        }
        listFooter={
          <div className="border-t border-[var(--border-color)] px-3 text-xs [&_button]:min-h-11">
            <CrmPagination
              singlePageLabel={`${inbox.total} ${inbox.total === 1 ? "conversación" : "conversaciones"}`}
              offset={scope.offset}
              total={inbox.total}
              loading={inbox.loadingList}
              onChange={scope.setOffset}
            />
          </div>
        }
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
        onBack={() => {
          inbox.closeThread();
          window.requestAnimationFrame(() => document.getElementById("inbox-search")?.focus());
        }}
        onSend={() => void inbox.sendMessage()}
        onTransition={(transition) => void inbox.runTransition(transition)}
        onAssignAutomation={() => void inbox.assignAutomationAgent()}
        onToggleAssignmentHistory={() => void inbox.toggleAssignmentHistory()}
        onLoadMoreAssignmentHistory={() => void inbox.loadMoreAssignmentHistory()}
      />
    </div>
  );
}

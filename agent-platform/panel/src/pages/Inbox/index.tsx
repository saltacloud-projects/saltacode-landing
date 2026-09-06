import { Inbox, RefreshCw } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { InboxFiltersForm } from "./InboxFilters";
import { InboxShell } from "./InboxShell";
import { useInboxState } from "./useInboxState";

export default function InboxPage() {
  const { profiles, selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.CONVERSATIONS_MANAGE);
  const canAssignAutomation = canManage && hasPermission(user, PERMISSIONS.RUNTIME_MANAGE);
  const automationAgents = profiles.filter((profile) => profile.is_active);
  const inbox = useInboxState({ agentId: selectedAgent?.id, user, canManage });

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <Inbox size={23} className="text-[var(--accent)]" />
        <div>
          <h2 className="text-xl font-semibold">Inbox de {selectedAgent?.name}</h2>
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

      <InboxFiltersForm
        filters={inbox.filters}
        operators={inbox.operators}
        onChange={inbox.setFilters}
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
        canManage={canManage}
        canAssignAutomation={canAssignAutomation}
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

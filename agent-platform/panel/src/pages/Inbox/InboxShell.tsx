import type { ReactNode } from "react";
import type { AgentProfile } from "../../agents/types";
import type {
  AutomationAssignmentEvent,
  ControlTransition,
  InboxConversation,
  InboxOperator,
  InboxThread,
} from "../../inbox/types";
import { ConversationList } from "./ConversationList";
import { ConversationThread } from "./ConversationThread";

interface InboxShellProps {
  listHeader: ReactNode;
  listFooter: ReactNode;
  items: InboxConversation[];
  thread: InboxThread | null;
  operators: InboxOperator[];
  currentAdminId: string;
  canManage: boolean;
  canAssignAutomation: boolean;
  automationAgents: Pick<AgentProfile, "id" | "name" | "is_active">[];
  ownsConversation: boolean;
  loadingList: boolean;
  loadingThread: boolean;
  busy: boolean;
  draft: string;
  reassignTo: string;
  automationAgentTo: string;
  automationAssignmentNotice: string;
  assignmentHistoryVisible: boolean;
  assignmentHistoryLoading: boolean;
  assignmentHistoryItems: AutomationAssignmentEvent[];
  assignmentHistoryTotal: number;
  onMessagesRead: (conversationId: string, messageIds: string[]) => Promise<boolean>;
  onSelect: (conversation: InboxConversation) => void;
  onDraftChange: (value: string) => void;
  onReassignChange: (value: string) => void;
  onAutomationAgentChange: (value: string) => void;
  onBack: () => void;
  onSend: () => void;
  onTransition: (transition: Omit<ControlTransition, "expected_version">) => void;
  onAssignAutomation: () => void;
  onToggleAssignmentHistory: () => void;
  onLoadMoreAssignmentHistory: () => void;
}

export function InboxShell({
  listHeader,
  listFooter,
  items,
  thread,
  operators,
  currentAdminId,
  canManage,
  canAssignAutomation,
  automationAgents,
  ownsConversation,
  loadingList,
  loadingThread,
  busy,
  draft,
  reassignTo,
  automationAgentTo,
  automationAssignmentNotice,
  assignmentHistoryVisible,
  assignmentHistoryLoading,
  assignmentHistoryItems,
  assignmentHistoryTotal,
  onMessagesRead,
  onSelect,
  onDraftChange,
  onReassignChange,
  onAutomationAgentChange,
  onBack,
  onSend,
  onTransition,
  onAssignAutomation,
  onToggleAssignmentHistory,
  onLoadMoreAssignmentHistory,
}: InboxShellProps) {
  return (
    <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(290px,360px)_minmax(0,1fr)]">
      <div
        className={`${thread ? "hidden lg:flex" : "flex"} min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)]`}
      >
        <div className="shrink-0">{listHeader}</div>
        <ConversationList
          items={items}
          selectedId={thread?.conversation.id}
          loading={loadingList}
          hiddenOnMobile={Boolean(thread)}
          onSelect={onSelect}
        />
        <div className="shrink-0">{listFooter}</div>
      </div>
      <ConversationThread
        thread={thread}
        operators={operators}
        currentAdminId={currentAdminId}
        canManage={canManage}
        canAssignAutomation={canAssignAutomation}
        automationAgents={automationAgents}
        ownsConversation={ownsConversation}
        loading={loadingThread}
        busy={busy}
        draft={draft}
        reassignTo={reassignTo}
        automationAgentTo={automationAgentTo}
        automationAssignmentNotice={automationAssignmentNotice}
        assignmentHistoryVisible={assignmentHistoryVisible}
        assignmentHistoryLoading={assignmentHistoryLoading}
        assignmentHistoryItems={assignmentHistoryItems}
        assignmentHistoryTotal={assignmentHistoryTotal}
        onMessagesRead={onMessagesRead}
        onDraftChange={onDraftChange}
        onReassignChange={onReassignChange}
        onAutomationAgentChange={onAutomationAgentChange}
        onBack={onBack}
        onSend={onSend}
        onTransition={onTransition}
        onAssignAutomation={onAssignAutomation}
        onToggleAssignmentHistory={onToggleAssignmentHistory}
        onLoadMoreAssignmentHistory={onLoadMoreAssignmentHistory}
      />
    </div>
  );
}

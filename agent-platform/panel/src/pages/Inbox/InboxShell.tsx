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
  items: InboxConversation[];
  thread: InboxThread | null;
  operators: InboxOperator[];
  currentAdminId: string;
  canManage: boolean;
  canAssignAutomation: boolean;
  automationAgents: AgentProfile[];
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
    <div className="grid min-h-[68vh] gap-4 lg:grid-cols-[minmax(290px,380px)_1fr]">
      <ConversationList
        items={items}
        selectedId={thread?.conversation.id}
        loading={loadingList}
        hiddenOnMobile={Boolean(thread)}
        onSelect={onSelect}
      />
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

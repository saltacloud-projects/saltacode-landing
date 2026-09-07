import type { AgentProfile } from "../../agents/types";
import type {
  AutomationAssignmentEvent,
  ControlTransition,
  InboxOperator,
  InboxThread,
} from "../../inbox/types";
import { AutomationAssignmentPanel } from "./AutomationAssignmentPanel";
import { MessageComposer } from "./MessageComposer";
import { ThreadHeader } from "./ThreadHeader";
import { ThreadMessages } from "./ThreadMessages";

interface ConversationThreadProps {
  thread: InboxThread | null;
  operators: InboxOperator[];
  currentAdminId: string;
  canManage: boolean;
  canAssignAutomation: boolean;
  automationAgents: Pick<AgentProfile, "id" | "name" | "is_active">[];
  ownsConversation: boolean;
  loading: boolean;
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

export function ConversationThread({
  thread,
  operators,
  currentAdminId,
  canManage,
  canAssignAutomation,
  automationAgents,
  ownsConversation,
  loading,
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
  onDraftChange,
  onReassignChange,
  onAutomationAgentChange,
  onBack,
  onSend,
  onTransition,
  onAssignAutomation,
  onToggleAssignmentHistory,
  onLoadMoreAssignmentHistory,
}: ConversationThreadProps) {
  return (
    <section
      aria-label="Detalle de conversación"
      className={`${thread ? "flex" : "hidden lg:flex"} min-w-0 min-h-[520px] flex-col overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]`}
    >
      {!thread ? (
        <div className="grid flex-1 place-items-center p-6 text-center text-sm text-[var(--text-muted)]">
          Seleccioná una conversación para atenderla.
        </div>
      ) : (
        <>
          <ThreadHeader
            conversation={thread.conversation}
            operators={operators}
            currentAdminId={currentAdminId}
            canManage={canManage}
            busy={busy}
            reassignTo={reassignTo}
            onReassignChange={onReassignChange}
            onBack={onBack}
            onTransition={onTransition}
          />
          <AutomationAssignmentPanel
            automationAgent={thread.conversation.automation_agent}
            automationVersion={thread.conversation.automation_version}
            controlMode={thread.conversation.control_mode}
            agents={automationAgents}
            selectedAgentId={automationAgentTo}
            canAssign={canAssignAutomation}
            busy={busy}
            historyVisible={assignmentHistoryVisible}
            historyLoading={assignmentHistoryLoading}
            historyItems={assignmentHistoryItems}
            historyTotal={assignmentHistoryTotal}
            onAgentChange={onAutomationAgentChange}
            onAssign={onAssignAutomation}
            onToggleHistory={onToggleAssignmentHistory}
            onLoadMoreHistory={onLoadMoreAssignmentHistory}
          />
          {automationAssignmentNotice && (
            <p
              role="status"
              className="border-b border-[var(--border-color)] bg-emerald-500/10 px-4 py-2 text-xs text-emerald-300"
            >
              {automationAssignmentNotice}
            </p>
          )}
          <ThreadMessages
            key={thread.conversation.id}
            thread={thread}
            loading={loading}
            onMessagesRead={onMessagesRead}
          />
          {ownsConversation ? (
            <MessageComposer value={draft} busy={busy} onChange={onDraftChange} onSubmit={onSend} />
          ) : (
            <p className="border-t border-[var(--border-color)] p-3 text-xs text-[var(--text-muted)]">
              {canManage
                ? "Tomá el control de esta conversación para responder."
                : "Tu rol permite revisar el historial, pero no intervenir."}
            </p>
          )}
        </>
      )}
    </section>
  );
}

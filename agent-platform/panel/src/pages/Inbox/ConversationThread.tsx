import { LoaderCircle } from "lucide-react";
import type { AgentProfile } from "../../agents/types";
import type {
  AutomationAssignmentEvent,
  ControlTransition,
  InboxOperator,
  InboxThread,
} from "../../inbox/types";
import { AutomationAssignmentPanel } from "./AutomationAssignmentPanel";
import { MessageComposer } from "./MessageComposer";
import { formatDate } from "./presentation";
import { ThreadHeader } from "./ThreadHeader";

interface ConversationThreadProps {
  thread: InboxThread | null;
  operators: InboxOperator[];
  currentAdminId: string;
  canManage: boolean;
  canAssignAutomation: boolean;
  automationAgents: AgentProfile[];
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
      className={`${thread ? "flex" : "hidden lg:flex"} min-h-[520px] flex-col overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]`}
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
          <div
            className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4"
            role="log"
            aria-label="Mensajes de la conversación"
          >
            {loading && thread.messages.length === 0 ? (
              <LoaderCircle className="animate-spin text-[var(--text-muted)]" size={18} />
            ) : (
              thread.messages.map((message) => (
                <article
                  key={message.id}
                  className={`max-w-[90%] rounded-xl px-3 py-2 text-sm ${message.role === "user" ? "ml-auto bg-[var(--accent)] text-white" : "mr-auto border border-[var(--border-color)] bg-[var(--bg-secondary)]"}`}
                >
                  <p className="whitespace-pre-wrap break-words">{message.content}</p>
                  <footer
                    className={`mt-2 flex flex-wrap gap-1 text-[10px] ${message.role === "user" ? "text-white/75" : "text-[var(--text-muted)]"}`}
                  >
                    <span>{formatDate(message.created_at)}</span>
                    {message.origin === "operator" && <span>· Operador</span>}
                    {message.status !== "completed" && <span>· {message.status}</span>}
                  </footer>
                </article>
              ))
            )}
          </div>
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

import { useEffect, useState } from "react";
import type { AgentProfile } from "../../agents/types";
import type {
  AutomationAssignmentEvent,
  ControlTransition,
  InboxOperator,
  InboxThread,
} from "../../inbox/types";
import { AutomationAssignmentPanel } from "./AutomationAssignmentPanel";
import { MessageComposer } from "./MessageComposer";
import { ConversationControls, ThreadHeader } from "./ThreadHeader";
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
  const [controlsOpen, setControlsOpen] = useState(false);
  const conversationId = thread?.conversation.id;
  useEffect(() => {
    if (conversationId) setControlsOpen(false);
  }, [conversationId]);
  useEffect(() => {
    if (!controlsOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setControlsOpen(false);
      document
        .querySelector<HTMLButtonElement>('[aria-controls="inbox-conversation-controls"]')
        ?.focus();
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [controlsOpen]);
  return (
    <section
      aria-label="Detalle de conversación"
      className={`${thread ? "flex" : "hidden lg:flex"} min-w-0 min-h-0 flex-col overflow-hidden rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)]`}
    >
      {!thread ? (
        <div className="grid flex-1 place-items-center p-6 text-center text-sm text-[var(--text-secondary)]">
          Seleccioná una conversación para atenderla.
        </div>
      ) : (
        <>
          <ThreadHeader
            controlsOpen={controlsOpen}
            onToggleControls={() => setControlsOpen((value) => !value)}
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
          <div className="relative flex min-h-0 flex-1 flex-col bg-[var(--bg-primary)]">
            <ThreadMessages
              key={thread.conversation.id}
              thread={thread}
              obscured={controlsOpen}
              loading={loading}
              onMessagesRead={onMessagesRead}
            />
            {controlsOpen && (
              <section
                id="inbox-conversation-controls"
                aria-label="Configuración de la conversación"
                className="absolute inset-0 z-20 overflow-y-auto overscroll-contain bg-[var(--bg-card)]"
              >
                <ConversationControls
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

                <details className="border-t border-[var(--border-color)] p-4">
                  <summary className="min-h-11 cursor-pointer text-sm font-medium">
                    Historial de control
                  </summary>
                  <ol className="space-y-2 text-xs text-[var(--text-secondary)]">
                    {thread.control_events.map((event) => (
                      <li
                        key={event.id}
                        className="rounded-lg border border-[var(--border-color)] p-3"
                      >
                        {event.event_type} · {event.from_mode} → {event.to_mode}
                        <p className="mt-1 text-[var(--text-secondary)]">
                          Versión {event.control_version} ·{" "}
                          {new Date(event.created_at).toLocaleString("es-AR")}
                        </p>
                        {event.reason && <p className="mt-1 break-words">{event.reason}</p>}
                      </li>
                    ))}
                    {thread.control_events.length === 0 && (
                      <li>Sin eventos de control registrados.</li>
                    )}
                  </ol>
                </details>
              </section>
            )}
          </div>
          {ownsConversation ? (
            <MessageComposer value={draft} busy={busy} onChange={onDraftChange} onSubmit={onSend} />
          ) : (
            <p className="shrink-0 border-t border-[var(--border-color)] bg-[var(--bg-card)] p-3 text-xs text-[var(--text-secondary)]">
              {thread.conversation.control_mode === "closed" ||
              thread.conversation.status === "closed"
                ? "Conversación cerrada. El historial permanece disponible."
                : canManage
                  ? "Tomá el control de esta conversación para responder."
                  : "Tu rol permite revisar el historial, pero no intervenir."}
            </p>
          )}
        </>
      )}
    </section>
  );
}

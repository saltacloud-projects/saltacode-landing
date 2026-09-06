import type {
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
  ownsConversation: boolean;
  loadingList: boolean;
  loadingThread: boolean;
  busy: boolean;
  draft: string;
  reassignTo: string;
  onSelect: (conversation: InboxConversation) => void;
  onDraftChange: (value: string) => void;
  onReassignChange: (value: string) => void;
  onBack: () => void;
  onSend: () => void;
  onTransition: (transition: Omit<ControlTransition, "expected_version">) => void;
}

export function InboxShell({
  items,
  thread,
  operators,
  currentAdminId,
  canManage,
  ownsConversation,
  loadingList,
  loadingThread,
  busy,
  draft,
  reassignTo,
  onSelect,
  onDraftChange,
  onReassignChange,
  onBack,
  onSend,
  onTransition,
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
        ownsConversation={ownsConversation}
        loading={loadingThread}
        busy={busy}
        draft={draft}
        reassignTo={reassignTo}
        onDraftChange={onDraftChange}
        onReassignChange={onReassignChange}
        onBack={onBack}
        onSend={onSend}
        onTransition={onTransition}
      />
    </div>
  );
}

import { api } from "../api/client";
import { type CrmListOptions, listPath } from "../crm/operations";
import { lastMessageBounds } from "./last-message-range";
import type {
  AutomationAssignmentHistoryPage,
  AutomationAssignmentReceipt,
  AutomationAssignmentRequest,
  ControlTransition,
  InboxConversationPage,
  InboxFilters,
  InboxOperator,
  InboxThread,
  TypingState,
} from "./types";

export function publishOperatorPresence(
  agentId: string,
  conversationId: string,
  signal: {
    client_instance_id: string;
    sequence: number;
    typing: boolean;
    expected_control_version: number;
  },
): Promise<TypingState> {
  return api(`${inboxRoot(agentId)}/${encodeURIComponent(conversationId)}/presence`, {
    method: "POST",
    keepalive: true,
    body: JSON.stringify(signal),
  });
}

function inboxRoot(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/inbox`;
}

export async function listInboxConversations(
  agentId: string,
  filters: InboxFilters,
  currentAdminId: string,
  options: CrmListOptions = {},
): Promise<InboxConversationPage> {
  const query = new URLSearchParams();
  if (filters.search?.trim()) query.set("search", filters.search.trim());
  if (filters.unreadOnly) query.set("unread_only", "true");
  const bounds = lastMessageBounds(filters);
  if (bounds) {
    query.set("last_message_from", bounds.from);
    query.set("last_message_before", bounds.before);
  }
  if (filters.channel) query.set("channel", filters.channel);
  if (filters.controlMode) query.set("control_mode", filters.controlMode);
  if (filters.lifecycle) query.set("lifecycle", filters.lifecycle);
  if (filters.status) query.set("status", filters.status);
  if (filters.owner === "me") query.set("assigned_admin_id", currentAdminId);
  if (filters.owner === "unassigned") query.set("unassigned_only", "true");
  if (filters.owner.startsWith("operator:")) {
    query.set("assigned_admin_id", filters.owner.slice("operator:".length));
  }
  return api<InboxConversationPage>(listPath("inbox", agentId, query, options));
}

export async function getInboxThread(
  agentId: string,
  conversationId: string,
): Promise<InboxThread> {
  return api<InboxThread>(`${inboxRoot(agentId)}/${encodeURIComponent(conversationId)}`);
}

export async function listInboxOperators(agentId: string): Promise<InboxOperator[]> {
  return api<InboxOperator[]>(`${inboxRoot(agentId)}/operators`);
}

export async function transitionInboxConversation(
  agentId: string,
  conversationId: string,
  transition: ControlTransition,
): Promise<void> {
  await api(`${inboxRoot(agentId)}/${encodeURIComponent(conversationId)}/control-transitions`, {
    method: "POST",
    body: JSON.stringify(transition),
  });
}

export async function sendInboxOperatorMessage(
  agentId: string,
  conversationId: string,
  content: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<void> {
  await api(`${inboxRoot(agentId)}/${encodeURIComponent(conversationId)}/operator-messages`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ content, expected_version: expectedVersion }),
  });
}

export async function assignInboxAutomationAgent(
  agentId: string,
  conversationId: string,
  assignment: AutomationAssignmentRequest,
  idempotencyKey: string,
  correlationId: string,
): Promise<AutomationAssignmentReceipt> {
  return api<AutomationAssignmentReceipt>(
    `${inboxRoot(agentId)}/${encodeURIComponent(conversationId)}/automation-assignments`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": idempotencyKey,
        "X-Correlation-ID": correlationId,
      },
      body: JSON.stringify(assignment),
    },
  );
}

export async function listInboxAutomationAssignments(
  agentId: string,
  conversationId: string,
  limit: number,
  offset: number,
): Promise<AutomationAssignmentHistoryPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return api<AutomationAssignmentHistoryPage>(
    `${inboxRoot(agentId)}/${encodeURIComponent(conversationId)}/automation-assignments?${query}`,
  );
}

export async function markInboxMessagesRead(
  agentId: string,
  conversationId: string,
  messageIds: string[],
): Promise<{ unread_count: number }> {
  return api(`${inboxRoot(agentId)}/${encodeURIComponent(conversationId)}/read`, {
    method: "POST",
    body: JSON.stringify({ message_ids: messageIds }),
  });
}

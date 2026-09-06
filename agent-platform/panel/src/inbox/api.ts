import { api } from "../api/client";
import type {
  ControlTransition,
  InboxConversationPage,
  InboxFilters,
  InboxOperator,
  InboxThread,
} from "./types";

function inboxRoot(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/inbox`;
}

export async function listInboxConversations(
  agentId: string,
  filters: InboxFilters,
  currentAdminId: string,
): Promise<InboxConversationPage> {
  const query = new URLSearchParams();
  if (filters.channel) query.set("channel", filters.channel);
  if (filters.controlMode) query.set("control_mode", filters.controlMode);
  if (filters.status) query.set("status", filters.status);
  if (filters.owner === "me") query.set("assigned_admin_id", currentAdminId);
  if (filters.owner === "unassigned") query.set("unassigned_only", "true");
  if (filters.owner.startsWith("operator:")) {
    query.set("assigned_admin_id", filters.owner.slice("operator:".length));
  }
  if (filters.updatedWithinHours) {
    const hours = Number(filters.updatedWithinHours);
    query.set("updated_after", new Date(Date.now() - hours * 60 * 60 * 1_000).toISOString());
  }
  query.set("limit", "100");
  return api<InboxConversationPage>(`${inboxRoot(agentId)}/?${query}`);
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

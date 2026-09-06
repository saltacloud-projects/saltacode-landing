import { api } from "../../api/client";
import type {
  CommercialOperator,
  FollowUpKind,
  FollowUpStatus,
  OpportunityCandidate,
  OpportunityDetail,
  OpportunityFilters,
  OpportunityMutation,
  OpportunityPage,
  OpportunityStage,
} from "./types";

function root(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/opportunities`;
}

function commandHeaders(idempotencyKey: string): Record<string, string> {
  return {
    "Idempotency-Key": idempotencyKey,
    "X-Correlation-ID": `panel-${idempotencyKey}`,
  };
}

export function newCommandKey(prefix: string): string {
  if (typeof crypto.randomUUID === "function") return `${prefix}-${crypto.randomUUID()}`;
  const values = crypto.getRandomValues(new Uint32Array(4));
  return `${prefix}-${Array.from(values, (value) => value.toString(16)).join("-")}`;
}

export async function listOpportunities(
  agentId: string,
  filters: OpportunityFilters,
  adminId: string,
): Promise<OpportunityPage> {
  const query = new URLSearchParams({ limit: "100" });
  if (filters.stage) query.set("stage", filters.stage);
  if (filters.search.trim()) query.set("search", filters.search.trim());
  if (filters.owner === "me") query.set("assigned_operator_id", adminId);
  if (filters.owner === "unassigned") query.set("unassigned_only", "true");
  if (filters.owner.startsWith("operator:")) {
    query.set("assigned_operator_id", filters.owner.slice("operator:".length));
  }
  return api<OpportunityPage>(`${root(agentId)}/?${query}`);
}

export function listOpportunityCandidates(agentId: string): Promise<OpportunityCandidate[]> {
  return api<OpportunityCandidate[]>(`${root(agentId)}/candidates`);
}

export function listOpportunityOperators(agentId: string): Promise<CommercialOperator[]> {
  return api<CommercialOperator[]>(`${root(agentId)}/operators`);
}

export function getOpportunity(agentId: string, opportunityId: string): Promise<OpportunityDetail> {
  return api<OpportunityDetail>(`${root(agentId)}/${encodeURIComponent(opportunityId)}`);
}

export function createOpportunity(
  agentId: string,
  input: {
    contact_id: string;
    source_conversation_id: string;
    title: string;
    summary?: string;
    assigned_operator_id?: string;
  },
): Promise<OpportunityMutation> {
  const key = newCommandKey("opportunity");
  return api<OpportunityMutation>(`${root(agentId)}/`, {
    method: "POST",
    headers: commandHeaders(key),
    body: JSON.stringify(input),
  });
}

export function transitionOpportunityStage(
  agentId: string,
  opportunityId: string,
  targetStage: OpportunityStage,
  expectedVersion: number,
  reason?: string,
): Promise<OpportunityMutation> {
  const key = newCommandKey("opportunity-stage");
  return api<OpportunityMutation>(
    `${root(agentId)}/${encodeURIComponent(opportunityId)}/stage-transitions`,
    {
      method: "POST",
      headers: commandHeaders(key),
      body: JSON.stringify({
        target_stage: targetStage,
        expected_version: expectedVersion,
        reason: reason || undefined,
      }),
    },
  );
}

export function reassignOpportunity(
  agentId: string,
  opportunityId: string,
  input: {
    assigned_agent_id: string;
    assigned_operator_id?: string;
    expected_version: number;
    reason?: string;
  },
): Promise<OpportunityMutation> {
  const key = newCommandKey("opportunity-owner");
  return api<OpportunityMutation>(
    `${root(agentId)}/${encodeURIComponent(opportunityId)}/reassignments`,
    {
      method: "POST",
      headers: commandHeaders(key),
      body: JSON.stringify(input),
    },
  );
}

export async function linkOpportunityConversation(
  agentId: string,
  opportunityId: string,
  conversationId: string,
): Promise<void> {
  const key = newCommandKey("opportunity-conversation");
  await api(`${root(agentId)}/${encodeURIComponent(opportunityId)}/conversation-links`, {
    method: "POST",
    headers: commandHeaders(key),
    body: JSON.stringify({ conversation_id: conversationId }),
  });
}

export async function createFollowUp(
  agentId: string,
  opportunityId: string,
  input: { contact_point_id: string; kind: FollowUpKind; due_at: string; note?: string },
): Promise<void> {
  const key = newCommandKey("follow-up");
  await api(`${root(agentId)}/${encodeURIComponent(opportunityId)}/follow-ups`, {
    method: "POST",
    headers: commandHeaders(key),
    body: JSON.stringify(input),
  });
}

export async function transitionFollowUp(
  agentId: string,
  opportunityId: string,
  taskId: string,
  targetStatus: FollowUpStatus,
  expectedVersion: number,
): Promise<void> {
  await api(
    `${root(agentId)}/${encodeURIComponent(opportunityId)}/follow-ups/` +
      `${encodeURIComponent(taskId)}/transitions`,
    {
      method: "POST",
      body: JSON.stringify({ target_status: targetStatus, expected_version: expectedVersion }),
    },
  );
}

export async function createQuoteRequest(
  agentId: string,
  opportunityId: string,
  input: {
    requirements: Record<string, unknown>;
    status: "unavailable" | "review_required";
    failure_code: string;
  },
): Promise<void> {
  const key = newCommandKey("quote-request");
  await api(`${root(agentId)}/${encodeURIComponent(opportunityId)}/quote-requests`, {
    method: "POST",
    headers: commandHeaders(key),
    body: JSON.stringify(input),
  });
}

export async function createAuthoritativeQuoteVersion(
  agentId: string,
  opportunityId: string,
  quoteRequestId: string,
  input: {
    expected_version: number;
    authority_name: string;
    authority_version: string;
    external_reference: string;
    content_hash: string;
    issued_at: string;
  },
): Promise<void> {
  const key = newCommandKey("quote-version");
  await api(
    `${root(agentId)}/${encodeURIComponent(opportunityId)}/quote-requests/` +
      `${encodeURIComponent(quoteRequestId)}/authoritative-versions`,
    {
      method: "POST",
      headers: commandHeaders(key),
      body: JSON.stringify(input),
    },
  );
}

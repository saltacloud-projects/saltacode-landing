import { api } from "../../api/client";
import type { HandoffRoute, HandoffTrigger } from "./types";

function root(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/handoff-routes`;
}

function commandKey(prefix: string): string {
  if (typeof crypto.randomUUID === "function") return `${prefix}-${crypto.randomUUID()}`;
  const values = crypto.getRandomValues(new Uint32Array(4));
  return `${prefix}-${Array.from(values, (value) => value.toString(16)).join("-")}`;
}

export function listHandoffRoutes(agentId: string): Promise<HandoffRoute[]> {
  return api<HandoffRoute[]>(`${root(agentId)}/`);
}

export function createHandoffRoute(
  agentId: string,
  input: { targetAgentId: string; trigger: HandoffTrigger; isActive: boolean },
): Promise<HandoffRoute> {
  return api<HandoffRoute>(`${root(agentId)}/`, {
    method: "POST",
    body: JSON.stringify({
      target_agent_id: input.targetAgentId,
      trigger: input.trigger,
      is_active: input.isActive,
      idempotency_key: commandKey("handoff-create"),
    }),
  });
}

export function updateHandoffRoute(
  agentId: string,
  routeId: string,
  input: { targetAgentId?: string; isActive?: boolean; expectedVersion: number },
): Promise<HandoffRoute> {
  return api<HandoffRoute>(`${root(agentId)}/${encodeURIComponent(routeId)}`, {
    method: "PATCH",
    body: JSON.stringify({
      target_agent_id: input.targetAgentId,
      is_active: input.isActive,
      expected_version: input.expectedVersion,
      idempotency_key: commandKey("handoff-update"),
    }),
  });
}

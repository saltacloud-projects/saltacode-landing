import { api } from "../../api/client";
import type { CommercialAutomationPolicy, CommercialAutomationPolicyUpdate } from "./types";

function policyPath(agentId: string): string {
  return `/agents/${agentId}/opportunities/automation-policy`;
}

export function getCommercialAutomationPolicy(
  agentId: string,
): Promise<CommercialAutomationPolicy> {
  return api<CommercialAutomationPolicy>(policyPath(agentId));
}

export function updateCommercialAutomationPolicy(
  agentId: string,
  input: CommercialAutomationPolicyUpdate,
): Promise<CommercialAutomationPolicy> {
  return api<CommercialAutomationPolicy>(policyPath(agentId), {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

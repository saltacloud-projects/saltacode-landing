import { api } from "../../api/client";
import type {
  CommandIntent,
  InboundJobAction,
  InboundJobDetail,
  InboundJobFilters,
  InboundJobMutation,
  InboundJobPage,
  InboundJobTimeline,
} from "./types";

function root(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/inbound-jobs`;
}

export function createCommandIntent(action: InboundJobAction): CommandIntent {
  const suffix =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint32Array(4)), (value) => value.toString(16)).join(
          "-",
        );
  const idempotencyKey = `inbound-${action}-${suffix}`;
  return { idempotencyKey, correlationId: `panel-${idempotencyKey}` };
}

export function listInboundJobs(
  agentId: string,
  filters: InboundJobFilters,
): Promise<InboundJobPage> {
  const query = new URLSearchParams({ limit: "100" });
  if (filters.status) query.set("status", filters.status);
  return api<InboundJobPage>(`${root(agentId)}/?${query}`);
}

export function getInboundJob(agentId: string, jobId: string): Promise<InboundJobDetail> {
  return api<InboundJobDetail>(`${root(agentId)}/${encodeURIComponent(jobId)}`);
}

export function getInboundJobTimeline(agentId: string, jobId: string): Promise<InboundJobTimeline> {
  return api<InboundJobTimeline>(`${root(agentId)}/${encodeURIComponent(jobId)}/timeline`);
}

export function commandInboundJob(
  agentId: string,
  jobId: string,
  action: InboundJobAction,
  expectedVersion: number,
  intent: CommandIntent,
): Promise<InboundJobMutation> {
  return api<InboundJobMutation>(`${root(agentId)}/${encodeURIComponent(jobId)}/${action}`, {
    method: "POST",
    headers: {
      "Idempotency-Key": intent.idempotencyKey,
      "X-Correlation-ID": intent.correlationId,
    },
    body: JSON.stringify({ expected_version: expectedVersion }),
  });
}

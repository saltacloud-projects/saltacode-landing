import { api } from "../../api/client";
import type {
  FollowUpCommandResult,
  FollowUpDetail,
  FollowUpEventPage,
  FollowUpFilters,
  FollowUpQueuePage,
} from "./types";

function root(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/follow-ups`;
}

function commandKey(prefix: string): string {
  if (typeof crypto.randomUUID === "function") return `${prefix}-${crypto.randomUUID()}`;
  const values = crypto.getRandomValues(new Uint32Array(4));
  return `${prefix}-${Array.from(values, (value) => value.toString(16)).join("-")}`;
}

function command(
  agentId: string,
  taskId: string,
  resource: "cancel" | "requeue" | "review-resolution",
  body: Record<string, unknown>,
): Promise<FollowUpCommandResult> {
  const key = commandKey(`follow-up-${resource}`);
  return api<FollowUpCommandResult>(`${root(agentId)}/${encodeURIComponent(taskId)}/${resource}`, {
    method: "POST",
    headers: {
      "Idempotency-Key": key,
      "X-Correlation-ID": `panel-${key}`,
    },
    body: JSON.stringify(body),
  });
}

export function listFollowUps(
  agentId: string,
  filters: FollowUpFilters,
): Promise<FollowUpQueuePage> {
  const query = new URLSearchParams({ limit: "100" });
  if (filters.status) query.set("status", filters.status);
  if (filters.kind) query.set("kind", filters.kind);
  return api<FollowUpQueuePage>(`${root(agentId)}/?${query}`);
}

export function getFollowUp(agentId: string, taskId: string): Promise<FollowUpDetail> {
  return api<FollowUpDetail>(`${root(agentId)}/${encodeURIComponent(taskId)}`);
}

export function listFollowUpEvents(agentId: string, taskId: string): Promise<FollowUpEventPage> {
  return api<FollowUpEventPage>(`${root(agentId)}/${encodeURIComponent(taskId)}/events?limit=100`);
}

export function cancelFollowUp(
  agentId: string,
  taskId: string,
  expectedVersion: number,
): Promise<FollowUpCommandResult> {
  return command(agentId, taskId, "cancel", { expected_version: expectedVersion });
}

export function requeueFollowUp(
  agentId: string,
  taskId: string,
  expectedVersion: number,
): Promise<FollowUpCommandResult> {
  return command(agentId, taskId, "requeue", { expected_version: expectedVersion });
}

export function resolveFollowUpReview(
  agentId: string,
  taskId: string,
  expectedVersion: number,
  resolution: "requeue" | "cancel",
): Promise<FollowUpCommandResult> {
  return command(agentId, taskId, "review-resolution", {
    expected_version: expectedVersion,
    resolution,
  });
}

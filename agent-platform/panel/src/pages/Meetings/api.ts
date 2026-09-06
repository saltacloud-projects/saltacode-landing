import { api } from "../../api/client";
import type {
  MeetingDetail,
  MeetingFilters,
  MeetingMutation,
  MeetingPage,
  SlotProposalInput,
} from "./types";

function root(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/meetings`;
}

function commandHeaders(key: string): Record<string, string> {
  return {
    "Idempotency-Key": key,
    "X-Correlation-ID": `panel-${key}`,
  };
}

function commandKey(prefix: string): string {
  if (typeof crypto.randomUUID === "function") return `${prefix}-${crypto.randomUUID()}`;
  const values = crypto.getRandomValues(new Uint32Array(4));
  return `${prefix}-${Array.from(values, (value) => value.toString(16)).join("-")}`;
}

function command(
  agentId: string,
  path: string,
  prefix: string,
  body: Record<string, unknown>,
): Promise<MeetingMutation> {
  const key = commandKey(prefix);
  return api<MeetingMutation>(`${root(agentId)}${path}`, {
    method: "POST",
    headers: commandHeaders(key),
    body: JSON.stringify(body),
  });
}

export function listMeetings(agentId: string, filters: MeetingFilters): Promise<MeetingPage> {
  const query = new URLSearchParams({ limit: "100" });
  if (filters.status) query.set("status", filters.status);
  if (filters.opportunityId.trim()) query.set("opportunity_id", filters.opportunityId.trim());
  return api<MeetingPage>(`${root(agentId)}/?${query}`);
}

export function getMeeting(agentId: string, meetingId: string): Promise<MeetingDetail> {
  return api<MeetingDetail>(`${root(agentId)}/${encodeURIComponent(meetingId)}`);
}

export function createMeeting(
  agentId: string,
  input: { opportunity_id: string; conversation_id?: string },
): Promise<MeetingMutation> {
  const key = commandKey("meeting-create");
  return api<MeetingMutation>(`${root(agentId)}/`, {
    method: "POST",
    headers: commandHeaders(key),
    body: JSON.stringify(input),
  });
}

export function proposeSlots(
  agentId: string,
  meetingId: string,
  expectedVersion: number,
  slots: SlotProposalInput[],
  reason?: string,
): Promise<MeetingMutation> {
  return command(agentId, `/${encodeURIComponent(meetingId)}/slot-proposals`, "meeting-slots", {
    expected_version: expectedVersion,
    slots,
    reason: reason || undefined,
  });
}

export function markAwaitingResponse(
  agentId: string,
  meetingId: string,
  expectedVersion: number,
  reason?: string,
): Promise<MeetingMutation> {
  return command(
    agentId,
    `/${encodeURIComponent(meetingId)}/awaiting-response`,
    "meeting-awaiting",
    { expected_version: expectedVersion, reason: reason || undefined },
  );
}

export function selectSlot(
  agentId: string,
  meetingId: string,
  expectedVersion: number,
  slotId: string,
  reason?: string,
): Promise<MeetingMutation> {
  return command(agentId, `/${encodeURIComponent(meetingId)}/slot-selections`, "meeting-select", {
    expected_version: expectedVersion,
    slot_id: slotId,
    reason: reason || undefined,
  });
}

export function scheduleManually(
  agentId: string,
  meetingId: string,
  input: {
    expected_version: number;
    expected_opportunity_version: number;
    slot_id: string;
    evidence_type: string;
    evidence_reference: string;
    reason?: string;
  },
): Promise<MeetingMutation> {
  return command(
    agentId,
    `/${encodeURIComponent(meetingId)}/manual-schedules`,
    "meeting-manual",
    input,
  );
}

function transition(
  agentId: string,
  meetingId: string,
  resource: "reschedule-requests" | "cancellations" | "reviews",
  expectedVersion: number,
  reason?: string,
): Promise<MeetingMutation> {
  return command(agentId, `/${encodeURIComponent(meetingId)}/${resource}`, `meeting-${resource}`, {
    expected_version: expectedVersion,
    reason: reason || undefined,
  });
}

export function requestReschedule(
  agentId: string,
  meetingId: string,
  expectedVersion: number,
  reason?: string,
): Promise<MeetingMutation> {
  return transition(agentId, meetingId, "reschedule-requests", expectedVersion, reason);
}

export function cancelMeeting(
  agentId: string,
  meetingId: string,
  expectedVersion: number,
  reason?: string,
): Promise<MeetingMutation> {
  return transition(agentId, meetingId, "cancellations", expectedVersion, reason);
}

export function requireReview(
  agentId: string,
  meetingId: string,
  expectedVersion: number,
  reason?: string,
): Promise<MeetingMutation> {
  return transition(agentId, meetingId, "reviews", expectedVersion, reason);
}

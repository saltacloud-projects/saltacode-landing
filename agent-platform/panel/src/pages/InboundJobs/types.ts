export type InboundJobStatus =
  | "queued"
  | "processing"
  | "completed"
  | "routed_to_human"
  | "ignored"
  | "review_required"
  | "cancelled";

export type InboundJobAction = "requeue" | "cancel" | "acknowledge";

export interface InboundJobSummary {
  id: string;
  channel: string;
  status: InboundJobStatus;
  phase: string;
  state_version: number;
  attempts: number;
  safe_code: string | null;
  created_at: string;
  updated_at: string;
  terminal_at: string | null;
}

export interface InboundJobDetail extends InboundJobSummary {
  conversation_control_version: number | null;
  conversation_automation_version: number | null;
  legacy_payload_quarantined: boolean;
}

export interface InboundJobEvent {
  id: string;
  event_type: string;
  from_status: InboundJobStatus | "failed" | null;
  to_status: InboundJobStatus;
  state_version: number;
  phase: string;
  actor_type: "system" | "worker" | "operator";
  has_actor_admin: boolean;
  safe_code: string | null;
  created_at: string;
}

export interface InboundJobPage {
  items: InboundJobSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface InboundJobTimeline {
  items: InboundJobEvent[];
}

export interface InboundJobMutation {
  id: string;
  status: InboundJobStatus;
  phase: string;
  state_version: number;
  safe_code: string | null;
}

export interface InboundJobFilters {
  status: InboundJobStatus | "";
}

export interface CommandIntent {
  idempotencyKey: string;
  correlationId: string;
}

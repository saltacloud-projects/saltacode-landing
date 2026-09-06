export type FollowUpKind = "commercial_follow_up" | "meeting_coordination" | "proposal_reminder";

export type FollowUpStatus =
  | "scheduled"
  | "dispatch_queued"
  | "in_progress"
  | "completed"
  | "cancelled"
  | "review_required";

export interface FollowUpQueueItem {
  id: string;
  opportunity_id: string;
  assigned_agent_id: string;
  assigned_operator_id: string | null;
  kind: FollowUpKind;
  status: FollowUpStatus;
  state_version: number;
  due_at: string;
  available_at: string;
  attempts: number;
  max_attempts: number;
  is_leased: boolean;
  outbound_status: string | null;
  safe_code: string | null;
  review_required_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FollowUpDetail extends FollowUpQueueItem {
  conversation_id: string | null;
  has_retained_source_conversation: boolean;
  quote_version_id: string | null;
  scheduled_control_version: number | null;
  scheduled_automation_version: number | null;
  scheduled_policy_version: number | null;
  executed_policy_version: number | null;
  has_consent_evidence: boolean;
  has_executed_consent_evidence: boolean;
  has_chat_message_evidence: boolean;
  has_outbound_message_evidence: boolean;
  completed_at: string | null;
  cancelled_at: string | null;
}

export interface FollowUpEvent {
  id: string;
  event_type: string;
  from_status: FollowUpStatus | null;
  to_status: FollowUpStatus;
  state_version: number;
  actor_type: string;
  has_actor_agent: boolean;
  has_actor_admin: boolean;
  has_actor_worker: boolean;
  routing_agent_id: string | null;
  automation_agent_id: string | null;
  target_channel: string | null;
  control_version: number | null;
  automation_version: number | null;
  scheduled_policy_version: number | null;
  executed_policy_version: number | null;
  has_consent_evidence: boolean;
  has_executed_consent_evidence: boolean;
  has_causal_consent_evidence: boolean;
  has_chat_message_evidence: boolean;
  has_outbound_message_evidence: boolean;
  safe_code: string | null;
  created_at: string;
}

export interface FollowUpQueuePage {
  items: FollowUpQueueItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface FollowUpEventPage {
  items: FollowUpEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface FollowUpCommandResult {
  id: string;
  status: FollowUpStatus;
  state_version: number;
}

export interface FollowUpFilters {
  status: FollowUpStatus | "";
  kind: FollowUpKind | "";
}

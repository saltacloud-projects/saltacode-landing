export type MeetingStatus =
  | "requested"
  | "slots_proposed"
  | "awaiting_response"
  | "slot_selected"
  | "calendar_pending"
  | "scheduled"
  | "reschedule_requested"
  | "cancelled"
  | "review_required";

export interface MeetingSlot {
  id: string;
  proposal_version: number;
  position: number;
  starts_at: string;
  ends_at: string;
  timezone: string;
  created_at: string;
}

export interface MeetingEvent {
  id: string;
  event_type: string;
  from_status: MeetingStatus | null;
  to_status: MeetingStatus;
  state_version: number;
  proposal_version: number;
  opportunity_control_version: number;
  slot_id: string | null;
  actor_type: "agent" | "operator";
  actor_agent_id: string | null;
  actor_admin_id: string | null;
  assigned_agent_id: string;
  assigned_operator_id: string | null;
  conversation_id: string | null;
  routing_agent_id: string | null;
  automation_agent_id: string | null;
  conversation_control_version: number | null;
  conversation_automation_version: number | null;
  source_channel: string | null;
  evidence_type: string | null;
  evidence_recorded: boolean;
  safe_code: string | null;
  created_at: string;
}

export interface MeetingSummary {
  id: string;
  opportunity_id: string;
  conversation_id: string | null;
  status: MeetingStatus;
  state_version: number;
  proposal_version: number;
  selected_slot_id: string | null;
  selected_slot: MeetingSlot | null;
  created_at: string;
  updated_at: string;
}

export interface MeetingDetail extends MeetingSummary {
  slots: MeetingSlot[];
  events: MeetingEvent[];
}

export interface MeetingPage {
  items: MeetingSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface MeetingMutation {
  id: string;
  opportunity_id: string;
  status: MeetingStatus;
  state_version: number;
  proposal_version: number;
  selected_slot_id: string | null;
  opportunity_stage: string;
  opportunity_control_version: number;
  created: boolean;
}

export interface MeetingFilters {
  status: Exclude<MeetingStatus, "calendar_pending"> | "";
  opportunityId: string;
}

export interface SlotProposalInput {
  starts_at: string;
  ends_at: string;
  timezone: string;
}

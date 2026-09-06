export type OpportunityStage =
  | "new"
  | "qualified"
  | "proposal_requested"
  | "proposal_preparing"
  | "proposal_sent"
  | "negotiation"
  | "meeting_scheduled"
  | "won"
  | "lost"
  | "paused";

export type FollowUpKind = "commercial_follow_up" | "meeting_coordination" | "proposal_reminder";

export type FollowUpStatus =
  | "scheduled"
  | "in_progress"
  | "completed"
  | "cancelled"
  | "review_required";

export type QuoteRequestStatus = "unavailable" | "review_required" | "issued" | "cancelled";

export interface CommercialOperator {
  id: string;
  name: string;
  email: string;
}

export interface CommercialAgent {
  id: string;
  name: string;
}

export interface ContactPoint {
  id: string;
  kind: "email" | "phone";
  masked_value: string;
  verification_status: string;
  commercial_follow_up_allowed: boolean;
  quote_delivery_allowed: boolean;
}

export interface CommercialContact {
  id: string;
  principal_id: string;
  display_name: string | null;
  company_name: string | null;
  job_title: string | null;
  status: string;
  contact_points: ContactPoint[];
}

export interface OpportunitySummary {
  id: string;
  title: string;
  summary: string | null;
  stage: OpportunityStage;
  control_version: number;
  contact: CommercialContact;
  assigned_agent: CommercialAgent;
  assigned_operator: CommercialOperator | null;
  linked_conversation_count: number;
  pending_follow_up_count: number;
  latest_quote_status: QuoteRequestStatus | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface OpportunityPage {
  items: OpportunitySummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface OpportunityCandidate {
  contact: CommercialContact;
  conversation_id: string;
  channel: string;
  route_key: string;
  conversation_status: string;
  conversation_updated_at: string;
}

export interface ConversationCandidate {
  id: string;
  agent_id: string;
  channel: string;
  route_key: string;
  status: string;
  updated_at: string;
}

export interface OpportunityConversation {
  id: string;
  conversation_id: string | null;
  channel: string | null;
  route_key: string | null;
  status: string | null;
  linked_at: string;
}

export interface OpportunityStageEvent {
  id: string;
  event_type: string;
  from_stage: OpportunityStage | null;
  to_stage: OpportunityStage;
  control_version: number;
  reason: string | null;
  created_at: string;
}

export interface OpportunityOwnershipEvent {
  id: string;
  event_type: string;
  from_agent_id: string | null;
  to_agent_id: string;
  from_operator_id: string | null;
  to_operator_id: string | null;
  control_version: number;
  reason: string | null;
  created_at: string;
}

export interface FollowUpTask {
  id: string;
  contact_point_id: string | null;
  consent_record_id: string;
  assigned_agent_id: string;
  assigned_operator_id: string | null;
  kind: FollowUpKind;
  status: FollowUpStatus;
  state_version: number;
  due_at: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface QuoteVersion {
  id: string;
  version: number;
  status: "issued";
  authority_name: string;
  authority_version: string;
  external_reference: string;
  content_hash: string;
  issued_at: string;
  recorded_at: string;
}

export interface QuoteRequest {
  id: string;
  status: QuoteRequestStatus;
  state_version: number;
  requirements: Record<string, unknown>;
  failure_code: string | null;
  created_at: string;
  updated_at: string;
  versions: QuoteVersion[];
}

export interface OpportunityDetail extends OpportunitySummary {
  available_conversations: ConversationCandidate[];
  conversations: OpportunityConversation[];
  stage_events: OpportunityStageEvent[];
  ownership_events: OpportunityOwnershipEvent[];
  follow_ups: FollowUpTask[];
  quote_requests: QuoteRequest[];
}

export interface OpportunityFilters {
  stage: string;
  owner: string;
  search: string;
}

export interface OpportunityMutation {
  id: string;
  stage: OpportunityStage;
  control_version: number;
  assigned_agent_id: string;
  assigned_operator_id: string | null;
  created: boolean;
}

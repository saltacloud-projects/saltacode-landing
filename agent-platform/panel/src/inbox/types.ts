export type ConversationControlMode = "automated" | "paused" | "human" | "closed";

export interface InboxOperator {
  id: string;
  name: string;
  email: string;
}

export interface InboxConversation {
  id: string;
  principal_id: string;
  display_name: string | null;
  channel: string;
  route_key: string;
  status: string;
  control_mode: ConversationControlMode;
  control_version: number;
  assigned_operator: InboxOperator | null;
  control_changed_at: string;
  control_reason: string | null;
  message_count: number;
  last_activity_at: string;
}

export interface InboxConversationPage {
  items: InboxConversation[];
  total: number;
  limit: number;
  offset: number;
}

export interface InboxMessage {
  id: string;
  role: string;
  content: string;
  status: string;
  tool_names: string[];
  origin: string | null;
  actor_admin_id: string | null;
  created_at: string;
}

export interface ConversationControlEvent {
  id: string;
  event_type: string;
  from_mode: ConversationControlMode;
  to_mode: ConversationControlMode;
  from_assigned_admin_id: string | null;
  to_assigned_admin_id: string | null;
  control_version: number;
  reason: string | null;
  created_at: string;
}

export interface InboxThread {
  conversation: InboxConversation;
  messages: InboxMessage[];
  control_events: ConversationControlEvent[];
}

export interface InboxFilters {
  channel: string;
  controlMode: string;
  status: string;
  owner: string;
  updatedWithinHours: string;
}

export interface ControlTransition {
  target_mode: ConversationControlMode;
  expected_version: number;
  assigned_admin_id?: string;
  reason?: string;
}

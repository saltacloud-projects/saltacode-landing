export type DeliveryStatus =
  | "queued"
  | "dispatching"
  | "accepted"
  | "delivered"
  | "read"
  | "failed"
  | "delivery_unknown"
  | "cancelled";

export interface DeliverySummary {
  id: string;
  conversation_id: string;
  channel: string;
  status: DeliveryStatus;
  kind: string;
  sender_type: string;
  sequence: number;
  correlation_id: string;
  provider_reference: string | null;
  attempt_count: number;
  latest_safe_code: string | null;
  is_fifo_blocking: boolean;
  blocked_message_count: number;
  created_at: string;
  updated_at: string;
}

export interface DeliveryAttempt {
  id: string;
  attempt_number: number;
  control_version: number;
  created_at: string;
}

export interface DeliveryEvent {
  id: string;
  attempt_id: string | null;
  event_type: string;
  from_status: string | null;
  to_status: string;
  actor_type: string;
  safe_code: string | null;
  created_at: string;
}

export interface DeliveryDetail extends DeliverySummary {
  channel_route_id: string;
  chat_message_id: string | null;
  control_version: number;
  accepted_at: string | null;
  delivered_at: string | null;
  attempts: DeliveryAttempt[];
  events: DeliveryEvent[];
}

export interface DeliveryPage {
  items: DeliverySummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface DeliveryFilters {
  channel: string;
  status: string;
  conversationId: string;
}

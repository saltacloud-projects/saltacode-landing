import type { ChannelKind } from "../../runtime/types";

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
  channel: ChannelKind;
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
  resolution_version: number;
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
  resolution: DeliveryResolution | null;
}

export type DeliveryResolutionAction = "confirm_delivered" | "confirm_not_delivered";
export type DeliveryEvidenceSource = "provider_api" | "provider_console";
export type DeliveryNotDeliveredReason =
  | "provider_confirmed_not_delivered"
  | "provider_record_not_found"
  | "operator_verified_not_delivered";

export interface DeliveryResolution {
  resolution_version: number;
  action: DeliveryResolutionAction;
  provider_reference: string | null;
  evidence_source: DeliveryEvidenceSource | null;
  reason_code: DeliveryNotDeliveredReason | null;
  has_actor_admin: boolean;
  created_at: string;
}

export type DeliveryResolutionInput =
  | {
      action: "confirm_delivered";
      provider_message_id: string;
      evidence_source: DeliveryEvidenceSource;
    }
  | {
      action: "confirm_not_delivered";
      reason_code: DeliveryNotDeliveredReason;
    };

export interface DeliveryResolutionMutation {
  id: string;
  status: "delivered" | "cancelled";
  resolution_version: number;
  action: DeliveryResolutionAction;
  applied: boolean;
}

export interface DeliveryResolutionIntent {
  idempotencyKey: string;
  correlationId: string;
}

export interface DeliveryPage {
  items: DeliverySummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface DeliveryFilters {
  channel: "" | ChannelKind;
  status: string;
  conversationId: string;
}

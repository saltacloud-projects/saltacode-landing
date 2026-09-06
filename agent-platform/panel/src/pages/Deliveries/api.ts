import { api } from "../../api/client";
import type { DeliveryDetail, DeliveryFilters, DeliveryPage } from "./types";

function root(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/deliveries`;
}

export function listDeliveries(agentId: string, filters: DeliveryFilters): Promise<DeliveryPage> {
  const query = new URLSearchParams({ limit: "100" });
  if (filters.channel) query.set("channel", filters.channel);
  if (filters.status) query.set("status", filters.status);
  if (filters.conversationId.trim()) {
    query.set("conversation_id", filters.conversationId.trim());
  }
  return api<DeliveryPage>(`${root(agentId)}/?${query}`);
}

export function getDelivery(agentId: string, deliveryId: string): Promise<DeliveryDetail> {
  return api<DeliveryDetail>(`${root(agentId)}/${encodeURIComponent(deliveryId)}`);
}

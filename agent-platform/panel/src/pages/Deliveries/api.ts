import { api } from "../../api/client";
import type {
  DeliveryDetail,
  DeliveryFilters,
  DeliveryPage,
  DeliveryResolutionInput,
  DeliveryResolutionIntent,
  DeliveryResolutionMutation,
} from "./types";

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

export function createResolutionIntent(): DeliveryResolutionIntent {
  const suffix =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint32Array(4)), (value) => value.toString(16)).join(
          "-",
        );
  const idempotencyKey = `delivery-resolution-${suffix}`;
  return { idempotencyKey, correlationId: `panel-${idempotencyKey}` };
}

export function resolveDelivery(
  agentId: string,
  deliveryId: string,
  expectedResolutionVersion: number,
  input: DeliveryResolutionInput,
  intent: DeliveryResolutionIntent,
): Promise<DeliveryResolutionMutation> {
  return api<DeliveryResolutionMutation>(
    `${root(agentId)}/${encodeURIComponent(deliveryId)}/resolve`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": intent.idempotencyKey,
        "X-Correlation-ID": intent.correlationId,
      },
      body: JSON.stringify({
        ...input,
        expected_resolution_version: expectedResolutionVersion,
      }),
    },
  );
}

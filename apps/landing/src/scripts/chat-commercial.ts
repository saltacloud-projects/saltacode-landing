import type { ChatEvent } from "./chat-stream";

export type CommercialDeliveryChannel = "email" | "whatsapp";

export interface CommercialContactPrompt {
  requestId: string;
  title: string;
  summary: string;
  preferredDeliveryChannel: CommercialDeliveryChannel;
}

export interface CommercialContactPayload {
  client_request_id: string;
  locale: "en" | "es-AR";
  title: string;
  summary: string;
  contact_kind: "email" | "phone";
  contact_value: string;
  preferred_delivery_channel: CommercialDeliveryChannel;
  quote_delivery_consent: true;
  commercial_follow_up_consent: boolean;
  privacy_version: string;
}

export interface CommercialEventCorrelation {
  accepted: boolean;
  attemptedClientRequestIds: readonly string[];
  promptCursor: number;
  promptRequestId: string;
}

export class CommercialContactApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`commercial_contact_${status}`);
    this.status = status;
  }
}

const REQUEST_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const EMAIL_PATTERN = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;
const PHONE_PATTERN = /^\+[1-9][0-9]{7,14}$/;

function sanitizedText(value: unknown, maxLength: number): string {
  if (typeof value !== "string") return "";
  return [...value.normalize("NFKC")]
    .map((character) => /\p{C}/u.test(character) ? " " : character)
    .join("")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

export function parseCommercialContactPrompt(event: ChatEvent): CommercialContactPrompt | null {
  if (event.event_type !== "commercial.contact.requested") return null;
  const payload = event.payload ?? {};
  const requestId = typeof payload.request_id === "string" ? payload.request_id : "";
  const title = sanitizedText(payload.title, 120);
  const summary = sanitizedText(payload.summary, 600);
  const preferredDeliveryChannel = payload.preferred_delivery_channel;
  if (
    !REQUEST_ID_PATTERN.test(requestId) ||
    !title ||
    !summary ||
    (preferredDeliveryChannel !== "email" && preferredDeliveryChannel !== "whatsapp")
  ) return null;
  return { requestId, title, summary, preferredDeliveryChannel };
}

export function applyCommercialEventCorrelation(
  current: CommercialEventCorrelation | undefined,
  event: ChatEvent,
): CommercialEventCorrelation | undefined {
  const prompt = parseCommercialContactPrompt(event);
  if (prompt) {
    if (prompt.requestId === current?.promptRequestId) return current;
    return {
      accepted: false,
      attemptedClientRequestIds: [],
      promptCursor: event.cursor ?? 0,
      promptRequestId: prompt.requestId,
    };
  }
  if (!current || current.accepted || event.event_type !== "commercial.opportunity.created") return current;
  const payload = event.payload ?? {};
  const clientRequestId = typeof payload.client_request_id === "string" ? payload.client_request_id : "";
  if (payload.status !== "accepted" || !UUID_PATTERN.test(clientRequestId)) return current;
  const matchesAttempt = current.attemptedClientRequestIds.includes(clientRequestId);
  const matchesReplayOrder = current.attemptedClientRequestIds.length === 0 &&
    current.promptCursor > 0 &&
    typeof event.cursor === "number" &&
    event.cursor > current.promptCursor;
  return matchesAttempt || matchesReplayOrder ? { ...current, accepted: true } : current;
}

export function isValidCommercialContact(channel: CommercialDeliveryChannel, value: string): boolean {
  return channel === "email"
    ? EMAIL_PATTERN.test(value) && !value.includes("..")
    : PHONE_PATTERN.test(value);
}

export function commercialContactMarkup(): string {
  return [
    '<section class="chat-commercial" aria-labelledby="chat-commercial-title">',
    '<h2 id="chat-commercial-title" tabindex="-1"></h2><p data-commercial-summary></p>',
    '<form data-commercial-form novalidate><fieldset><legend>¿Dónde querés recibir el presupuesto?</legend><div class="chat-commercial-options">',
    '<label><input type="radio" name="delivery-channel" value="email"> Email</label>',
    '<label><input type="radio" name="delivery-channel" value="whatsapp"> WhatsApp</label>',
    '</div></fieldset><label class="chat-commercial-contact"><span data-commercial-contact-label></span>',
    '<input data-commercial-contact required maxlength="320" aria-describedby="chat-commercial-hint chat-commercial-status"></label>',
    '<small id="chat-commercial-hint">Para WhatsApp usá formato internacional, por ejemplo +549...</small>',
    '<label class="chat-commercial-consent"><input data-commercial-quote-consent type="checkbox" required> Autorizo a SaltaCode a usar este dato para preparar y enviar el presupuesto solicitado.</label>',
    '<label class="chat-commercial-consent"><input data-commercial-follow-up type="checkbox"> También quiero recibir seguimiento comercial sobre esta solicitud.</label>',
    '<p>Consultá cómo usamos tus datos en la <a href="/legal/privacidad/" target="_blank" rel="noopener noreferrer">Política de privacidad</a>.</p>',
    '<button class="chat-commercial-submit" type="submit">Compartir datos</button>',
    '<p id="chat-commercial-status" class="chat-commercial-status" role="status" aria-live="polite" aria-atomic="true"></p>',
    '</form></section>',
  ].join("");
}

export async function postCommercialContact(
  payload: CommercialContactPayload,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const response = await fetcher("/api/v2/chat/commercial-contact", {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new CommercialContactApiError(response.status);
  const body = await response.json() as { opportunity_id?: unknown; status?: unknown };
  if (body.status !== "accepted" || typeof body.opportunity_id !== "string" || !UUID_PATTERN.test(body.opportunity_id)) {
    throw new CommercialContactApiError(502);
  }
}

import assert from "node:assert/strict";
import test from "node:test";

import {
  CommercialContactApiError,
  applyCommercialEventCorrelation,
  commercialContactMarkup,
  isValidCommercialContact,
  parseCommercialContactPrompt,
  postCommercialContact,
  type CommercialContactPayload,
} from "../src/scripts/chat-commercial.ts";

const clientRequestId = "10000000-1000-4000-8000-100000000001";
const opportunityId = "20000000-2000-4000-8000-200000000002";

function commercialPayload(): CommercialContactPayload {
  return {
    client_request_id: clientRequestId,
    locale: "es-AR",
    title: "Software para ventas",
    summary: "Necesita una propuesta para digitalizar su proceso comercial.",
    contact_kind: "email",
    contact_value: "contacto@example.com",
    preferred_delivery_channel: "email",
    quote_delivery_consent: true,
    commercial_follow_up_consent: false,
    privacy_version: "privacy-v1",
  };
}

test("accepts only a bounded public commercial contact prompt", () => {
  const prompt = parseCommercialContactPrompt({
    schema_version: "2",
    event_type: "commercial.contact.requested",
    payload: {
      request_id: "tool-request:42",
      title: "  Presupuesto\u0000 web  ",
      summary: "  Sitio\n institucional  ",
      preferred_delivery_channel: "whatsapp",
    },
  });

  assert.deepEqual(prompt, {
    requestId: "tool-request:42",
    title: "Presupuesto web",
    summary: "Sitio institucional",
    preferredDeliveryChannel: "whatsapp",
  });
  assert.equal(parseCommercialContactPrompt({
    schema_version: "2",
    event_type: "commercial.contact.requested",
    payload: { request_id: "invalid id", title: "Hola", summary: "Mundo", preferred_delivery_channel: "sms" },
  }), null);
});

test("commercial form exposes native fields and explicit separate consents", () => {
  const markup = commercialContactMarkup();

  assert.match(markup, /id="chat-commercial-title" tabindex="-1"/);
  assert.match(markup, /<form data-commercial-form novalidate>/);
  assert.match(markup, /type="radio" name="delivery-channel" value="email"/);
  assert.match(markup, /type="radio" name="delivery-channel" value="whatsapp"/);
  assert.match(markup, /data-commercial-quote-consent type="checkbox" required/);
  assert.match(markup, /data-commercial-follow-up type="checkbox"/);
  assert.match(markup, /role="status" aria-live="polite" aria-atomic="true"/);
  assert.match(markup, /\/legal\/privacidad\//);
});

test("contact validation matches the public BFF boundary", () => {
  assert.equal(isValidCommercialContact("email", "contacto@example.com"), true);
  assert.equal(isValidCommercialContact("email", "contacto@localhost"), false);
  assert.equal(isValidCommercialContact("email", "a..b@example.com"), false);
  assert.equal(isValidCommercialContact("whatsapp", "+5493871234567"), true);
  assert.equal(isValidCommercialContact("whatsapp", "0387 1234567"), false);
});

test("posts one versioned consent payload without depending on internal agent identity", async () => {
  const calls: Array<{ input: string; init: RequestInit | undefined }> = [];
  const fetcher: typeof fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return Response.json({ opportunity_id: opportunityId, status: "accepted" }, { status: 202 });
  };

  await postCommercialContact(commercialPayload(), fetcher);

  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.input, "/api/v2/chat/commercial-contact");
  assert.equal(calls[0]?.init?.method, "POST");
  assert.equal(calls[0]?.init?.credentials, "same-origin");
  assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), commercialPayload());
  assert.equal(String(calls[0]?.init?.body).includes("target_agent_id"), false);
});

test("rejects malformed acknowledgements and exposes only the response status", async () => {
  const fetcher: typeof fetch = async () => Response.json({ status: "accepted" }, { status: 202 });

  await assert.rejects(
    postCommercialContact(commercialPayload(), fetcher),
    (error: unknown) => error instanceof CommercialContactApiError && error.status === 502,
  );
});

test("an uncertain retry can reuse the exact client request and consent payload", async () => {
  const bodies: string[] = [];
  let attempt = 0;
  const fetcher: typeof fetch = async (_input, init) => {
    bodies.push(String(init?.body));
    attempt += 1;
    if (attempt === 1) return new Response(null, { status: 503 });
    return Response.json({ opportunity_id: opportunityId, status: "accepted" }, { status: 202 });
  };
  const payload = commercialPayload();

  await assert.rejects(postCommercialContact(payload, fetcher), CommercialContactApiError);
  await postCommercialContact(payload, fetcher);

  assert.equal(bodies.length, 2);
  assert.equal(bodies[0], bodies[1]);
  assert.equal(JSON.parse(bodies[1]!).client_request_id, clientRequestId);
});

test("ordered public replay closes each accepted prompt without persisted personal data", () => {
  const prompt = (cursor: number, requestId: string) => ({
    schema_version: "2" as const,
    cursor,
    event_type: "commercial.contact.requested",
    payload: {
      request_id: requestId,
      title: `Presupuesto ${requestId}`,
      summary: "Solicitud comercial saneada.",
      preferred_delivery_channel: "email",
    },
  });
  const accepted = (cursor: number, requestId: string) => ({
    schema_version: "2" as const,
    cursor,
    event_type: "commercial.opportunity.created",
    payload: { client_request_id: requestId, status: "accepted" },
  });

  let state = applyCommercialEventCorrelation(undefined, prompt(10, "tool-request:1"));
  state = applyCommercialEventCorrelation(state, accepted(11, clientRequestId));
  assert.equal(state?.accepted, true);

  state = applyCommercialEventCorrelation(state, prompt(20, "tool-request:2"));
  assert.equal(state?.accepted, false);
  state = applyCommercialEventCorrelation(state, accepted(21, "30000000-3000-4000-8000-300000000003"));
  assert.equal(state?.accepted, true);
  assert.deepEqual(state?.attemptedClientRequestIds, []);
});

test("live correlation rejects another request id instead of falling back to order", () => {
  let state = applyCommercialEventCorrelation(undefined, {
    schema_version: "2",
    cursor: 10,
    event_type: "commercial.contact.requested",
    payload: {
      request_id: "tool-request:1",
      title: "Presupuesto",
      summary: "Solicitud comercial saneada.",
      preferred_delivery_channel: "whatsapp",
    },
  })!;
  state = { ...state, attemptedClientRequestIds: [clientRequestId] };

  const mismatched = applyCommercialEventCorrelation(state, {
    schema_version: "2",
    cursor: 11,
    event_type: "commercial.opportunity.created",
    payload: {
      client_request_id: "30000000-3000-4000-8000-300000000003",
      status: "accepted",
    },
  });

  assert.equal(mismatched?.accepted, false);
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  loadOrUpgradeServerHistory,
  mapServerMessage,
  postChatMessage,
} from "../src/scripts/chat-api.ts";

const clientMessageId = "10000000-1000-4000-8000-100000000001";
const history = {
  status: "active" as const,
  control_mode: "automated" as const,
  latest_event_id: 7,
  messages: [{
    message_id: "server-message",
    client_message_id: clientMessageId,
    role: "user" as const,
    content: "Necesito una web",
    status: "completed",
    created_at: "2026-09-06T00:00:00Z",
  }],
};

test("upgrades a legacy session explicitly before loading authoritative history", async () => {
  const calls: string[] = [];
  const responses = [
    new Response(JSON.stringify({ code: "chat_session_not_found" }), { status: 404 }),
    new Response(null, { status: 204 }),
    Response.json(history),
  ];
  const fetcher: typeof fetch = async (input, init) => {
    calls.push(`${init?.method ?? "GET"} ${String(input)}`);
    return responses.shift()!;
  };

  assert.deepEqual(await loadOrUpgradeServerHistory(fetcher), history);
  assert.deepEqual(calls, [
    "GET /api/v2/chat/history?limit=100",
    "POST /api/v1/chat/session/upgrade",
    "GET /api/v2/chat/history?limit=100",
  ]);
});

test("an existing v2 session never invokes the legacy upgrade", async () => {
  const calls: string[] = [];
  const fetcher: typeof fetch = async (input) => {
    calls.push(String(input));
    return Response.json(history);
  };

  assert.deepEqual(await loadOrUpgradeServerHistory(fetcher), history);
  assert.deepEqual(calls, ["/api/v2/chat/history?limit=100"]);
});

test("an uncertain retry posts the same persistent client message id", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const fetcher: typeof fetch = async (_input, init) => {
    bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
    return Response.json({
      client_message_id: clientMessageId,
      message_id: "server-message",
      status: "accepted",
      event_cursor: 8,
      duplicate: bodies.length > 1,
    }, { status: 202 });
  };
  const pending = { clientMessageId, text: "Necesito una web", status: "sending" as const };

  const first = await postChatMessage(pending, "privacy-v1", "es-AR", fetcher);
  const retried = await postChatMessage(pending, "privacy-v1", "es-AR", fetcher);

  assert.equal(first.duplicate, false);
  assert.equal(retried.duplicate, true);
  assert.equal(bodies[0]?.client_message_id, clientMessageId);
  assert.equal(bodies[1]?.client_message_id, clientMessageId);
});

test("server history maps to the local cache without changing identity", () => {
  assert.deepEqual(mapServerMessage(history.messages[0]!), {
    id: "server-message",
    clientMessageId,
    role: "user",
    text: "Necesito una web",
    state: "completed",
    createdAt: "2026-09-06T00:00:00Z",
  });
});

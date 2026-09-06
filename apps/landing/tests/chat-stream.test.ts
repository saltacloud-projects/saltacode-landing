import assert from "node:assert/strict";
import test from "node:test";

import { consumeChatEventStream, reconnectChatEvents } from "../src/scripts/chat-stream.ts";

const encoder = new TextEncoder();

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

function event(cursor: number, eventType: string, payload: Record<string, unknown>): string {
  return [
    `id: ${cursor}`,
    `event: ${eventType}`,
    `data: ${JSON.stringify({
      schema_version: "2",
      cursor,
      event_type: eventType,
      occurred_at: "2026-09-06T00:00:00Z",
      payload,
    })}`,
    "",
    "",
  ].join("\n");
}

test("consumes durable events split across network chunks and advances the cursor", async () => {
  const received: string[] = [];
  const payload = event(4, "chat.message.completed", { content: "Hola" });
  const cursor = await consumeChatEventStream(streamOf(payload.slice(0, 37), payload.slice(37)), 3, {
    isActive: () => true,
    onEvent: (item) => received.push(String(item.payload?.content)),
  });

  assert.equal(cursor, 4);
  assert.deepEqual(received, ["Hola"]);
});

test("rejects duplicate or out-of-order event cursors", async () => {
  await assert.rejects(
    consumeChatEventStream(streamOf(event(4, "chat.message.accepted", {})), 4, {
      isActive: () => true,
      onEvent: () => undefined,
    }),
    /stream_cursor_not_monotonic/,
  );
});

test("reconnects from the last consumed event without replaying rendered messages", async () => {
  const headers: string[] = [];
  const received: number[] = [];
  let active = true;
  const responses = [
    new Response(streamOf(event(4, "chat.execution.changed", { status: "running" }))),
    new Response(streamOf(event(5, "chat.message.completed", { content: "Respuesta" }))),
  ];
  const fetcher: typeof fetch = async (_input, init) => {
    headers.push(new Headers(init?.headers).get("Last-Event-ID") ?? "");
    return responses.shift()!;
  };

  await reconnectChatEvents({
    fetcher,
    initialCursor: 3,
    signal: new AbortController().signal,
    isActive: () => active,
    onCursorExpired: async () => 0,
    onEvent: (item) => {
      received.push(item.cursor!);
      if (item.cursor === 5) active = false;
    },
    wait: async () => undefined,
    random: () => 0,
  });

  assert.deepEqual(headers, ["3", "4"]);
  assert.deepEqual(received, [4, 5]);
});

test("refreshes history after an expired cursor before reconnecting", async () => {
  const headers: string[] = [];
  let active = true;
  let refreshed = 0;
  const fetcher: typeof fetch = async (_input, init) => {
    headers.push(new Headers(init?.headers).get("Last-Event-ID") ?? "");
    if (headers.length === 1) {
      return new Response(JSON.stringify({ code: "cursor_expired" }), {
        status: 409,
        headers: { "Content-Type": "application/problem+json" },
      });
    }
    return new Response(streamOf(event(9, "chat.message.completed", { content: "Recuperada" })));
  };

  await reconnectChatEvents({
    fetcher,
    initialCursor: 3,
    signal: new AbortController().signal,
    isActive: () => active,
    onCursorExpired: async () => {
      refreshed += 1;
      return 8;
    },
    onEvent: () => { active = false; },
    wait: async () => undefined,
  });

  assert.equal(refreshed, 1);
  assert.deepEqual(headers, ["3", "8"]);
});

test("closing the visual subscription aborts reconnect without sending a command", async () => {
  const controller = new AbortController();
  let requests = 0;
  const fetcher: typeof fetch = async (_input, init) => {
    requests += 1;
    return await new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")), { once: true });
    });
  };
  const subscription = reconnectChatEvents({
    fetcher,
    initialCursor: 0,
    signal: controller.signal,
    isActive: () => !controller.signal.aborted,
    onCursorExpired: async () => 0,
    onEvent: () => undefined,
  });
  controller.abort();
  await subscription;

  assert.equal(requests, 1);
});

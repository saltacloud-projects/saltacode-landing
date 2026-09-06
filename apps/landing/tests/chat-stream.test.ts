import assert from "node:assert/strict";
import test from "node:test";

import { consumeChatStream } from "../src/scripts/chat-stream.ts";

const encoder = new TextEncoder();

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

function data(event: Record<string, unknown>): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

const identity = { correlation_id: "correlation-1", response_id: "response-1" };

test("consumes a valid stream split across network chunks", async () => {
  const deltas: string[] = [];
  const outcomes: Array<string | undefined> = [];
  const payload = [
    data({ type: "chat.started", ...identity }),
    data({ type: "chat.delta", ...identity, sequence: 0, delta: "Hola" }),
    data({ type: "chat.delta", ...identity, sequence: 1, delta: " mundo" }),
    data({ type: "chat.done", ...identity, outcome: "completed" }),
  ].join("");

  await consumeChatStream(streamOf(payload.slice(0, 37), payload.slice(37)), {
    isActive: () => true,
    onDelta: (delta) => deltas.push(delta),
    onError: () => assert.fail("valid stream must not emit an error"),
    onDone: (outcome) => outcomes.push(outcome),
  });

  assert.equal(deltas.join(""), "Hola mundo");
  assert.deepEqual(outcomes, ["completed"]);
});

test("rejects identity changes after the stream starts", async () => {
  const stream = streamOf(
    data({ type: "chat.started", ...identity }),
    data({
      type: "chat.delta",
      correlation_id: "different-correlation",
      response_id: identity.response_id,
      sequence: 0,
      delta: "invalid",
    }),
  );

  await assert.rejects(
    consumeChatStream(stream, {
      isActive: () => true,
      onDelta: () => undefined,
      onError: () => undefined,
      onDone: () => undefined,
    }),
    /stream_identity_changed/,
  );
});

test("rejects duplicate or out-of-order delta sequences", async () => {
  const stream = streamOf(
    data({ type: "chat.started", ...identity }),
    data({ type: "chat.delta", ...identity, sequence: 0, delta: "first" }),
    data({ type: "chat.delta", ...identity, sequence: 0, delta: "duplicate" }),
  );

  await assert.rejects(
    consumeChatStream(stream, {
      isActive: () => true,
      onDelta: () => undefined,
      onError: () => undefined,
      onDone: () => undefined,
    }),
    /invalid_sequence/,
  );
});

test("rejects a stream that closes before chat.done", async () => {
  const stream = streamOf(
    data({ type: "chat.started", ...identity }),
    data({ type: "chat.delta", ...identity, sequence: 0, delta: "partial" }),
  );

  await assert.rejects(
    consumeChatStream(stream, {
      isActive: () => true,
      onDelta: () => undefined,
      onError: () => undefined,
      onDone: () => undefined,
    }),
    /incomplete_stream/,
  );
});

test("cancels consumption when the chat is no longer active", async () => {
  await assert.rejects(
    consumeChatStream(streamOf(data({ type: "chat.started", ...identity })), {
      isActive: () => false,
      onDelta: () => undefined,
      onError: () => undefined,
      onDone: () => undefined,
    }),
    (error: unknown) => error instanceof DOMException && error.name === "AbortError",
  );
});

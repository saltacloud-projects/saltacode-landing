import assert from "node:assert/strict";
import test from "node:test";

import {
  CHAT_TRANSCRIPT_MAX_BYTES,
  CHAT_TRANSCRIPT_MAX_MESSAGES,
  CHAT_TRANSCRIPT_STORAGE_KEY,
  CHAT_TRANSCRIPT_TTL_MS,
  CHAT_TRANSCRIPT_VERSION,
  applyChatEvent,
  clearChatTranscript,
  emptyChatTranscript,
  loadChatTranscript,
  parseChatTranscript,
  saveChatTranscript,
  type ChatTranscript,
  type ChatTranscriptStorage,
} from "../src/scripts/chat-transcript.ts";

class MemoryStorage implements ChatTranscriptStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

const now = Date.UTC(2026, 8, 6);
const clientMessageId = "10000000-1000-4000-8000-100000000001";

function conversation(): ChatTranscript {
  return {
    ...emptyChatTranscript(),
    latestEventId: 12,
    messages: [
      {
        id: "message-user",
        clientMessageId,
        role: "user",
        text: "Necesito un sistema web",
        state: "completed",
        createdAt: "2026-09-06T00:00:00Z",
      },
      {
        id: "message-assistant",
        clientMessageId: `${clientMessageId}:assistant`,
        role: "assistant",
        text: "Contame cómo trabajan hoy.",
        state: "completed",
        createdAt: "2026-09-06T00:00:01Z",
      },
    ],
  };
}

test("reload restores a bounded consented server snapshot and cursor", () => {
  const storage = new MemoryStorage();
  assert.equal(saveChatTranscript(storage, conversation(), now), true);

  const restored = loadChatTranscript(storage, now + CHAT_TRANSCRIPT_TTL_MS - 1);
  assert.equal(restored?.latestEventId, 12);
  assert.deepEqual(restored?.messages, conversation().messages);
  assert.equal(restored?.updatedAt, now);
  assert.equal(restored?.expiresAt, now + CHAT_TRANSCRIPT_TTL_MS);
  assert.equal(JSON.parse(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY)!).version, CHAT_TRANSCRIPT_VERSION);
});

test("reload preserves one pending client id for an idempotent retry", () => {
  const storage = new MemoryStorage();
  const pending = {
    ...emptyChatTranscript(),
    pending: [{ clientMessageId, text: "Necesito una web", status: "sending" as const }],
  };
  saveChatTranscript(storage, pending, now);

  const restored = loadChatTranscript(storage, now);
  assert.deepEqual(restored?.pending, pending.pending);
  assert.equal(restored?.pending[0]?.clientMessageId, clientMessageId);
});

test("human replies and control changes update the same durable conversation", () => {
  const transcript = conversation();
  const result = applyChatEvent(transcript, {
    schema_version: "2",
    cursor: 13,
    event_type: "chat.control.changed",
    occurred_at: "2026-09-06T00:00:02Z",
    payload: { mode: "human" },
  });
  const reply = applyChatEvent(transcript, {
    schema_version: "2",
    cursor: 14,
    event_type: "chat.message.completed",
    occurred_at: "2026-09-06T00:00:03Z",
    payload: { message_id: "operator-reply", role: "assistant", content: "Hola, soy Oscar." },
  });

  assert.equal(result.controlChanged, true);
  assert.equal(transcript.controlMode, "human");
  assert.equal(reply.receivedRole, "assistant");
  assert.equal(transcript.messages.at(-1)?.text, "Hola, soy Oscar.");
  assert.equal(transcript.latestEventId, 14);
});

test("expires and removes obsolete or corrupt local cache", () => {
  const storage = new MemoryStorage();
  saveChatTranscript(storage, conversation(), now);
  assert.equal(loadChatTranscript(storage, now + CHAT_TRANSCRIPT_TTL_MS), null);
  assert.equal(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY), null);

  storage.setItem(CHAT_TRANSCRIPT_STORAGE_KEY, "{not-json");
  assert.equal(loadChatTranscript(storage, now), null);
  assert.equal(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY), null);

  const obsolete = JSON.stringify({
    ...conversation(),
    version: CHAT_TRANSCRIPT_VERSION - 1,
    updatedAt: now,
    expiresAt: now + CHAT_TRANSCRIPT_TTL_MS,
  });
  assert.equal(parseChatTranscript(obsolete, now), null);
});

test("keeps the newest server messages within count and byte limits", () => {
  const storage = new MemoryStorage();
  const transcript = conversation();
  transcript.messages = Array.from({ length: CHAT_TRANSCRIPT_MAX_MESSAGES + 25 }, (_, index) => ({
    id: `message-${index}`,
    clientMessageId: `browser-${index}`,
    role: index % 2 ? "assistant" as const : "user" as const,
    text: `${index}:${"á".repeat(4_000)}`,
    state: "completed" as const,
    createdAt: new Date(now + index).toISOString(),
  }));

  assert.equal(saveChatTranscript(storage, transcript, now), true);
  const serialized = storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY)!;
  assert.ok(new TextEncoder().encode(serialized).byteLength <= CHAT_TRANSCRIPT_MAX_BYTES);
  const restored = parseChatTranscript(serialized, now);
  assert.ok(restored && restored.messages.length <= CHAT_TRANSCRIPT_MAX_MESSAGES);
  assert.match(restored!.messages.at(-1)!.text, /^124:/);
});

test("explicit reset and unavailable storage fail safely", () => {
  const storage = new MemoryStorage();
  saveChatTranscript(storage, conversation(), now);
  assert.equal(clearChatTranscript(storage), true);
  assert.equal(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY), null);

  const unavailable: ChatTranscriptStorage = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("quota"); },
    removeItem: () => { throw new Error("blocked"); },
  };
  assert.equal(loadChatTranscript(unavailable), null);
  assert.equal(saveChatTranscript(unavailable, conversation()), false);
  assert.equal(clearChatTranscript(unavailable), false);
});

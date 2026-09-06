import assert from "node:assert/strict";
import test from "node:test";

import {
  CHAT_TRANSCRIPT_MAX_BYTES,
  CHAT_TRANSCRIPT_MAX_MESSAGES,
  CHAT_TRANSCRIPT_STORAGE_KEY,
  CHAT_TRANSCRIPT_TTL_MS,
  CHAT_TRANSCRIPT_VERSION,
  clearChatTranscript,
  loadChatTranscript,
  parseChatTranscript,
  saveChatTranscript,
  type ChatTranscriptMessage,
  type ChatTranscriptStorage,
} from "../src/scripts/chat-transcript.ts";

class MemoryStorage implements ChatTranscriptStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

const completed: ChatTranscriptMessage[] = [
  { role: "user", text: "Necesito un sistema web", state: "completed" },
  { role: "agent", text: "Contame cómo trabajan hoy.", state: "completed" },
];

test("round-trips a consented transcript for 30 days without replay metadata", () => {
  const storage = new MemoryStorage();
  const now = Date.UTC(2026, 8, 1);
  assert.equal(saveChatTranscript(storage, completed, now), true);

  const restored = loadChatTranscript(storage, now + CHAT_TRANSCRIPT_TTL_MS - 1);
  assert.deepEqual(restored?.messages, completed);
  assert.equal(restored?.updatedAt, now);
  assert.equal(restored?.expiresAt, now + CHAT_TRANSCRIPT_TTL_MS);
  assert.equal(JSON.parse(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY)!).version, CHAT_TRANSCRIPT_VERSION);
});

test("expires, removes, and rejects obsolete or corrupt transcript data", () => {
  const storage = new MemoryStorage();
  const now = Date.UTC(2026, 8, 1);
  saveChatTranscript(storage, completed, now);
  assert.equal(loadChatTranscript(storage, now + CHAT_TRANSCRIPT_TTL_MS), null);
  assert.equal(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY), null);

  storage.setItem(CHAT_TRANSCRIPT_STORAGE_KEY, "{not-json");
  assert.equal(loadChatTranscript(storage, now), null);
  assert.equal(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY), null);

  const obsolete = JSON.stringify({
    version: CHAT_TRANSCRIPT_VERSION + 1,
    updatedAt: now,
    expiresAt: now + CHAT_TRANSCRIPT_TTL_MS,
    messages: completed,
  });
  assert.equal(parseChatTranscript(obsolete, now), null);
});

test("restores an unfinished response as interrupted without a request identifier", () => {
  const storage = new MemoryStorage();
  const now = Date.UTC(2026, 8, 1);
  saveChatTranscript(storage, [
    completed[0]!,
    { role: "agent", text: "Respuesta parcial", state: "pending" },
  ], now);

  const restored = loadChatTranscript(storage, now);
  assert.deepEqual(restored?.messages.at(-1), {
    role: "agent",
    text: "Respuesta parcial",
    state: "interrupted",
  });
  assert.equal(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY)?.includes("clientMessageId"), false);
});

test("keeps the newest messages within count and byte limits", () => {
  const storage = new MemoryStorage();
  const messages = Array.from({ length: CHAT_TRANSCRIPT_MAX_MESSAGES + 25 }, (_, index) => ({
    role: index % 2 ? "agent" as const : "user" as const,
    text: `${index}:${"á".repeat(4_000)}`,
    state: "completed" as const,
  }));

  assert.equal(saveChatTranscript(storage, messages, Date.UTC(2026, 8, 1)), true);
  const serialized = storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY)!;
  assert.ok(new TextEncoder().encode(serialized).byteLength <= CHAT_TRANSCRIPT_MAX_BYTES);
  const restored = parseChatTranscript(serialized, Date.UTC(2026, 8, 1));
  assert.ok(restored && restored.messages.length <= CHAT_TRANSCRIPT_MAX_MESSAGES);
  assert.match(restored!.messages.at(-1)!.text, /^104:/);
});

test("reset and unavailable storage fail safely", () => {
  const storage = new MemoryStorage();
  saveChatTranscript(storage, completed, Date.UTC(2026, 8, 1));
  assert.equal(clearChatTranscript(storage), true);
  assert.equal(storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY), null);

  const unavailable: ChatTranscriptStorage = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("quota"); },
    removeItem: () => { throw new Error("blocked"); },
  };
  assert.equal(loadChatTranscript(unavailable), null);
  assert.equal(saveChatTranscript(unavailable, completed), false);
  assert.equal(clearChatTranscript(unavailable), false);
});

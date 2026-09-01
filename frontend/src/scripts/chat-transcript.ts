export const CHAT_TRANSCRIPT_STORAGE_KEY = "saltacode-chat-transcript";
export const CHAT_TRANSCRIPT_VERSION = 1;
export const CHAT_TRANSCRIPT_TTL_MS = 30 * 24 * 60 * 60 * 1_000;
export const CHAT_TRANSCRIPT_MAX_MESSAGES = 80;
export const CHAT_TRANSCRIPT_MAX_BYTES = 64 * 1_024;

export type ChatTranscriptRole = "agent" | "user";
export type ChatTranscriptState = "completed" | "error" | "interrupted" | "pending";

export interface ChatTranscriptMessage {
  role: ChatTranscriptRole;
  text: string;
  state: ChatTranscriptState;
}

export interface ChatTranscript {
  updatedAt: number;
  expiresAt: number;
  messages: ChatTranscriptMessage[];
}

export interface ChatTranscriptStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

interface StoredChatTranscript extends ChatTranscript {
  version: number;
}

const textEncoder = new TextEncoder();
const MAX_MESSAGE_CHARACTERS = 12_000;

function byteLength(value: string): number {
  return textEncoder.encode(value).byteLength;
}

function normalizeMessage(value: unknown, restorePending: boolean): ChatTranscriptMessage | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ChatTranscriptMessage>;
  if (candidate.role !== "agent" && candidate.role !== "user") return null;
  if (typeof candidate.text !== "string" || !candidate.text.trim()) return null;
  if (!["completed", "error", "interrupted", "pending"].includes(candidate.state ?? "")) return null;
  return {
    role: candidate.role,
    text: candidate.text.slice(0, MAX_MESSAGE_CHARACTERS),
    state: restorePending && candidate.state === "pending" ? "interrupted" : candidate.state!,
  };
}

function serializeBounded(messages: readonly ChatTranscriptMessage[], now: number): string | null {
  const bounded = messages
    .map((message) => normalizeMessage(message, false))
    .filter((message): message is ChatTranscriptMessage => message !== null)
    .slice(-CHAT_TRANSCRIPT_MAX_MESSAGES);
  if (!bounded.length) return null;

  const envelope: StoredChatTranscript = {
    version: CHAT_TRANSCRIPT_VERSION,
    updatedAt: now,
    expiresAt: now + CHAT_TRANSCRIPT_TTL_MS,
    messages: bounded,
  };
  let serialized = JSON.stringify(envelope);
  while (byteLength(serialized) > CHAT_TRANSCRIPT_MAX_BYTES && envelope.messages.length > 1) {
    envelope.messages.shift();
    serialized = JSON.stringify(envelope);
  }
  if (byteLength(serialized) > CHAT_TRANSCRIPT_MAX_BYTES) return null;
  return serialized;
}

export function parseChatTranscript(serialized: string, now = Date.now()): ChatTranscript | null {
  if (!serialized || byteLength(serialized) > CHAT_TRANSCRIPT_MAX_BYTES) return null;
  try {
    const candidate = JSON.parse(serialized) as Partial<StoredChatTranscript>;
    if (
      candidate.version !== CHAT_TRANSCRIPT_VERSION ||
      typeof candidate.updatedAt !== "number" ||
      typeof candidate.expiresAt !== "number" ||
      !Number.isFinite(candidate.updatedAt) ||
      !Number.isFinite(candidate.expiresAt) ||
      candidate.updatedAt > now ||
      candidate.expiresAt <= now ||
      candidate.expiresAt - candidate.updatedAt > CHAT_TRANSCRIPT_TTL_MS ||
      !Array.isArray(candidate.messages) ||
      candidate.messages.length === 0 ||
      candidate.messages.length > CHAT_TRANSCRIPT_MAX_MESSAGES
    ) return null;

    const messages = candidate.messages
      .map((message) => normalizeMessage(message, true))
      .filter((message): message is ChatTranscriptMessage => message !== null);
    if (messages.length !== candidate.messages.length) return null;
    return { updatedAt: candidate.updatedAt, expiresAt: candidate.expiresAt, messages };
  } catch {
    return null;
  }
}

export function loadChatTranscript(storage: ChatTranscriptStorage, now = Date.now()): ChatTranscript | null {
  let serialized: string | null = null;
  try {
    serialized = storage.getItem(CHAT_TRANSCRIPT_STORAGE_KEY);
  } catch {
    return null;
  }
  if (serialized === null) return null;
  const transcript = parseChatTranscript(serialized, now);
  if (!transcript) clearChatTranscript(storage);
  return transcript;
}

export function saveChatTranscript(
  storage: ChatTranscriptStorage,
  messages: readonly ChatTranscriptMessage[],
  now = Date.now(),
): boolean {
  const serialized = serializeBounded(messages, now);
  if (!serialized) return false;
  try {
    storage.setItem(CHAT_TRANSCRIPT_STORAGE_KEY, serialized);
    return true;
  } catch {
    return false;
  }
}

export function clearChatTranscript(storage: ChatTranscriptStorage): boolean {
  try {
    storage.removeItem(CHAT_TRANSCRIPT_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

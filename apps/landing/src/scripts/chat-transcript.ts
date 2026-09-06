export const CHAT_TRANSCRIPT_STORAGE_KEY = "saltacode-chat-transcript";
export const CHAT_TRANSCRIPT_VERSION = 2;
export const CHAT_TRANSCRIPT_TTL_MS = 30 * 24 * 60 * 60 * 1_000;
export const CHAT_TRANSCRIPT_MAX_MESSAGES = 100;
export const CHAT_TRANSCRIPT_MAX_PENDING = 8;
export const CHAT_TRANSCRIPT_MAX_BYTES = 64 * 1_024;

export type ChatTranscriptRole = "assistant" | "user";
export type ChatTranscriptState = "accepted" | "completed" | "error" | "pending";
export type ChatControlMode = "automated" | "closed" | "human" | "paused";

export interface ChatTranscriptMessage {
  id: string;
  clientMessageId: string;
  role: ChatTranscriptRole;
  text: string;
  state: ChatTranscriptState;
  createdAt: string;
}

export interface PendingChatMessage {
  clientMessageId: string;
  text: string;
  status: "accepted" | "sending";
}

export interface ChatTranscript {
  updatedAt: number;
  expiresAt: number;
  latestEventId: number;
  controlMode: ChatControlMode;
  messages: ChatTranscriptMessage[];
  pending: PendingChatMessage[];
}

export interface ChatTranscriptStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface ChatEventResult {
  receivedRole: ChatTranscriptRole | undefined;
  failed: boolean;
  controlChanged: boolean;
}

interface StoredChatTranscript extends ChatTranscript {
  version: number;
}

const textEncoder = new TextEncoder();
const MAX_MESSAGE_CHARACTERS = 16_000;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTROL_MODES: ChatControlMode[] = ["automated", "closed", "human", "paused"];
const MESSAGE_STATES: ChatTranscriptState[] = ["accepted", "completed", "error", "pending"];

function byteLength(value: string): number {
  return textEncoder.encode(value).byteLength;
}

function normalizeMessage(value: unknown): ChatTranscriptMessage | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ChatTranscriptMessage>;
  if (candidate.role !== "assistant" && candidate.role !== "user") return null;
  if (typeof candidate.id !== "string" || !candidate.id.trim()) return null;
  if (typeof candidate.clientMessageId !== "string" || !candidate.clientMessageId.trim()) return null;
  if (typeof candidate.text !== "string" || !candidate.text.trim()) return null;
  if (!MESSAGE_STATES.includes((candidate.state ?? "") as ChatTranscriptState)) return null;
  if (typeof candidate.createdAt !== "string" || !Number.isFinite(Date.parse(candidate.createdAt))) return null;
  return {
    id: candidate.id.slice(0, 255),
    clientMessageId: candidate.clientMessageId.slice(0, 255),
    role: candidate.role,
    text: candidate.text.slice(0, MAX_MESSAGE_CHARACTERS),
    state: candidate.state!,
    createdAt: candidate.createdAt,
  };
}

function normalizePending(value: unknown): PendingChatMessage | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<PendingChatMessage>;
  if (typeof candidate.clientMessageId !== "string" || !UUID_PATTERN.test(candidate.clientMessageId)) return null;
  if (typeof candidate.text !== "string" || !candidate.text.trim()) return null;
  if (candidate.status !== "accepted" && candidate.status !== "sending") return null;
  return {
    clientMessageId: candidate.clientMessageId,
    text: candidate.text.slice(0, MAX_MESSAGE_CHARACTERS),
    status: candidate.status,
  };
}

function serializeBounded(transcript: ChatTranscript, now: number): string | null {
  const messages = transcript.messages
    .map(normalizeMessage)
    .filter((message): message is ChatTranscriptMessage => message !== null)
    .slice(-CHAT_TRANSCRIPT_MAX_MESSAGES);
  const pending = transcript.pending
    .map(normalizePending)
    .filter((message): message is PendingChatMessage => message !== null)
    .slice(-CHAT_TRANSCRIPT_MAX_PENDING);
  if (!messages.length && !pending.length) return null;

  const envelope: StoredChatTranscript = {
    version: CHAT_TRANSCRIPT_VERSION,
    updatedAt: now,
    expiresAt: now + CHAT_TRANSCRIPT_TTL_MS,
    latestEventId: Math.max(0, Math.trunc(transcript.latestEventId)),
    controlMode: transcript.controlMode,
    messages,
    pending,
  };
  let serialized = JSON.stringify(envelope);
  while (byteLength(serialized) > CHAT_TRANSCRIPT_MAX_BYTES && envelope.messages.length > 1) {
    envelope.messages.shift();
    serialized = JSON.stringify(envelope);
  }
  return byteLength(serialized) <= CHAT_TRANSCRIPT_MAX_BYTES ? serialized : null;
}

export function emptyChatTranscript(): ChatTranscript {
  return {
    updatedAt: 0,
    expiresAt: 0,
    latestEventId: 0,
    controlMode: "automated",
    messages: [],
    pending: [],
  };
}

export function applyChatEvent(transcript: ChatTranscript, event: ChatEvent): ChatEventResult {
  if (event.cursor !== undefined) transcript.latestEventId = event.cursor;
  const payload = event.payload ?? {};
  const clientMessageId = typeof payload.client_message_id === "string" ? payload.client_message_id : "";
  const messageId = typeof payload.message_id === "string" ? payload.message_id : "";
  const content = typeof payload.content === "string" ? payload.content : "";
  const mode = typeof payload.mode === "string" ? payload.mode as ChatControlMode : undefined;
  let receivedRole: ChatTranscriptRole | undefined;
  let failed = false;
  let controlChanged = false;

  if (event.event_type === "chat.message.accepted" && clientMessageId) {
    const pending = transcript.pending.find((message) => message.clientMessageId === clientMessageId);
    if (pending) pending.status = "accepted";
  }
  if (content && messageId) {
    receivedRole = payload.role === "user" ? "user" : "assistant";
    const nextMessage: ChatTranscriptMessage = {
      id: messageId,
      clientMessageId: clientMessageId || messageId,
      role: receivedRole,
      text: content,
      state: "completed",
      createdAt: event.occurred_at ?? new Date().toISOString(),
    };
    const index = transcript.messages.findIndex((message) => message.id === messageId);
    if (index >= 0) transcript.messages[index] = nextMessage;
    else transcript.messages.push(nextMessage);
    if (clientMessageId) {
      const inbound = transcript.messages.find((message) => message.clientMessageId === clientMessageId);
      if (inbound) inbound.state = "completed";
      transcript.pending = transcript.pending.filter((message) => message.clientMessageId !== clientMessageId);
    }
  }
  if (event.event_type === "chat.message.failed" && clientMessageId) {
    failed = true;
    transcript.pending = transcript.pending.filter((message) => message.clientMessageId !== clientMessageId);
    transcript.messages.push({
      id: `error:${event.cursor ?? clientMessageId}`,
      clientMessageId: `error:${clientMessageId}`,
      role: "assistant",
      text: payload.error_code === "conversation_control_changed"
        ? "La automatización se pausó para permitir atención humana."
        : "No pude completar esa respuesta. Podés reintentar o contactar al equipo.",
      state: "error",
      createdAt: event.occurred_at ?? new Date().toISOString(),
    });
  }
  if (mode && CONTROL_MODES.includes(mode)) {
    transcript.controlMode = mode;
    controlChanged = true;
  }
  if (event.event_type === "chat.conversation.closed") {
    transcript.controlMode = "closed";
    controlChanged = true;
  }
  return { receivedRole, failed, controlChanged };
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
      !Number.isSafeInteger(candidate.latestEventId) ||
      candidate.latestEventId! < 0 ||
      !CONTROL_MODES.includes((candidate.controlMode ?? "") as ChatControlMode) ||
      !Array.isArray(candidate.messages) ||
      !Array.isArray(candidate.pending) ||
      candidate.messages.length > CHAT_TRANSCRIPT_MAX_MESSAGES ||
      candidate.pending.length > CHAT_TRANSCRIPT_MAX_PENDING
    ) return null;

    const messages = candidate.messages.map(normalizeMessage);
    const pending = candidate.pending.map(normalizePending);
    if (messages.includes(null) || pending.includes(null)) return null;
    return {
      updatedAt: candidate.updatedAt,
      expiresAt: candidate.expiresAt,
      latestEventId: candidate.latestEventId!,
      controlMode: candidate.controlMode!,
      messages: messages as ChatTranscriptMessage[],
      pending: pending as PendingChatMessage[],
    };
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
  transcript: ChatTranscript,
  now = Date.now(),
): boolean {
  const serialized = serializeBounded(transcript, now);
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
import type { ChatEvent } from "./chat-stream";

import type { ChatControlMode, ChatTranscriptMessage, PendingChatMessage } from "./chat-transcript";

export interface ChatHistory {
  status: "active" | "closed";
  control_mode: ChatControlMode;
  latest_event_id: number;
  messages: Array<{
    message_id: string;
    client_message_id: string;
    role: "assistant" | "user";
    content: string;
    status: string;
    created_at: string;
  }>;
}

export interface AcceptedMessage {
  client_message_id: string;
  message_id: string;
  status: "accepted";
  event_cursor: number;
  duplicate: boolean;
}

export class ChatApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code || `chat_api_${status}`);
    this.status = status;
    this.code = code;
  }
}

async function parseError(response: Response): Promise<ChatApiError> {
  try {
    const body = await response.json() as { code?: unknown };
    return new ChatApiError(response.status, typeof body.code === "string" ? body.code : "");
  } catch {
    return new ChatApiError(response.status, "");
  }
}

async function requestJson<T>(fetcher: typeof fetch, path: string, init?: RequestInit): Promise<T> {
  const response = await fetcher(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) throw await parseError(response);
  return await response.json() as T;
}

export async function loadServerHistory(fetcher: typeof fetch = fetch): Promise<ChatHistory | null> {
  try {
    return await requestJson<ChatHistory>(fetcher, "/api/v2/chat/history?limit=100");
  } catch (error) {
    if (error instanceof ChatApiError && error.status === 404) return null;
    throw error;
  }
}

export async function upgradeLegacySession(fetcher: typeof fetch = fetch): Promise<boolean> {
  const response = await fetcher("/api/v1/chat/session/upgrade", {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (response.status === 204) return true;
  if (response.status === 404) return false;
  throw await parseError(response);
}

export async function loadOrUpgradeServerHistory(fetcher: typeof fetch = fetch): Promise<ChatHistory | null> {
  const current = await loadServerHistory(fetcher);
  if (current) return current;
  if (!await upgradeLegacySession(fetcher)) return null;
  return await loadServerHistory(fetcher);
}

export async function postChatMessage(
  message: PendingChatMessage,
  privacyVersion: string,
  locale: "en" | "es-AR",
  fetcher: typeof fetch = fetch,
): Promise<AcceptedMessage> {
  return await requestJson<AcceptedMessage>(fetcher, "/api/v2/chat/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_message_id: message.clientMessageId,
      message: message.text,
      locale,
      transcript_consent: true,
      privacy_version: privacyVersion,
    }),
  });
}

export async function resetServerChat(
  privacyVersion: string,
  fetcher: typeof fetch = fetch,
): Promise<number> {
  const result = await requestJson<{ latest_event_id: number }>(fetcher, "/api/v2/chat/session/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript_consent: true, privacy_version: privacyVersion }),
  });
  return result.latest_event_id;
}

export function mapServerMessage(message: ChatHistory["messages"][number]): ChatTranscriptMessage {
  return {
    id: message.message_id,
    clientMessageId: message.client_message_id,
    role: message.role,
    text: message.content,
    state: message.status === "completed" ? "completed" : "accepted",
    createdAt: message.created_at,
  };
}

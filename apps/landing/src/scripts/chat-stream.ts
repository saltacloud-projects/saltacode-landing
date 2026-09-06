export interface ChatEvent {
  schema_version: "2";
  cursor?: number;
  event_type?: string;
  occurred_at?: string;
  payload?: Record<string, unknown>;
  code?: string;
  retryable?: boolean;
  outcome?: string;
}

export interface ChatEventStreamHandlers {
  isActive: () => boolean;
  onEvent: (event: ChatEvent) => void;
}

export interface ReconnectChatOptions extends ChatEventStreamHandlers {
  fetcher?: typeof fetch;
  initialCursor: number;
  signal: AbortSignal;
  onCursorExpired: () => Promise<number>;
  onRetry?: (attempt: number) => void;
  wait?: (delayMs: number, signal: AbortSignal) => Promise<void>;
  random?: () => number;
}

const MIN_RETRY_DELAY_MS = 400;
const MAX_RETRY_DELAY_MS = 8_000;

function parseFrame(frame: string): ChatEvent | undefined {
  const lines = frame.split("\n");
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return undefined;

  let event: ChatEvent;
  try {
    event = JSON.parse(data) as ChatEvent;
  } catch {
    throw new Error("invalid_stream_json");
  }
  if (event.schema_version !== "2") throw new Error("invalid_stream_version");

  const id = lines.find((line) => line.startsWith("id:"))?.slice(3).trim();
  const type = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
  if (id !== undefined) {
    const cursor = Number(id);
    if (!Number.isSafeInteger(cursor) || cursor < 1 || String(cursor) !== id) {
      throw new Error("invalid_stream_cursor");
    }
    if (event.cursor !== cursor) throw new Error("stream_cursor_changed");
  }
  if (type && event.event_type && event.event_type !== type) throw new Error("stream_event_type_changed");
  if (type) event.event_type = type;
  return event;
}

export async function consumeChatEventStream(
  stream: ReadableStream<Uint8Array>,
  cursor: number,
  handlers: ChatEventStreamHandlers,
): Promise<number> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let latestCursor = cursor;
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (!handlers.isActive()) {
      await reader.cancel();
      throw new DOMException("", "AbortError");
    }
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const event = parseFrame(frame);
      if (!event) continue;
      if (event.cursor !== undefined) {
        if (event.cursor <= latestCursor) throw new Error("stream_cursor_not_monotonic");
        latestCursor = event.cursor;
      }
      handlers.onEvent(event);
    }
    if (done) return latestCursor;
  }
}

function defaultWait(delayMs: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, delayMs);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("", "AbortError"));
    }, { once: true });
  });
}

async function problemCode(response: Response): Promise<string> {
  try {
    const body = await response.json() as { code?: unknown };
    return typeof body.code === "string" ? body.code : "";
  } catch {
    return "";
  }
}

export async function reconnectChatEvents(options: ReconnectChatOptions): Promise<void> {
  const fetcher = options.fetcher ?? fetch;
  const wait = options.wait ?? defaultWait;
  const random = options.random ?? Math.random;
  let cursor = options.initialCursor;
  let attempt = 0;

  while (options.isActive() && !options.signal.aborted) {
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (cursor > 0) headers["Last-Event-ID"] = String(cursor);
      const response = await fetcher("/api/v2/chat/events", {
        credentials: "same-origin",
        headers,
        signal: options.signal,
      });
      if (response.status === 409 && await problemCode(response) === "cursor_expired") {
        cursor = await options.onCursorExpired();
        attempt = 0;
        continue;
      }
      if (!response.ok || !response.body) throw new Error(`event_stream_${response.status}`);
      cursor = await consumeChatEventStream(response.body, cursor, options);
      attempt = 0;
    } catch (error) {
      if (options.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) return;
      attempt += 1;
      options.onRetry?.(attempt);
    }

    if (!options.isActive() || options.signal.aborted) return;
    const exponential = Math.min(MAX_RETRY_DELAY_MS, MIN_RETRY_DELAY_MS * 2 ** Math.min(attempt, 5));
    const delay = Math.round(exponential * (0.8 + random() * 0.4));
    try {
      await wait(delay, options.signal);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      throw error;
    }
  }
}

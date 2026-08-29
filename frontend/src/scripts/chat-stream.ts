export interface ChatStreamEvent {
  type: string;
  correlation_id?: string;
  response_id?: string;
  sequence?: number;
  delta?: string;
  retryable?: boolean;
  outcome?: string;
}

export interface ChatStreamHandlers {
  isActive: () => boolean;
  onDelta: (delta: string) => void;
  onError: (retryable: boolean) => void;
  onDone: (outcome: string | undefined) => void;
}

interface ChatStreamState {
  started: boolean;
  done: boolean;
  correlationId: string;
  responseId: string;
  lastSequence: number;
}

function parseFrame(frame: string): ChatStreamEvent | undefined {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");

  if (!data) return undefined;

  try {
    return JSON.parse(data) as ChatStreamEvent;
  } catch {
    throw new Error("invalid_stream_json");
  }
}

function assertIdentity(event: ChatStreamEvent, state: ChatStreamState): void {
  if (event.correlation_id !== state.correlationId || event.response_id !== state.responseId) {
    throw new Error("stream_identity_changed");
  }
}

function applyEvent(event: ChatStreamEvent, state: ChatStreamState, handlers: ChatStreamHandlers): void {
  if (state.done) throw new Error("event_after_done");

  if (event.type === "chat.started") {
    if (state.started || !event.correlation_id || !event.response_id) throw new Error("bad_started");
    state.started = true;
    state.correlationId = event.correlation_id;
    state.responseId = event.response_id;
    return;
  }

  if (!state.started) throw new Error("stream_not_started");
  assertIdentity(event, state);

  if (event.type === "chat.delta") {
    if (!event.delta || !Number.isInteger(event.sequence) || event.sequence! <= state.lastSequence) {
      throw new Error("invalid_sequence");
    }
    state.lastSequence = event.sequence!;
    handlers.onDelta(event.delta);
    return;
  }

  if (event.type === "chat.error") {
    handlers.onError(event.retryable === true);
    return;
  }

  if (event.type === "chat.done") {
    state.done = true;
    handlers.onDone(event.outcome);
    return;
  }

  throw new Error("unknown_stream_event");
}

export async function consumeChatStream(
  stream: ReadableStream<Uint8Array>,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const state: ChatStreamState = {
    started: false,
    done: false,
    correlationId: "",
    responseId: "",
    lastSequence: -1,
  };
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
      if (event) applyEvent(event, state, handlers);
    }

    if (done) break;
  }

  if (!state.started || !state.done) throw new Error("incomplete_stream");
}

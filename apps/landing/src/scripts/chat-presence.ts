import type { ChatControlMode } from "./chat-transcript";

export interface VisitorPresenceSignal {
  client_instance_id: string;
  sequence: number;
  typing: boolean;
}

interface PresenceClock {
  now: () => number;
  schedule: (callback: () => void, delay: number) => number;
  cancel: (timer: number) => void;
}

const browserClock: PresenceClock = {
  now: () => Date.now(),
  schedule: (callback, delay) => window.setTimeout(callback, delay),
  cancel: (timer) => window.clearTimeout(timer),
};
const RENEW_INTERVAL_MS = 3_000;
const EDIT_IDLE_MS = 4_000;
const PRESENCE_TTL_MS = 8_000;

export interface ChatPresenceController {
  receive: (value: unknown) => void;
  clear: () => void;
  stop: () => void;
  edit: (hasContent: boolean) => void;
  label: (mode: ChatControlMode) => string;
}

export function createChatPresence(options: {
  instanceId: string;
  canSend: () => boolean;
  onChange: () => void;
}): ChatPresenceController {
  let operatorTyping = false;
  const receiver = createOperatorPresence((typing) => {
    operatorTyping = typing;
    options.onChange();
  });
  const sender = createVisitorPresence({ ...options, send: postVisitorPresence });
  return {
    receive: receiver.receive,
    clear: receiver.clear,
    stop: sender.stop,
    edit: sender.edit,
    label: (mode) => operatorTypingLabel(operatorTyping, mode),
  };
}

export async function postVisitorPresence(
  signal: VisitorPresenceSignal,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4_000);
  try {
    const response = await fetcher("/api/v2/chat/presence", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        client_instance_id: signal.client_instance_id,
        sequence: signal.sequence,
        typing: signal.typing,
      }),
      signal: controller.signal,
      keepalive: !signal.typing,
    });
    if (!response.ok) throw new Error(`presence_${response.status}`);
  } finally {
    clearTimeout(timer);
  }
}

export function operatorTypingExpiry(value: unknown, now: number): number | null {
  if (!value || typeof value !== "object") return null;
  const operator = (value as { operator?: unknown }).operator;
  if (!operator || typeof operator !== "object") return null;
  const state = operator as { typing?: unknown; expires_at?: unknown };
  if (state.typing !== true || typeof state.expires_at !== "string") return null;
  const expiry = Date.parse(state.expires_at);
  return Number.isFinite(expiry) && expiry > now ? Math.min(expiry, now + PRESENCE_TTL_MS) : null;
}

export function operatorTypingLabel(typing: boolean, mode: ChatControlMode): string {
  return typing && mode === "human" ? "Una persona del equipo está escribiendo…" : "";
}

export function createOperatorPresence(
  onChange: (typing: boolean) => void,
  clock: PresenceClock = browserClock,
) {
  let timer: number | undefined;
  let active = false;
  function change(typing: boolean): void {
    if (active === typing) return;
    active = typing;
    onChange(typing);
  }
  function clear(): void {
    if (timer !== undefined) clock.cancel(timer);
    timer = undefined;
    change(false);
  }
  return {
    clear,
    receive(value: unknown): void {
      if (timer !== undefined) clock.cancel(timer);
      timer = undefined;
      const expiry = operatorTypingExpiry(value, clock.now());
      if (expiry === null) {
        change(false);
        return;
      }
      change(true);
      timer = clock.schedule(clear, expiry - clock.now());
    },
  };
}

export function createVisitorPresence(options: {
  instanceId: string;
  canSend: () => boolean;
  send: (signal: VisitorPresenceSignal) => Promise<void>;
  clock?: PresenceClock;
}) {
  const clock = options.clock ?? browserClock;
  let sequence = 0;
  let active = false;
  let lastSent = -Infinity;
  let renewal: number | undefined;
  let idle: number | undefined;

  function cancelTimers(): void {
    if (renewal !== undefined) clock.cancel(renewal);
    if (idle !== undefined) clock.cancel(idle);
    renewal = undefined;
    idle = undefined;
  }

  function publish(typing: boolean): void {
    active = typing;
    lastSent = clock.now();
    const sentSequence = ++sequence;
    void options.send({
      client_instance_id: options.instanceId,
      sequence: sentSequence,
      typing,
    }).catch(() => {
      // Presence is best effort; an uncertain signal expires server-side, never blocking a message.
      if (sequence === sentSequence) {
        active = false;
        cancelTimers();
      }
    });
  }

  function stop(): void {
    cancelTimers();
    if (active) publish(false);
  }

  return {
    stop,
    edit(hasContent: boolean): void {
      if (!hasContent || !options.canSend()) {
        stop();
        return;
      }
      if (idle !== undefined) clock.cancel(idle);
      idle = clock.schedule(stop, EDIT_IDLE_MS);
      const remaining = RENEW_INTERVAL_MS - (clock.now() - lastSent);
      if (remaining <= 0) {
        if (renewal !== undefined) clock.cancel(renewal);
        renewal = undefined;
        publish(true);
      } else if (renewal === undefined) {
        renewal = clock.schedule(() => {
          renewal = undefined;
          if (options.canSend()) publish(true);
          else stop();
        }, remaining);
      }
    },
  };
}

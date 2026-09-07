import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { ApiError, apiResponse } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../auth/permissions";

interface InboxSnapshot {
  revision: string;
  unread_conversations: number;
  active_conversations: number;
  historical_conversations: number;
}

interface InboxLiveState {
  snapshot: InboxSnapshot | null;
  connected: boolean;
  revision: number;
}

const InboxLiveContext = createContext<InboxLiveState>({
  snapshot: null,
  connected: false,
  revision: 0,
});

function parseSnapshot(value: string): InboxSnapshot {
  const parsed = JSON.parse(value) as InboxSnapshot;
  if (
    typeof parsed.revision !== "string" ||
    ![
      parsed.unread_conversations,
      parsed.active_conversations,
      parsed.historical_conversations,
    ].every((count) => Number.isSafeInteger(count) && count >= 0)
  )
    throw new Error("Invalid inbox snapshot");
  return parsed;
}

export function InboxLiveProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const allowed = hasPermission(user, PERMISSIONS.CONVERSATIONS_READ);
  const [state, setState] = useState<InboxLiveState>({
    snapshot: null,
    connected: false,
    revision: 0,
  });

  useEffect(() => {
    setState({ snapshot: null, connected: false, revision: 0 });
    if (!allowed || !user?.id) return;
    let disposed = false;
    let active: AbortController | null = null;
    let reconnect: number | undefined;
    let retryDelay = 1_000;

    const connect = async () => {
      if (disposed || document.visibilityState !== "visible") return;
      const controller = new AbortController();
      active?.abort();
      active = controller;
      let idleTimeout: number | undefined;
      const resetIdleTimeout = () => {
        window.clearTimeout(idleTimeout);
        idleTimeout = window.setTimeout(() => controller.abort("idle-timeout"), 45_000);
      };
      resetIdleTimeout();
      try {
        const response = await apiResponse("/crm/inbox/live", {
          signal: controller.signal,
          headers: { Accept: "text/event-stream" },
          cache: "no-store",
        });
        if (!response.headers.get("content-type")?.includes("text/event-stream") || !response.body)
          throw new Error("Inbox stream unavailable");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        try {
          while (!controller.signal.aborted) {
            const chunk = await reader.read();
            if (chunk.done) break;
            resetIdleTimeout();
            buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replace(
              /\r\n/g,
              "\n",
            );
            if (buffer.length > 64_000) throw new Error("Inbox event exceeds limit");
            let separator = buffer.indexOf("\n\n");
            while (separator !== -1) {
              const frame = buffer.slice(0, separator);
              buffer = buffer.slice(separator + 2);
              const lines = frame.split("\n");
              const event = lines
                .find((line) => line.startsWith("event:"))
                ?.slice(6)
                .trim();
              if (event === "inbox.access_revoked") {
                setState((current) => ({
                  snapshot: null,
                  connected: false,
                  revision: current.revision + 1,
                }));
                throw new ApiError(401, "Inbox authorization changed");
              }
              if (event === "inbox.snapshot") {
                const snapshot = parseSnapshot(
                  lines
                    .filter((line) => line.startsWith("data:"))
                    .map((line) => line.slice(5).trim())
                    .join("\n"),
                );
                if (!controller.signal.aborted && !disposed) {
                  setState((current) => ({
                    snapshot,
                    connected: true,
                    revision:
                      current.revision +
                      (!current.connected || current.snapshot?.revision !== snapshot.revision
                        ? 1
                        : 0),
                  }));
                  retryDelay = 1_000;
                }
              }
              separator = buffer.indexOf("\n\n");
            }
          }
        } finally {
          await reader.cancel().catch(() => undefined);
          reader.releaseLock();
        }
      } catch (error) {
        if (
          !disposed &&
          active === controller &&
          !controller.signal.aborted &&
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        ) {
          setState((current) => ({
            snapshot: null,
            connected: false,
            revision: current.revision + 1,
          }));
        }
      } finally {
        window.clearTimeout(idleTimeout);
        if (!disposed && active === controller) {
          setState((current) => ({ ...current, connected: false }));
          if (
            (!controller.signal.aborted || controller.signal.reason === "idle-timeout") &&
            document.visibilityState === "visible"
          ) {
            reconnect = window.setTimeout(() => void connect(), retryDelay);
            retryDelay = Math.min(retryDelay * 2, 15_000);
          }
        }
      }
    };
    const visibilityChanged = () => {
      setState((current) => ({ ...current, connected: false }));
      window.clearTimeout(reconnect);
      active?.abort();
      if (document.visibilityState === "visible") void connect();
    };
    document.addEventListener("visibilitychange", visibilityChanged);
    void connect();
    return () => {
      disposed = true;
      window.clearTimeout(reconnect);
      active?.abort();
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [allowed, user?.id]);

  return <InboxLiveContext.Provider value={state}>{children}</InboxLiveContext.Provider>;
}

export function useInboxLive() {
  return useContext(InboxLiveContext);
}

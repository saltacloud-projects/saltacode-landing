import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { publishOperatorPresence } from "./api";

const SIGNAL_INTERVAL_MS = 3_000;
const IDLE_TIMEOUT_MS = 8_000;

function instanceIdentity(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // randomUUID requires a secure context; local LAN review still exposes getRandomValues.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Publish only editing events, never draft content or periodic presence from an idle draft. */
export function useOperatorPresence({
  agentId,
  conversationId,
  controlVersion,
  enabled,
}: {
  agentId: string;
  conversationId: string | undefined;
  controlVersion: number | undefined;
  enabled: boolean;
}) {
  const [instanceId] = useState(instanceIdentity);
  const sequence = useRef(0);
  const handlers = useRef({ edit: (_hasText: boolean) => {}, stop: () => {} });

  useEffect(() => {
    if (!enabled || !agentId || !conversationId || controlVersion === undefined) return;
    let active = false;
    let suspended = false;
    let lastSignalAt = -Infinity;
    let idleTimer: number | undefined;
    const send = (typing: boolean) => {
      active = typing;
      lastSignalAt = performance.now();
      void publishOperatorPresence(agentId, conversationId, {
        client_instance_id: instanceId,
        sequence: ++sequence.current,
        typing,
        expected_control_version: controlVersion,
      }).catch((error: unknown) => {
        // Presence is best-effort and must not interrupt a reply or retry across an ownership epoch.
        if (error instanceof ApiError && [401, 403, 409, 423].includes(error.status))
          suspended = true;
      });
    };
    const stop = () => {
      window.clearTimeout(idleTimer);
      if (active) send(false);
    };
    const edit = (hasText: boolean) => {
      if (!hasText || document.visibilityState !== "visible") return stop();
      if (suspended) return;
      window.clearTimeout(idleTimer);
      if (!active || performance.now() - lastSignalAt >= SIGNAL_INTERVAL_MS) send(true);
      idleTimer = window.setTimeout(stop, IDLE_TIMEOUT_MS);
    };
    const visibility = () => {
      if (document.visibilityState !== "visible") stop();
    };
    handlers.current = { edit, stop };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("blur", stop);
    window.addEventListener("pagehide", stop);
    return () => {
      stop();
      handlers.current = { edit: () => {}, stop: () => {} };
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("blur", stop);
      window.removeEventListener("pagehide", stop);
    };
  }, [agentId, conversationId, controlVersion, enabled, instanceId]);

  return {
    edit: useCallback((hasText: boolean) => handlers.current.edit(hasText), []),
    stop: useCallback(() => handlers.current.stop(), []),
  };
}

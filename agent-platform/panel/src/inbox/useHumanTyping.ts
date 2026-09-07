import { useEffect, useMemo, useState } from "react";
import type { TypingState } from "./types";

/** Locally expire stale presence even if no new SSE snapshot arrives. */
export function useHumanTyping(state: TypingState | undefined, enabled: boolean): boolean {
  const [, invalidate] = useState(0);
  const expiresAt = useMemo(
    () => Math.min(Date.parse(state?.expires_at ?? ""), Date.now() + 8_000),
    [state?.expires_at],
  );
  const typing = enabled && Boolean(state?.typing) && expiresAt > Date.now();
  useEffect(() => {
    if (!typing) return;
    const timer = window.setTimeout(() => invalidate((value) => value + 1), expiresAt - Date.now());
    return () => window.clearTimeout(timer);
  }, [typing, expiresAt]);
  return typing;
}

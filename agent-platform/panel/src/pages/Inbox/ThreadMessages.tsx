import { LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useInboxLive } from "../../inbox/InboxLiveContext";
import type { InboxThread } from "../../inbox/types";
import { formatDate } from "./presentation";

interface ThreadMessagesProps {
  thread: InboxThread;
  loading: boolean;
  onMessagesRead: (conversationId: string, messageIds: string[]) => Promise<boolean>;
}

export function ThreadMessages({ thread, loading, onMessagesRead }: ThreadMessagesProps) {
  const { connected, revision } = useInboxLive();
  const currentObservation = useRef(() => {});
  const viewport = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const visible = useRef(false);
  const pending = useRef(false);
  const acknowledged = useRef(new Set<string>());
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const { conversation, messages } = thread;
  const activity =
    connected &&
    conversation.observedLiveRevision === revision &&
    document.visibilityState === "visible" &&
    conversation.control_mode === "automated"
      ? conversation.agent_activity
      : null;
  const lastMessageId = messages[messages.length - 1]?.id;

  const observeRead = useCallback(() => {
    if (
      !following.current ||
      !visible.current ||
      loading ||
      pending.current ||
      document.visibilityState !== "visible" ||
      !conversation.unread_count
    )
      return;
    const messageIds = messages
      .filter((message) => message.role === "user" && !acknowledged.current.has(message.id))
      .map((message) => message.id);
    if (!messageIds.length) return;
    pending.current = true;
    void onMessagesRead(conversation.id, messageIds).then((applied) => {
      if (applied) for (const messageId of messageIds) acknowledged.current.add(messageId);
      pending.current = false;
      if (applied) currentObservation.current();
    });
  }, [conversation.id, conversation.unread_count, messages, loading, onMessagesRead]);
  currentObservation.current = observeRead;

  useLayoutEffect(() => {
    if (!lastMessageId && !activity?.status) return;
    if (following.current && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight;
    else setHasNewMessages(true);
  }, [lastMessageId, activity?.status]);

  useEffect(() => {
    const sentinel = bottom.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible.current = entry.isIntersecting;
        observeRead();
      },
      { threshold: 1 },
    );
    observer.observe(sentinel);
    document.addEventListener("visibilitychange", observeRead);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", observeRead);
    };
  }, [observeRead]);

  const onScroll = () => {
    const element = viewport.current;
    if (!element) return;
    following.current = element.scrollHeight - element.scrollTop - element.clientHeight < 12;
    if (following.current) setHasNewMessages(false);
    observeRead();
  };

  return (
    <>
      <div
        ref={viewport}
        onScroll={onScroll}
        className="flex min-h-48 max-h-[55dvh] flex-1 flex-col gap-3 overflow-y-auto overscroll-contain p-4"
        role="log"
        aria-label="Mensajes de la conversación"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {loading && messages.length === 0 ? (
          <LoaderCircle className="animate-spin text-[var(--text-muted)]" size={18} />
        ) : (
          messages.map((message) => (
            <article
              key={message.id}
              className={`max-w-[90%] rounded-xl px-3 py-2 text-sm ${message.role === "user" ? "ml-auto bg-[var(--accent)] text-white" : "mr-auto border border-[var(--border-color)] bg-[var(--bg-secondary)]"}`}
            >
              <p
                className={`mb-1 text-xs font-semibold ${message.role === "user" ? "text-white" : "text-amber-300"}`}
              >
                {message.role === "user"
                  ? "Visitante"
                  : message.origin === "operator"
                    ? "Operador"
                    : message.role === "assistant"
                      ? "Agente"
                      : "Sistema"}
              </p>
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
              <footer
                className={`mt-2 flex flex-wrap gap-1 text-[10px] ${message.role === "user" ? "text-white/75" : "text-[var(--text-muted)]"}`}
              >
                <time dateTime={message.created_at}>{formatDate(message.created_at)}</time>
                {message.status !== "completed" && <span>· {message.status}</span>}
              </footer>
            </article>
          ))
        )}
        {activity && (
          <p
            role="status"
            className="mr-auto flex items-center gap-2 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-xs text-amber-300"
          >
            <span aria-hidden="true" className="flex gap-1 motion-safe:animate-pulse">
              <span>●</span>
              <span>●</span>
              <span>●</span>
            </span>
            {activity.status === "queued"
              ? `${activity.name}: respuesta en cola…`
              : `${activity.name} está preparando una respuesta…`}
          </p>
        )}
        <div ref={bottom} aria-hidden="true" className="h-px shrink-0" />
      </div>
      {hasNewMessages && (
        <button
          type="button"
          onClick={() => {
            following.current = true;
            if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
            setHasNewMessages(false);
          }}
          className="mx-auto mb-2 min-h-10 rounded-full border border-[var(--accent)] px-4 text-xs text-[var(--accent)]"
        >
          Ver mensajes nuevos ↓
        </button>
      )}
    </>
  );
}

import { LoaderCircle } from "lucide-react";
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useInboxLive } from "../../inbox/InboxLiveContext";
import type { InboxThread } from "../../inbox/types";
import {
  AUTHOR_LABELS,
  calendarDay,
  dayLabel,
  formatDate,
  messageAuthor,
  messageTime,
} from "./presentation";

interface ThreadMessagesProps {
  thread: InboxThread;
  loading: boolean;
  obscured?: boolean;
  onMessagesRead: (conversationId: string, messageIds: string[]) => Promise<boolean>;
}

export function ThreadMessages({
  thread,
  loading,
  obscured = false,
  onMessagesRead,
}: ThreadMessagesProps) {
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
      obscured ||
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
  }, [conversation.id, conversation.unread_count, messages, loading, obscured, onMessagesRead]);
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
        className={`${obscured ? "invisible" : ""} flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-3 pb-4 pt-2 sm:px-5`}
        role="log"
        aria-label="Mensajes de la conversación"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {loading && messages.length === 0 ? (
          <LoaderCircle className="animate-spin text-[var(--text-secondary)]" size={18} />
        ) : (
          messages.map((message, index) => {
            const previous = messages[index - 1];
            const startsDay =
              !previous || calendarDay(previous.created_at) !== calendarDay(message.created_at);
            const author = messageAuthor(message);
            const showAuthor =
              startsDay ||
              !previous ||
              messageAuthor(previous) !== author ||
              previous.actor_admin_id !== message.actor_admin_id ||
              new Date(message.created_at).getTime() - new Date(previous.created_at).getTime() >
                5 * 60_000;
            const inbound = author === "visitor";
            return (
              <Fragment key={message.id}>
                {startsDay && (
                  <h4 className="mx-auto mb-2 mt-4 shrink-0 rounded-full border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-1 text-[10px] font-medium text-[var(--text-secondary)]">
                    {dayLabel(message.created_at)}
                  </h4>
                )}
                <article
                  aria-label={`${AUTHOR_LABELS[author]} · ${formatDate(message.created_at)}`}
                  className={`${showAuthor ? "mt-3" : "mt-1"} max-w-[92%] shrink-0 rounded-2xl px-3 py-2 text-sm sm:max-w-[82%] ${inbound ? "mr-auto rounded-bl-md border border-[var(--border-color)] bg-[var(--bg-card)]" : "ml-auto rounded-br-md border border-[color-mix(in_srgb,var(--accent)_20%,transparent)] bg-[color-mix(in_srgb,var(--accent)_10%,transparent)]"}`}
                >
                  {showAuthor && (
                    <p
                      className={`mb-1 text-[11px] font-semibold ${inbound ? "text-[var(--text-secondary)]" : "text-amber-300"}`}
                    >
                      {AUTHOR_LABELS[author]}
                    </p>
                  )}
                  <p className="whitespace-pre-wrap break-words leading-relaxed">
                    {message.content}
                  </p>
                  <footer className="mt-1.5 flex flex-wrap justify-end gap-1 text-[10px] text-[var(--text-secondary)]">
                    <time dateTime={message.created_at} title={formatDate(message.created_at)}>
                      {messageTime(message.created_at)}
                    </time>
                    {message.status !== "completed" && <span>· {message.status}</span>}
                  </footer>
                </article>
              </Fragment>
            );
          })
        )}
        {activity && (
          <p
            role="status"
            className="ml-auto mt-3 flex shrink-0 items-center gap-2 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-xs text-amber-300"
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
          className={`${obscured ? "invisible" : ""} mx-auto my-2 min-h-11 rounded-full border border-[var(--accent)] px-4 text-xs text-[var(--accent-hover)]`}
        >
          Ver mensajes nuevos ↓
        </button>
      )}
    </>
  );
}

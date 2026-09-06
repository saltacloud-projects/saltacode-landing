import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import type { AdminUser } from "../../auth/AuthContext";
import {
  getInboxThread,
  listInboxConversations,
  listInboxOperators,
  sendInboxOperatorMessage,
  transitionInboxConversation,
} from "../../inbox/api";
import type {
  ControlTransition,
  InboxConversation,
  InboxFilters,
  InboxOperator,
  InboxThread,
} from "../../inbox/types";

const EMPTY_FILTERS: InboxFilters = {
  channel: "",
  controlMode: "",
  status: "active",
  owner: "",
  updatedWithinHours: "",
};

interface UseInboxStateOptions {
  agentId?: string;
  user: AdminUser | null;
  canManage: boolean;
}

function idempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return `operator-${crypto.randomUUID()}`;
  const bytes = crypto.getRandomValues(new Uint32Array(4));
  return `operator-${Array.from(bytes, (value) => value.toString(16)).join("-")}`;
}

function errorMessage(value: unknown, fallback: string): string {
  return value instanceof ApiError ? value.message : fallback;
}

export function useInboxState({ agentId, user, canManage }: UseInboxStateOptions) {
  const [items, setItems] = useState<InboxConversation[]>([]);
  const [operators, setOperators] = useState<InboxOperator[]>([]);
  const [thread, setThread] = useState<InboxThread | null>(null);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [reassignTo, setReassignTo] = useState("");
  const activeAgentId = useRef<string | null>(agentId ?? null);
  const selectedConversationId = useRef<string | null>(null);
  activeAgentId.current = agentId ?? null;
  selectedConversationId.current = thread?.conversation.id ?? null;

  const loadList = useCallback(
    async (requestedAgentId: string, activeFilters: InboxFilters, silent = false) => {
      if (!user) return;
      if (!silent) setLoadingList(true);
      try {
        const page = await listInboxConversations(requestedAgentId, activeFilters, user.id);
        if (activeAgentId.current === requestedAgentId) setItems(page.items);
      } catch (value) {
        if (activeAgentId.current === requestedAgentId) {
          setError(errorMessage(value, "No se pudo cargar el inbox."));
        }
      } finally {
        if (!silent && activeAgentId.current === requestedAgentId) setLoadingList(false);
      }
    },
    [user],
  );

  const loadThread = useCallback(async (requestedAgentId: string, conversationId: string) => {
    setLoadingThread(true);
    try {
      const nextThread = await getInboxThread(requestedAgentId, conversationId);
      if (
        activeAgentId.current === requestedAgentId &&
        selectedConversationId.current === conversationId
      ) {
        setThread(nextThread);
        setReassignTo(nextThread.conversation.assigned_operator?.id ?? "");
      }
    } catch (value) {
      if (activeAgentId.current === requestedAgentId) {
        setError(errorMessage(value, "No se pudo cargar la conversación."));
      }
    } finally {
      if (activeAgentId.current === requestedAgentId) setLoadingThread(false);
    }
  }, []);

  useEffect(() => {
    setItems([]);
    setThread(null);
    setOperators([]);
    setError("");
    setDraft("");
    if (!agentId) {
      setLoadingList(false);
      return;
    }
    void loadList(agentId, filters);
    if (canManage) {
      void listInboxOperators(agentId)
        .then((rows) => {
          if (activeAgentId.current === agentId) setOperators(rows);
        })
        .catch((value) => {
          if (activeAgentId.current === agentId) {
            setError(errorMessage(value, "No se pudieron cargar los operadores."));
          }
        });
    }
  }, [agentId, filters, canManage, loadList]);

  useEffect(() => {
    if (!agentId) return;
    const timer = window.setInterval(() => {
      void loadList(agentId, filters, true);
      const conversationId = selectedConversationId.current;
      if (conversationId) void loadThread(agentId, conversationId);
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [agentId, filters, loadList, loadThread]);

  const openConversation = (conversation: InboxConversation) => {
    if (!agentId) return;
    setError("");
    setThread({ conversation, messages: [], control_events: [] });
    selectedConversationId.current = conversation.id;
    void loadThread(agentId, conversation.id);
  };

  const refreshSelected = useCallback(async () => {
    const conversationId = selectedConversationId.current;
    if (!agentId || !conversationId) return;
    await Promise.all([loadList(agentId, filters, true), loadThread(agentId, conversationId)]);
  }, [agentId, filters, loadList, loadThread]);

  const runTransition = async (transition: Omit<ControlTransition, "expected_version">) => {
    const conversation = thread?.conversation;
    if (!agentId || !conversation || busy) return;
    setBusy(true);
    setError("");
    try {
      await transitionInboxConversation(agentId, conversation.id, {
        ...transition,
        expected_version: conversation.control_version,
      });
      await refreshSelected();
    } catch (value) {
      if (value instanceof ApiError && value.status === 409) {
        await refreshSelected();
        setError("La conversación cambió. Actualizamos el estado antes de volver a intentar.");
      } else {
        setError(errorMessage(value, "No se pudo actualizar el control."));
      }
    } finally {
      setBusy(false);
    }
  };

  const sendMessage = async () => {
    const conversation = thread?.conversation;
    const content = draft.trim();
    if (!agentId || !conversation || !content || busy) return;
    setBusy(true);
    setError("");
    try {
      await sendInboxOperatorMessage(
        agentId,
        conversation.id,
        content,
        conversation.control_version,
        idempotencyKey(),
      );
      setDraft("");
      await refreshSelected();
    } catch (value) {
      if (value instanceof ApiError && value.status === 409) {
        await refreshSelected();
        setError("La conversación cambió. Verificá el control antes de responder.");
      } else {
        setError(errorMessage(value, "No se pudo enviar la respuesta."));
      }
    } finally {
      setBusy(false);
    }
  };

  const ownsConversation = useMemo(
    () =>
      Boolean(
        canManage &&
          user &&
          thread?.conversation.control_mode === "human" &&
          thread.conversation.assigned_operator?.id === user.id,
      ),
    [canManage, thread, user],
  );

  return {
    items,
    operators,
    thread,
    filters,
    loadingList,
    loadingThread,
    busy,
    error,
    draft,
    reassignTo,
    ownsConversation,
    setFilters,
    setDraft,
    setReassignTo,
    openConversation,
    closeThread: () => setThread(null),
    refreshList: () => (agentId ? loadList(agentId, filters) : Promise.resolve()),
    runTransition,
    sendMessage,
  };
}

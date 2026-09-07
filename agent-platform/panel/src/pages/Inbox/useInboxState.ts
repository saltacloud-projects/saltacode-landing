import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import type { AdminUser } from "../../auth/AuthContext";
import { PERMISSIONS } from "../../auth/permissions";
import { type CrmListOptions, canOperateItem } from "../../crm/operations";
import {
  assignInboxAutomationAgent,
  getInboxThread,
  listInboxAutomationAssignments,
  listInboxConversations,
  listInboxOperators,
  markInboxMessagesRead,
  sendInboxOperatorMessage,
  transitionInboxConversation,
} from "../../inbox/api";
import { useInboxLive } from "../../inbox/InboxLiveContext";
import type {
  AutomationAssignmentEvent,
  ControlTransition,
  InboxConversation,
  InboxFilters,
  InboxOperator,
  InboxThread,
} from "../../inbox/types";

const ASSIGNMENT_HISTORY_PAGE_SIZE = 10;

const EMPTY_FILTERS: InboxFilters = {
  channel: "",
  controlMode: "",
  status: "",
  lifecycle: "active",
  owner: "",
  lastMessagePeriod: "all",
  search: "",
  unreadOnly: false,
};

interface UseInboxStateOptions extends CrmListOptions {
  agentId?: string;
  user: AdminUser | null;
  canManage: boolean;
}

function idempotencyKey(): string {
  return requestIdentity("operator");
}

function requestIdentity(prefix: string): string {
  if (typeof crypto.randomUUID === "function") return `${prefix}-${crypto.randomUUID()}`;
  const bytes = crypto.getRandomValues(new Uint32Array(4));
  return `${prefix}-${Array.from(bytes, (value) => value.toString(16)).join("-")}`;
}

function errorMessage(value: unknown, fallback: string): string {
  return value instanceof ApiError ? value.message : fallback;
}

export function useInboxState({
  agentId = "",
  user,
  canManage,
  global = false,
  offset = 0,
}: UseInboxStateOptions) {
  const { revision, connected } = useInboxLive();
  const liveRevision = useRef(revision);
  liveRevision.current = revision;
  const ownerAgentId = useRef(agentId);
  const threadGeneration = useRef(0);
  const readPending = useRef(false);
  const [total, setTotal] = useState(0);
  const listGeneration = useRef(0);
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
  const [automationAgentTo, setAutomationAgentTo] = useState("");
  const [automationAssignmentNotice, setAutomationAssignmentNotice] = useState("");
  const [assignmentHistoryVisible, setAssignmentHistoryVisible] = useState(false);
  const [assignmentHistoryLoading, setAssignmentHistoryLoading] = useState(false);
  const [assignmentHistoryItems, setAssignmentHistoryItems] = useState<AutomationAssignmentEvent[]>(
    [],
  );
  const [assignmentHistoryTotal, setAssignmentHistoryTotal] = useState(0);
  const activeAgentId = useRef<string | null>(agentId ?? null);
  const selectedConversationId = useRef<string | null>(null);
  const automationSelectionDirty = useRef(false);
  activeAgentId.current = agentId ?? null;
  selectedConversationId.current = thread?.conversation.id ?? null;

  const loadList = useCallback(
    async (requestedAgentId: string, activeFilters: InboxFilters, silent = false) => {
      if (!user) return;
      const generation = ++listGeneration.current;
      const requestedLiveRevision = liveRevision.current;
      if (!silent) setLoadingList(true);
      try {
        const page = await listInboxConversations(requestedAgentId, activeFilters, user.id, {
          global,
          offset,
        });
        if (generation === listGeneration.current && activeAgentId.current === requestedAgentId) {
          setItems(
            page.items.map((item) => ({ ...item, observedLiveRevision: requestedLiveRevision })),
          );
          setTotal(page.total);
        }
      } catch (value) {
        if (generation === listGeneration.current && activeAgentId.current === requestedAgentId) {
          if (value instanceof ApiError && (value.status === 401 || value.status === 403)) {
            setItems([]);
            setTotal(0);
            setThread(null);
            setDraft("");
          }
          setError(errorMessage(value, "No se pudo cargar el inbox."));
        }
      } finally {
        if (generation === listGeneration.current && activeAgentId.current === requestedAgentId)
          setLoadingList(false);
      }
    },
    [user, global, offset],
  );

  const loadThread = useCallback(
    async (requestedAgentId: string, conversationId: string, silent = false) => {
      const generation = ++threadGeneration.current;
      const requestedLiveRevision = liveRevision.current;
      if (!silent) setLoadingThread(true);
      try {
        const nextThread = await getInboxThread(requestedAgentId, conversationId);
        if (
          generation === threadGeneration.current &&
          ownerAgentId.current === requestedAgentId &&
          selectedConversationId.current === conversationId
        ) {
          setThread((current) => ({
            ...nextThread,
            conversation: {
              ...current?.conversation,
              ...nextThread.conversation,
              observedLiveRevision: requestedLiveRevision,
            },
          }));
          setReassignTo(nextThread.conversation.assigned_operator?.id ?? "");
          if (!automationSelectionDirty.current) {
            setAutomationAgentTo(nextThread.conversation.automation_agent.id);
          }
        }
      } catch (value) {
        if (
          generation === threadGeneration.current &&
          ownerAgentId.current === requestedAgentId &&
          selectedConversationId.current === conversationId
        ) {
          if (value instanceof ApiError && (value.status === 403 || value.status === 404))
            setThread(null);
          setError(errorMessage(value, "No se pudo cargar la conversación."));
        }
      } finally {
        if (generation === threadGeneration.current && ownerAgentId.current === requestedAgentId)
          setLoadingThread(false);
      }
    },
    [],
  );

  useEffect(() => {
    setItems([]);
    setThread(null);
    setOperators([]);
    setError("");
    setDraft("");
    setAutomationAgentTo("");
    setAutomationAssignmentNotice("");
    setAssignmentHistoryVisible(false);
    setAssignmentHistoryItems([]);
    setAssignmentHistoryTotal(0);
    automationSelectionDirty.current = false;
    if (!agentId && !global) {
      setLoadingList(false);
      return;
    }
    if (canManage && agentId && !global) {
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
  }, [agentId, canManage, global]);

  useEffect(() => {
    if (agentId || global) void loadList(agentId, filters);
  }, [agentId, global, filters, loadList]);

  useEffect(() => {
    if ((!agentId && !global) || !revision || document.visibilityState !== "visible") return;
    void loadList(agentId, filters, true);
    const conversationId = selectedConversationId.current;
    if (conversationId) void loadThread(ownerAgentId.current, conversationId, true);
  }, [agentId, filters, loadList, loadThread, global, revision]);

  useEffect(() => {
    if ((!agentId && !global) || connected) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadList(agentId, filters, true);
      const conversationId = selectedConversationId.current;
      if (conversationId) void loadThread(ownerAgentId.current, conversationId, true);
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [agentId, filters, loadList, loadThread, global, connected]);

  useEffect(() => {
    if (!filters.lastMessagePeriod || ["all", "custom"].includes(filters.lastMessagePeriod)) return;
    let timer: number;
    const schedule = () => {
      const midnight = new Date();
      midnight.setHours(24, 0, 0, 0);
      timer = window.setTimeout(
        () => {
          if (document.visibilityState === "visible") void loadList(agentId, filters, true);
          schedule();
        },
        midnight.getTime() - Date.now() + 25,
      );
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [agentId, filters, loadList]);

  const openConversation = (conversation: InboxConversation) => {
    const owner = conversation.owner_agent_id ?? (global ? "" : agentId);
    if (!owner) return;
    ownerAgentId.current = owner;
    setOperators([]);
    if (canOperateItem(global, conversation, user, PERMISSIONS.CONVERSATIONS_MANAGE)) {
      void listInboxOperators(owner)
        .then((rows) => {
          if (ownerAgentId.current === owner) setOperators(rows);
        })
        .catch(() => setOperators([]));
    }
    setError("");
    setDraft("");
    setThread({ conversation, messages: [], control_events: [] });
    setAutomationAgentTo(conversation.automation_agent.id);
    setAutomationAssignmentNotice("");
    setAssignmentHistoryVisible(false);
    setAssignmentHistoryItems([]);
    setAssignmentHistoryTotal(0);
    automationSelectionDirty.current = false;
    selectedConversationId.current = conversation.id;
    void loadThread(owner, conversation.id);
  };

  const refreshSelected = useCallback(async () => {
    const conversationId = selectedConversationId.current;
    if ((!agentId && !global) || !conversationId) return;
    await Promise.all([
      loadList(agentId, filters, true),
      loadThread(ownerAgentId.current, conversationId, true),
    ]);
  }, [agentId, filters, loadList, loadThread, global]);

  const runTransition = async (transition: Omit<ControlTransition, "expected_version">) => {
    const conversation = thread?.conversation;
    if (!ownerAgentId.current || !conversation || busy) return;
    setBusy(true);
    setError("");
    try {
      await transitionInboxConversation(ownerAgentId.current, conversation.id, {
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
    if (!ownerAgentId.current || !conversation || !content || busy) return;
    setBusy(true);
    setError("");
    try {
      await sendInboxOperatorMessage(
        ownerAgentId.current,
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

  const loadAssignmentHistory = useCallback(
    async (offset: number, append: boolean) => {
      const requestedOwner = ownerAgentId.current;
      const conversationId = selectedConversationId.current;
      if (!ownerAgentId.current || !conversationId || assignmentHistoryLoading) return;
      setAssignmentHistoryLoading(true);
      try {
        const page = await listInboxAutomationAssignments(
          ownerAgentId.current,
          conversationId,
          ASSIGNMENT_HISTORY_PAGE_SIZE,
          offset,
        );
        if (
          ownerAgentId.current === requestedOwner &&
          selectedConversationId.current === conversationId
        ) {
          setAssignmentHistoryItems((current) =>
            append ? [...current, ...page.items] : page.items,
          );
          setAssignmentHistoryTotal(page.total);
        }
      } catch (value) {
        if (ownerAgentId.current === requestedOwner) {
          setError(errorMessage(value, "No se pudo cargar el historial de agentes."));
        }
      } finally {
        if (ownerAgentId.current === requestedOwner) setAssignmentHistoryLoading(false);
      }
    },
    [assignmentHistoryLoading],
  );

  const toggleAssignmentHistory = async () => {
    if (assignmentHistoryVisible) {
      setAssignmentHistoryVisible(false);
      return;
    }
    setAssignmentHistoryVisible(true);
    if (assignmentHistoryItems.length === 0) await loadAssignmentHistory(0, false);
  };

  const selectAutomationAgent = (value: string) => {
    automationSelectionDirty.current = true;
    setAutomationAgentTo(value);
    setAutomationAssignmentNotice("");
  };

  const assignAutomationAgent = async () => {
    const conversation = thread?.conversation;
    if (
      !ownerAgentId.current ||
      !conversation ||
      !automationAgentTo ||
      automationAgentTo === conversation.automation_agent.id ||
      busy
    ) {
      return;
    }
    setBusy(true);
    setError("");
    setAutomationAssignmentNotice("");
    try {
      await assignInboxAutomationAgent(
        ownerAgentId.current,
        conversation.id,
        {
          target_agent_id: automationAgentTo,
          expected_automation_version: conversation.automation_version,
          trigger: "operator_reassignment",
          reason: "Assigned from operator inbox",
        },
        requestIdentity("automation-assignment"),
        requestIdentity("inbox-correlation"),
      );
      automationSelectionDirty.current = false;
      await refreshSelected();
      setAutomationAssignmentNotice(
        conversation.control_mode === "automated"
          ? "Agente de respuesta automática actualizado."
          : "Agente preparado. El control actual no cambió y la automatización sigue detenida.",
      );
      if (assignmentHistoryVisible) await loadAssignmentHistory(0, false);
    } catch (value) {
      automationSelectionDirty.current = false;
      if (value instanceof ApiError && value.status === 409) {
        await refreshSelected();
        setError(
          "La asignación cambió. Actualizamos el agente automático antes de volver a intentar.",
        );
      } else if (value instanceof ApiError && value.status === 404) {
        await refreshSelected();
        setError("No se pudo completar la asignación con los permisos disponibles.");
      } else {
        setError(errorMessage(value, "No se pudo actualizar el agente automático."));
      }
    } finally {
      setBusy(false);
    }
  };

  const markVisibleMessagesRead = useCallback(
    async (conversationId: string, messageIds: string[]) => {
      if (
        document.visibilityState !== "visible" ||
        readPending.current ||
        !messageIds.length ||
        selectedConversationId.current !== conversationId
      )
        return false;
      const owner = ownerAgentId.current;
      readPending.current = true;
      try {
        const result = await markInboxMessagesRead(owner, conversationId, messageIds);
        if (ownerAgentId.current === owner && selectedConversationId.current === conversationId) {
          setThread((current) =>
            current &&
            current.conversation.id === conversationId &&
            (!current.conversation.latest_inbound_message_id ||
              messageIds.includes(current.conversation.latest_inbound_message_id))
              ? {
                  ...current,
                  conversation: { ...current.conversation, unread_count: result.unread_count },
                }
              : current,
          );
          setItems((current) =>
            current.map((item) =>
              item.id === conversationId &&
              (!item.latest_inbound_message_id ||
                messageIds.includes(item.latest_inbound_message_id))
                ? { ...item, unread_count: result.unread_count }
                : item,
            ),
          );
        }
        return true;
      } catch {
        // A read acknowledgement never blocks the operator's draft or changes message delivery.
        return false;
      } finally {
        readPending.current = false;
      }
    },
    [],
  );

  const ownsConversation = useMemo(
    () =>
      Boolean(
        canManage &&
          canOperateItem(global, thread?.conversation, user, PERMISSIONS.CONVERSATIONS_MANAGE) &&
          user &&
          thread?.conversation.control_mode === "human" &&
          thread.conversation.status !== "closed" &&
          thread.conversation.assigned_operator?.id === user.id,
      ),
    [canManage, global, thread, user],
  );

  return {
    items,
    total,
    ownerAgentId: ownerAgentId.current,
    operators,
    thread,
    filters,
    loadingList,
    loadingThread,
    busy,
    error,
    draft,
    reassignTo,
    automationAgentTo,
    automationAssignmentNotice,
    assignmentHistoryVisible,
    assignmentHistoryLoading,
    assignmentHistoryItems,
    assignmentHistoryTotal,
    ownsConversation,
    setFilters,
    setDraft,
    setReassignTo,
    selectAutomationAgent,
    openConversation,
    markVisibleMessagesRead,
    closeThread: () => setThread(null),
    refreshList: () => (agentId || global ? loadList(agentId, filters) : Promise.resolve()),
    runTransition,
    sendMessage,
    assignAutomationAgent,
    toggleAssignmentHistory,
    loadMoreAssignmentHistory: () => loadAssignmentHistory(assignmentHistoryItems.length, true),
  };
}

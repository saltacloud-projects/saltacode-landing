import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import type { AdminUser } from "../../auth/AuthContext";
import {
  assignInboxAutomationAgent,
  getInboxThread,
  listInboxAutomationAssignments,
  listInboxConversations,
  listInboxOperators,
  sendInboxOperatorMessage,
  transitionInboxConversation,
} from "../../inbox/api";
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
        if (!automationSelectionDirty.current) {
          setAutomationAgentTo(nextThread.conversation.automation_agent.id);
        }
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
    setAutomationAgentTo("");
    setAutomationAssignmentNotice("");
    setAssignmentHistoryVisible(false);
    setAssignmentHistoryItems([]);
    setAssignmentHistoryTotal(0);
    automationSelectionDirty.current = false;
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
    setAutomationAgentTo(conversation.automation_agent.id);
    setAutomationAssignmentNotice("");
    setAssignmentHistoryVisible(false);
    setAssignmentHistoryItems([]);
    setAssignmentHistoryTotal(0);
    automationSelectionDirty.current = false;
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

  const loadAssignmentHistory = useCallback(
    async (offset: number, append: boolean) => {
      const conversationId = selectedConversationId.current;
      if (!agentId || !conversationId || assignmentHistoryLoading) return;
      setAssignmentHistoryLoading(true);
      try {
        const page = await listInboxAutomationAssignments(
          agentId,
          conversationId,
          ASSIGNMENT_HISTORY_PAGE_SIZE,
          offset,
        );
        if (
          activeAgentId.current === agentId &&
          selectedConversationId.current === conversationId
        ) {
          setAssignmentHistoryItems((current) =>
            append ? [...current, ...page.items] : page.items,
          );
          setAssignmentHistoryTotal(page.total);
        }
      } catch (value) {
        if (activeAgentId.current === agentId) {
          setError(errorMessage(value, "No se pudo cargar el historial de agentes."));
        }
      } finally {
        if (activeAgentId.current === agentId) setAssignmentHistoryLoading(false);
      }
    },
    [agentId, assignmentHistoryLoading],
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
      !agentId ||
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
        agentId,
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
    closeThread: () => setThread(null),
    refreshList: () => (agentId ? loadList(agentId, filters) : Promise.resolve()),
    runTransition,
    sendMessage,
    assignAutomationAgent,
    toggleAssignmentHistory,
    loadMoreAssignmentHistory: () => loadAssignmentHistory(assignmentHistoryItems.length, true),
  };
}

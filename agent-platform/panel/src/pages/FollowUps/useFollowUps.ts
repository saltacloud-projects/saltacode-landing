import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import {
  cancelFollowUp,
  getFollowUp,
  listFollowUpEvents,
  listFollowUps,
  requeueFollowUp,
  resolveFollowUpReview,
} from "./api";
import type { FollowUpDetail, FollowUpEvent, FollowUpFilters, FollowUpQueueItem } from "./types";

const EMPTY_FILTERS: FollowUpFilters = { status: "", kind: "" };

function errorMessage(value: unknown, fallback: string): string {
  return value instanceof Error ? value.message : fallback;
}

export function useFollowUps(agentId?: string) {
  const [items, setItems] = useState<FollowUpQueueItem[]>([]);
  const [detail, setDetail] = useState<FollowUpDetail | null>(null);
  const [events, setEvents] = useState<FollowUpEvent[]>([]);
  const [filters, setFilters] = useState<FollowUpFilters>(EMPTY_FILTERS);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeAgentId = useRef(agentId);
  const selectedId = useRef<string | null>(null);
  const commandInFlight = useRef(false);
  activeAgentId.current = agentId;

  const loadList = useCallback(async (requestedAgent: string, activeFilters: FollowUpFilters) => {
    setLoadingList(true);
    try {
      const page = await listFollowUps(requestedAgent, activeFilters);
      if (activeAgentId.current === requestedAgent) setItems(page.items);
    } catch (value) {
      if (activeAgentId.current === requestedAgent) {
        setError(errorMessage(value, "No se pudo cargar la cola de seguimientos."));
      }
    } finally {
      if (activeAgentId.current === requestedAgent) setLoadingList(false);
    }
  }, []);

  const loadDetail = useCallback(async (requestedAgent: string, taskId: string) => {
    setLoadingDetail(true);
    try {
      const [nextDetail, eventPage] = await Promise.all([
        getFollowUp(requestedAgent, taskId),
        listFollowUpEvents(requestedAgent, taskId),
      ]);
      if (activeAgentId.current === requestedAgent && selectedId.current === taskId) {
        setDetail(nextDetail);
        setEvents(eventPage.items);
      }
    } catch (value) {
      if (activeAgentId.current === requestedAgent) {
        if (value instanceof ApiError && value.status === 404) {
          selectedId.current = null;
          setDetail(null);
          setEvents([]);
        }
        setError(errorMessage(value, "No se pudo cargar el seguimiento."));
      }
    } finally {
      if (activeAgentId.current === requestedAgent) setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    selectedId.current = null;
    setItems([]);
    setDetail(null);
    setEvents([]);
    setError("");
    if (!agentId) {
      setLoadingList(false);
      return;
    }
    void loadList(agentId, filters);
  }, [agentId, filters, loadList]);

  const open = (item: FollowUpQueueItem) => {
    if (!agentId) return;
    selectedId.current = item.id;
    setDetail({
      ...item,
      conversation_id: null,
      has_retained_source_conversation: false,
      quote_version_id: null,
      scheduled_control_version: null,
      scheduled_automation_version: null,
      scheduled_policy_version: null,
      executed_policy_version: null,
      has_consent_evidence: false,
      has_executed_consent_evidence: false,
      has_chat_message_evidence: false,
      has_outbound_message_evidence: false,
      completed_at: null,
      cancelled_at: null,
    });
    setEvents([]);
    setError("");
    void loadDetail(agentId, item.id);
  };

  const close = () => {
    selectedId.current = null;
    setDetail(null);
    setEvents([]);
  };

  const refresh = useCallback(async () => {
    if (!agentId) return;
    await loadList(agentId, filters);
    if (selectedId.current) await loadDetail(agentId, selectedId.current);
  }, [agentId, filters, loadDetail, loadList]);

  const execute = async (action: () => Promise<unknown>, fallback: string): Promise<boolean> => {
    if (commandInFlight.current) return false;
    commandInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
      return true;
    } catch (value) {
      if (value instanceof ApiError && value.status === 409) {
        setError(
          "El seguimiento cambió mientras lo estabas revisando. Recargamos el estado actual; comprobalo antes de volver a operar.",
        );
        await refresh();
      } else {
        if (value instanceof ApiError && value.status === 404) await refresh();
        setError(errorMessage(value, fallback));
      }
      return false;
    } finally {
      commandInFlight.current = false;
      setBusy(false);
    }
  };

  return {
    items,
    detail,
    events,
    filters,
    loadingList,
    loadingDetail,
    busy,
    error,
    setFilters,
    open,
    close,
    refresh,
    cancel: () => {
      if (!agentId || !detail) return Promise.resolve(false);
      return execute(
        () => cancelFollowUp(agentId, detail.id, detail.state_version),
        "No se pudo cancelar el seguimiento.",
      );
    },
    requeue: () => {
      if (!agentId || !detail) return Promise.resolve(false);
      return execute(
        () => requeueFollowUp(agentId, detail.id, detail.state_version),
        "No se pudo reencolar el seguimiento.",
      );
    },
    resolveReview: (resolution: "requeue" | "cancel") => {
      if (!agentId || !detail) return Promise.resolve(false);
      return execute(
        () => resolveFollowUpReview(agentId, detail.id, detail.state_version, resolution),
        "No se pudo resolver la revisión.",
      );
    },
  };
}

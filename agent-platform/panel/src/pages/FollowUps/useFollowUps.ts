import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import type { CrmListOptions } from "../../crm/operations";
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

export function useFollowUps(agentId = "", { global = false, offset = 0 }: CrmListOptions = {}) {
  const ownerAgentId = useRef(agentId);
  const [total, setTotal] = useState(0);
  const listGeneration = useRef(0);
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

  const loadList = useCallback(
    async (requestedAgent: string, activeFilters: FollowUpFilters) => {
      const generation = ++listGeneration.current;
      setLoadingList(true);
      try {
        const page = await listFollowUps(requestedAgent, activeFilters, { global, offset });
        if (generation === listGeneration.current && activeAgentId.current === requestedAgent) {
          setItems(page.items);
          setTotal(page.total);
        }
      } catch (value) {
        if (generation === listGeneration.current && activeAgentId.current === requestedAgent) {
          setError(errorMessage(value, "No se pudo cargar la cola de seguimientos."));
        }
      } finally {
        if (generation === listGeneration.current && activeAgentId.current === requestedAgent)
          setLoadingList(false);
      }
    },
    [global, offset],
  );

  const loadDetail = useCallback(async (requestedAgent: string, taskId: string) => {
    setLoadingDetail(true);
    try {
      const [nextDetail, eventPage] = await Promise.all([
        getFollowUp(requestedAgent, taskId),
        listFollowUpEvents(requestedAgent, taskId),
      ]);
      if (ownerAgentId.current === requestedAgent && selectedId.current === taskId) {
        setDetail((current) => ({ ...current, ...nextDetail }));
        setEvents(eventPage.items);
      }
    } catch (value) {
      if (ownerAgentId.current === requestedAgent) {
        if (value instanceof ApiError && value.status === 404) {
          selectedId.current = null;
          setDetail(null);
          setEvents([]);
        }
        setError(errorMessage(value, "No se pudo cargar el seguimiento."));
      }
    } finally {
      if (ownerAgentId.current === requestedAgent) setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    selectedId.current = null;
    setItems([]);
    setDetail(null);
    setEvents([]);
    setError("");
    if (!agentId && !global) {
      setLoadingList(false);
      return;
    }
    void loadList(agentId, filters);
  }, [agentId, filters, loadList, global]);

  const open = (item: FollowUpQueueItem) => {
    const owner = item.owner_agent_id ?? (global ? "" : agentId);
    if (!owner) return;
    ownerAgentId.current = owner;
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
    void loadDetail(owner, item.id);
  };

  const close = () => {
    selectedId.current = null;
    setDetail(null);
    setEvents([]);
  };

  const refresh = useCallback(async () => {
    if (!agentId && !global) return;
    await loadList(agentId, filters);
    if (selectedId.current) await loadDetail(ownerAgentId.current, selectedId.current);
  }, [agentId, filters, loadDetail, loadList, global]);

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
    total,
    ownerAgentId: ownerAgentId.current,
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
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return execute(
        () => cancelFollowUp(ownerAgentId.current, detail.id, detail.state_version),
        "No se pudo cancelar el seguimiento.",
      );
    },
    requeue: () => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return execute(
        () => requeueFollowUp(ownerAgentId.current, detail.id, detail.state_version),
        "No se pudo reencolar el seguimiento.",
      );
    },
    resolveReview: (resolution: "requeue" | "cancel") => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return execute(
        () =>
          resolveFollowUpReview(ownerAgentId.current, detail.id, detail.state_version, resolution),
        "No se pudo resolver la revisión.",
      );
    },
  };
}

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import {
  commandInboundJob,
  createCommandIntent,
  getInboundJob,
  getInboundJobTimeline,
  listInboundJobs,
} from "./api";
import type {
  CommandIntent,
  InboundJobAction,
  InboundJobDetail,
  InboundJobEvent,
  InboundJobFilters,
  InboundJobSummary,
} from "./types";

const EMPTY_FILTERS: InboundJobFilters = { status: "" };

function message(value: unknown, fallback: string): string {
  return value instanceof Error ? value.message : fallback;
}

export function useInboundJobs(agentId?: string) {
  const [items, setItems] = useState<InboundJobSummary[]>([]);
  const [detail, setDetail] = useState<InboundJobDetail | null>(null);
  const [events, setEvents] = useState<InboundJobEvent[]>([]);
  const [filters, setFilters] = useState<InboundJobFilters>(EMPTY_FILTERS);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeAgentId = useRef(agentId);
  const selectedId = useRef<string | null>(null);
  const commandInFlight = useRef(false);
  const pendingIntents = useRef(new Map<string, CommandIntent>());
  activeAgentId.current = agentId;

  const loadList = useCallback(async (requestedAgent: string, activeFilters: InboundJobFilters) => {
    setLoadingList(true);
    try {
      const page = await listInboundJobs(requestedAgent, activeFilters);
      if (activeAgentId.current === requestedAgent) setItems(page.items);
    } catch (value) {
      if (activeAgentId.current === requestedAgent) {
        setError(message(value, "No se pudo cargar la cola de ingresos externos."));
      }
    } finally {
      if (activeAgentId.current === requestedAgent) setLoadingList(false);
    }
  }, []);

  const loadDetail = useCallback(async (requestedAgent: string, jobId: string) => {
    setLoadingDetail(true);
    try {
      const [nextDetail, timeline] = await Promise.all([
        getInboundJob(requestedAgent, jobId),
        getInboundJobTimeline(requestedAgent, jobId),
      ]);
      if (activeAgentId.current === requestedAgent && selectedId.current === jobId) {
        setDetail(nextDetail);
        setEvents(timeline.items);
      }
    } catch (value) {
      if (activeAgentId.current === requestedAgent) {
        if (value instanceof ApiError && value.status === 404) {
          selectedId.current = null;
          setDetail(null);
          setEvents([]);
        }
        setError(message(value, "No se pudo cargar el ingreso externo."));
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
    pendingIntents.current.clear();
    if (!agentId) {
      setLoadingList(false);
      return;
    }
    void loadList(agentId, filters);
  }, [agentId, filters, loadList]);

  const open = (item: InboundJobSummary) => {
    if (!agentId) return;
    selectedId.current = item.id;
    setDetail({
      ...item,
      conversation_control_version: null,
      conversation_automation_version: null,
      legacy_payload_quarantined: false,
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

  const execute = async (action: InboundJobAction): Promise<boolean> => {
    if (!agentId || !detail || commandInFlight.current) return false;
    commandInFlight.current = true;
    setBusy(true);
    setError("");
    const signature = `${agentId}:${detail.id}:${detail.state_version}:${action}`;
    const intent = pendingIntents.current.get(signature) ?? createCommandIntent(action);
    pendingIntents.current.set(signature, intent);
    try {
      await commandInboundJob(agentId, detail.id, action, detail.state_version, intent);
      pendingIntents.current.delete(signature);
      await refresh();
      return true;
    } catch (value) {
      const hasDefinitiveResponse = value instanceof ApiError && value.status < 500;
      if (hasDefinitiveResponse) pendingIntents.current.delete(signature);
      if (value instanceof ApiError && value.status === 409) {
        setError(
          "El ingreso cambió mientras lo revisabas. Recargamos el estado actual; comprobalo antes de volver a operar.",
        );
      } else if (!hasDefinitiveResponse) {
        setError(
          "No pudimos confirmar el resultado. Revisamos el estado y, si repetís esta misma acción, conservaremos su clave para evitar duplicarla.",
        );
      } else {
        setError(message(value, "No se pudo resolver el ingreso externo."));
      }
      await refresh();
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
    requeue: () => execute("requeue"),
    cancel: () => execute("cancel"),
    acknowledge: () => execute("acknowledge"),
  };
}

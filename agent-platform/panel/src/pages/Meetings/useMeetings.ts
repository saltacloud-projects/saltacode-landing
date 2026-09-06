import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import {
  cancelMeeting,
  createMeeting,
  getMeeting,
  listMeetings,
  markAwaitingResponse,
  proposeSlots,
  requestReschedule,
  requireReview,
  scheduleManually,
  selectSlot,
} from "./api";
import type {
  MeetingDetail,
  MeetingFilters,
  MeetingMutation,
  MeetingSummary,
  SlotProposalInput,
} from "./types";

const EMPTY_FILTERS: MeetingFilters = { status: "", opportunityId: "" };

function errorMessage(value: unknown, fallback: string): string {
  return value instanceof Error ? value.message : fallback;
}

export function useMeetings(agentId?: string, initialOpportunityId = "") {
  const [items, setItems] = useState<MeetingSummary[]>([]);
  const [detail, setDetail] = useState<MeetingDetail | null>(null);
  const [filters, setFilters] = useState<MeetingFilters>({
    ...EMPTY_FILTERS,
    opportunityId: initialOpportunityId,
  });
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeAgentId = useRef(agentId);
  const selectedId = useRef<string | null>(null);
  const commandInFlight = useRef(false);
  activeAgentId.current = agentId;

  const loadList = useCallback(async (requestedAgent: string, activeFilters: MeetingFilters) => {
    setLoadingList(true);
    try {
      const page = await listMeetings(requestedAgent, activeFilters);
      if (activeAgentId.current === requestedAgent) setItems(page.items);
    } catch (value) {
      if (activeAgentId.current === requestedAgent) {
        setError(errorMessage(value, "No se pudieron cargar las reuniones."));
      }
    } finally {
      if (activeAgentId.current === requestedAgent) setLoadingList(false);
    }
  }, []);

  const loadDetail = useCallback(async (requestedAgent: string, meetingId: string) => {
    setLoadingDetail(true);
    try {
      const next = await getMeeting(requestedAgent, meetingId);
      if (activeAgentId.current === requestedAgent && selectedId.current === meetingId) {
        setDetail(next);
      }
    } catch (value) {
      if (activeAgentId.current === requestedAgent) {
        if (value instanceof ApiError && value.status === 404) setDetail(null);
        setError(errorMessage(value, "No se pudo cargar la reunión."));
      }
    } finally {
      if (activeAgentId.current === requestedAgent) setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    setItems([]);
    setDetail(null);
    selectedId.current = null;
    setError("");
    if (!agentId) {
      setLoadingList(false);
      return;
    }
    void loadList(agentId, filters);
  }, [agentId, filters, loadList]);

  const open = (item: MeetingSummary) => {
    if (!agentId) return;
    setError("");
    selectedId.current = item.id;
    setDetail({ ...item, slots: [], events: [] });
    void loadDetail(agentId, item.id);
  };

  const refresh = useCallback(async () => {
    if (!agentId) return;
    await loadList(agentId, filters);
    const meetingId = selectedId.current;
    if (meetingId) await loadDetail(agentId, meetingId);
  }, [agentId, filters, loadDetail, loadList]);

  const execute = async (
    action: () => Promise<MeetingMutation>,
    fallback: string,
  ): Promise<MeetingMutation | null> => {
    if (commandInFlight.current) return null;
    commandInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await action();
      await loadList(agentId ?? "", filters);
      selectedId.current = result.id;
      await loadDetail(agentId ?? "", result.id);
      return result;
    } catch (value) {
      if (value instanceof ApiError && value.status === 409) {
        setError(
          "La reunión cambió mientras la estabas editando. Recargamos el estado actual; revisalo antes de volver a intentar.",
        );
        await refresh();
      } else {
        if (value instanceof ApiError && value.status === 404) await refresh();
        setError(errorMessage(value, fallback));
      }
      return null;
    } finally {
      commandInFlight.current = false;
      setBusy(false);
    }
  };

  return {
    items,
    detail,
    filters,
    loadingList,
    loadingDetail,
    busy,
    error,
    setFilters,
    open,
    close: () => {
      selectedId.current = null;
      setDetail(null);
    },
    refresh,
    create: (input: { opportunity_id: string; conversation_id?: string }) => {
      if (!agentId) return Promise.resolve(null);
      return execute(() => createMeeting(agentId, input), "No se pudo crear la reunión.");
    },
    proposeSlots: (slots: SlotProposalInput[], reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(null);
      return execute(
        () => proposeSlots(agentId, detail.id, detail.state_version, slots, reason),
        "No se pudieron proponer los horarios.",
      );
    },
    markAwaiting: (reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(null);
      return execute(
        () => markAwaitingResponse(agentId, detail.id, detail.state_version, reason),
        "No se pudo marcar la espera de respuesta.",
      );
    },
    selectSlot: (slotId: string, reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(null);
      return execute(
        () => selectSlot(agentId, detail.id, detail.state_version, slotId, reason),
        "No se pudo seleccionar el horario.",
      );
    },
    scheduleManually: (input: {
      expected_opportunity_version: number;
      slot_id: string;
      evidence_type: string;
      evidence_reference: string;
      reason?: string;
    }) => {
      if (!agentId || !detail) return Promise.resolve(null);
      return execute(
        () =>
          scheduleManually(agentId, detail.id, {
            ...input,
            expected_version: detail.state_version,
          }),
        "No se pudo confirmar manualmente la reunión.",
      );
    },
    requestReschedule: (reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(null);
      return execute(
        () => requestReschedule(agentId, detail.id, detail.state_version, reason),
        "No se pudo solicitar la reprogramación.",
      );
    },
    cancel: (reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(null);
      return execute(
        () => cancelMeeting(agentId, detail.id, detail.state_version, reason),
        "No se pudo cancelar la reunión.",
      );
    },
    requireReview: (reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(null);
      return execute(
        () => requireReview(agentId, detail.id, detail.state_version, reason),
        "No se pudo enviar la reunión a revisión.",
      );
    },
  };
}

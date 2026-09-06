import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import {
  createAuthoritativeQuoteVersion,
  createFollowUp,
  createOpportunity,
  createQuoteRequest,
  getOpportunity,
  linkOpportunityConversation,
  listOpportunities,
  listOpportunityCandidates,
  listOpportunityOperators,
  reassignOpportunity,
  transitionFollowUp,
  transitionOpportunityStage,
} from "./api";
import type {
  CommercialOperator,
  FollowUpKind,
  FollowUpStatus,
  OpportunityCandidate,
  OpportunityDetail,
  OpportunityFilters,
  OpportunityStage,
  OpportunitySummary,
} from "./types";

const EMPTY_FILTERS: OpportunityFilters = { stage: "", owner: "", search: "" };

interface Options {
  agentId?: string;
  adminId: string;
  canManage: boolean;
}

function message(value: unknown, fallback: string): string {
  return value instanceof Error ? value.message : fallback;
}

export function useOpportunities({ agentId, adminId, canManage }: Options) {
  const [items, setItems] = useState<OpportunitySummary[]>([]);
  const [detail, setDetail] = useState<OpportunityDetail | null>(null);
  const [candidates, setCandidates] = useState<OpportunityCandidate[]>([]);
  const [operators, setOperators] = useState<CommercialOperator[]>([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeAgentId = useRef(agentId);
  const selectedId = useRef<string | null>(null);
  activeAgentId.current = agentId;
  selectedId.current = detail?.id ?? null;

  const loadList = useCallback(
    async (requestedAgent: string, activeFilters: OpportunityFilters) => {
      setLoadingList(true);
      try {
        const page = await listOpportunities(requestedAgent, activeFilters, adminId);
        if (activeAgentId.current === requestedAgent) setItems(page.items);
      } catch (value) {
        if (activeAgentId.current === requestedAgent) {
          setError(message(value, "No se pudieron cargar las oportunidades."));
        }
      } finally {
        if (activeAgentId.current === requestedAgent) setLoadingList(false);
      }
    },
    [adminId],
  );

  const loadDetail = useCallback(async (requestedAgent: string, opportunityId: string) => {
    setLoadingDetail(true);
    try {
      const next = await getOpportunity(requestedAgent, opportunityId);
      if (activeAgentId.current === requestedAgent && selectedId.current === opportunityId) {
        setDetail(next);
      }
    } catch (value) {
      if (activeAgentId.current === requestedAgent) {
        if (value instanceof ApiError && value.status === 404) setDetail(null);
        setError(message(value, "No se pudo cargar la oportunidad."));
      }
    } finally {
      if (activeAgentId.current === requestedAgent) setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    setItems([]);
    setDetail(null);
    setCandidates([]);
    setOperators([]);
    setError("");
    if (!agentId) {
      setLoadingList(false);
      return;
    }
    void listOpportunityCandidates(agentId)
      .then((rows) => {
        if (activeAgentId.current === agentId) setCandidates(rows);
      })
      .catch((value) => {
        if (activeAgentId.current === agentId) {
          setError(message(value, "No se pudieron cargar los contactos."));
        }
      });
    if (canManage) {
      void listOpportunityOperators(agentId)
        .then((rows) => {
          if (activeAgentId.current === agentId) setOperators(rows);
        })
        .catch((value) => {
          if (activeAgentId.current === agentId) {
            setError(message(value, "No se pudieron cargar los operadores."));
          }
        });
    }
  }, [agentId, canManage]);

  useEffect(() => {
    if (!agentId) return;
    void loadList(agentId, filters);
  }, [agentId, filters, loadList]);

  const open = (item: OpportunitySummary) => {
    if (!agentId) return;
    setError("");
    selectedId.current = item.id;
    setDetail({
      ...item,
      available_conversations: [],
      conversations: [],
      stage_events: [],
      ownership_events: [],
      follow_ups: [],
      quote_requests: [],
    });
    void loadDetail(agentId, item.id);
  };

  const refresh = useCallback(async () => {
    if (!agentId) return;
    await loadList(agentId, filters);
    const opportunityId = selectedId.current;
    if (opportunityId) await loadDetail(agentId, opportunityId);
  }, [agentId, filters, loadList, loadDetail]);

  const command = async (action: () => Promise<unknown>, fallback: string): Promise<boolean> => {
    if (busy) return false;
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
      return true;
    } catch (value) {
      if (value instanceof ApiError && (value.status === 404 || value.status === 409)) {
        await refresh();
      }
      setError(message(value, fallback));
      return false;
    } finally {
      setBusy(false);
    }
  };

  return {
    items,
    detail,
    candidates,
    operators,
    filters,
    loadingList,
    loadingDetail,
    busy,
    error,
    setFilters,
    open,
    close: () => setDetail(null),
    refresh,
    create: (input: Parameters<typeof createOpportunity>[1]) => {
      if (!agentId) return Promise.resolve(false);
      return command(() => createOpportunity(agentId, input), "No se pudo crear la oportunidad.");
    },
    transitionStage: (stage: OpportunityStage, reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(false);
      return command(
        () => transitionOpportunityStage(agentId, detail.id, stage, detail.control_version, reason),
        "No se pudo cambiar la etapa.",
      );
    },
    reassign: (assignedAgentId: string, assignedOperatorId?: string, reason?: string) => {
      if (!agentId || !detail) return Promise.resolve(false);
      return command(
        () =>
          reassignOpportunity(agentId, detail.id, {
            assigned_agent_id: assignedAgentId,
            assigned_operator_id: assignedOperatorId,
            expected_version: detail.control_version,
            reason,
          }),
        "No se pudo reasignar la oportunidad.",
      );
    },
    linkConversation: (conversationId: string) => {
      if (!agentId || !detail) return Promise.resolve(false);
      return command(
        () => linkOpportunityConversation(agentId, detail.id, conversationId),
        "No se pudo vincular la conversación.",
      );
    },
    createFollowUp: (input: {
      contact_point_id: string;
      kind: FollowUpKind;
      due_at: string;
      note?: string;
    }) => {
      if (!agentId || !detail) return Promise.resolve(false);
      return command(
        () => createFollowUp(agentId, detail.id, input),
        "No se pudo programar el seguimiento.",
      );
    },
    transitionFollowUp: (taskId: string, status: FollowUpStatus, version: number) => {
      if (!agentId || !detail) return Promise.resolve(false);
      return command(
        () => transitionFollowUp(agentId, detail.id, taskId, status, version),
        "No se pudo actualizar el seguimiento.",
      );
    },
    requestQuote: (input: Parameters<typeof createQuoteRequest>[2]) => {
      if (!agentId || !detail) return Promise.resolve(false);
      return command(
        () => createQuoteRequest(agentId, detail.id, input),
        "No se pudo registrar la solicitud de presupuesto.",
      );
    },
    registerQuoteVersion: (
      requestId: string,
      input: Parameters<typeof createAuthoritativeQuoteVersion>[3],
    ) => {
      if (!agentId || !detail) return Promise.resolve(false);
      return command(
        () => createAuthoritativeQuoteVersion(agentId, detail.id, requestId, input),
        "No se pudo registrar la evidencia autoritativa.",
      );
    },
  };
}

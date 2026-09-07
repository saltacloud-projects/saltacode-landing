import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { PERMISSIONS } from "../../auth/permissions";
import type { CrmListOptions } from "../../crm/operations";
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

interface Options extends CrmListOptions {
  agentId?: string;
  adminId: string;
  canManage: boolean;
}

function message(value: unknown, fallback: string): string {
  return value instanceof Error ? value.message : fallback;
}

export function useOpportunities({
  agentId = "",
  adminId,
  canManage,
  global = false,
  offset = 0,
}: Options) {
  const ownerAgentId = useRef(agentId);
  const [total, setTotal] = useState(0);
  const listGeneration = useRef(0);
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
      const generation = ++listGeneration.current;
      setLoadingList(true);
      try {
        const page = await listOpportunities(requestedAgent, activeFilters, adminId, {
          global,
          offset,
        });
        if (generation === listGeneration.current && activeAgentId.current === requestedAgent) {
          setItems(page.items);
          setTotal(page.total);
        }
      } catch (value) {
        if (generation === listGeneration.current && activeAgentId.current === requestedAgent) {
          setError(message(value, "No se pudieron cargar las oportunidades."));
        }
      } finally {
        if (generation === listGeneration.current && activeAgentId.current === requestedAgent)
          setLoadingList(false);
      }
    },
    [adminId, global, offset],
  );

  const loadDetail = useCallback(async (requestedAgent: string, opportunityId: string) => {
    setLoadingDetail(true);
    try {
      const next = await getOpportunity(requestedAgent, opportunityId);
      if (ownerAgentId.current === requestedAgent && selectedId.current === opportunityId) {
        setDetail((current) => ({ ...current, ...next }));
      }
    } catch (value) {
      if (ownerAgentId.current === requestedAgent) {
        if (value instanceof ApiError && value.status === 404) setDetail(null);
        setError(message(value, "No se pudo cargar la oportunidad."));
      }
    } finally {
      if (ownerAgentId.current === requestedAgent) setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    setItems([]);
    setDetail(null);
    setCandidates([]);
    setOperators([]);
    setError("");
    if (!agentId) {
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
    if (!agentId && !global) return;
    void loadList(agentId, filters);
  }, [agentId, filters, loadList, global]);

  const open = (item: OpportunitySummary) => {
    const owner = item.owner_agent_id ?? (global ? "" : agentId);
    if (!owner) return;
    ownerAgentId.current = owner;
    if (canManage && (!global || item.capabilities?.includes(PERMISSIONS.OPPORTUNITIES_MANAGE)))
      void listOpportunityOperators(owner)
        .then((rows) => {
          if (ownerAgentId.current === owner) setOperators(rows);
        })
        .catch(() => setOperators([]));
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
    void loadDetail(owner, item.id);
  };

  const refresh = useCallback(async () => {
    if (!agentId && !global) return;
    await loadList(agentId, filters);
    const opportunityId = selectedId.current;
    if (opportunityId) await loadDetail(ownerAgentId.current, opportunityId);
  }, [agentId, filters, loadList, loadDetail, global]);

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
    total,
    ownerAgentId: ownerAgentId.current,
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
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return command(
        () =>
          transitionOpportunityStage(
            ownerAgentId.current,
            detail.id,
            stage,
            detail.control_version,
            reason,
          ),
        "No se pudo cambiar la etapa.",
      );
    },
    reassign: (assignedAgentId: string, assignedOperatorId?: string, reason?: string) => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return command(
        () =>
          reassignOpportunity(ownerAgentId.current, detail.id, {
            assigned_agent_id: assignedAgentId,
            assigned_operator_id: assignedOperatorId,
            expected_version: detail.control_version,
            reason,
          }),
        "No se pudo reasignar la oportunidad.",
      );
    },
    linkConversation: (conversationId: string) => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return command(
        () => linkOpportunityConversation(ownerAgentId.current, detail.id, conversationId),
        "No se pudo vincular la conversación.",
      );
    },
    createFollowUp: (input: {
      contact_point_id: string;
      kind: FollowUpKind;
      due_at: string;
      note?: string;
    }) => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return command(
        () => createFollowUp(ownerAgentId.current, detail.id, input),
        "No se pudo programar el seguimiento.",
      );
    },
    transitionFollowUp: (taskId: string, status: FollowUpStatus, version: number) => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return command(
        () => transitionFollowUp(ownerAgentId.current, detail.id, taskId, status, version),
        "No se pudo actualizar el seguimiento.",
      );
    },
    requestQuote: (input: Parameters<typeof createQuoteRequest>[2]) => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return command(
        () => createQuoteRequest(ownerAgentId.current, detail.id, input),
        "No se pudo registrar la solicitud de presupuesto.",
      );
    },
    registerQuoteVersion: (
      requestId: string,
      input: Parameters<typeof createAuthoritativeQuoteVersion>[3],
    ) => {
      if (!ownerAgentId.current || !detail) return Promise.resolve(false);
      return command(
        () => createAuthoritativeQuoteVersion(ownerAgentId.current, detail.id, requestId, input),
        "No se pudo registrar la evidencia autoritativa.",
      );
    },
  };
}

import { useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { useAgentWorkspace } from "../agents/AgentWorkspaceContext";
import { api } from "../api/client";
import type { AdminUser } from "../auth/AuthContext";
import { hasPermission } from "../auth/permissions";

export interface CrmOwnership {
  owner_agent_id?: string;
  owner_agent_name?: string;
  capabilities?: string[];
}

export interface CrmAgent {
  is_active: boolean;
  id: string;
  name: string;
  capabilities: string[];
}

export interface CrmListOptions {
  global?: boolean;
  offset?: number;
}

export const CRM_PAGE_SIZE = 50;

export function listPath(
  resource: string,
  agentId: string,
  query: URLSearchParams,
  options: CrmListOptions = {},
): string {
  query.set("limit", String(CRM_PAGE_SIZE));
  query.set("offset", String(options.offset ?? 0));
  if (options.global) {
    if (agentId) query.set("agent_id", agentId);
    return `/crm/${resource}?${query}`;
  }
  return `/agents/${encodeURIComponent(agentId)}/${resource}/?${query}`;
}

export function canOperateItem(
  global: boolean,
  item: CrmOwnership | null | undefined,
  user: AdminUser | null,
  permission: string,
): boolean {
  return (
    hasPermission(user, permission) &&
    (!global || Boolean(item?.capabilities?.includes(permission)))
  );
}

export function useCrmScope(resource: string) {
  const { selectedAgent } = useAgentWorkspace();
  const { pathname } = useLocation();
  const [params, setParams] = useSearchParams();
  const global = !pathname.startsWith("/agents/");
  const agentId = global ? (params.get("agent_id") ?? "") : (selectedAgent?.id ?? "");
  const [agents, setAgents] = useState<CrmAgent[]>([]);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    if (!global) return;
    let current = true;
    setError("");
    void api<CrmAgent[]>(`/crm/${resource}/agents`)
      .then((rows) => {
        if (current) setAgents(rows);
      })
      .catch((cause: unknown) => {
        if (current)
          setError(
            cause instanceof Error
              ? cause.message
              : "No se pudieron cargar los agentes autorizados.",
          );
      });
    return () => {
      current = false;
    };
  }, [global, resource]);
  return {
    global,
    agentId,
    agents,
    error,
    offset,
    setOffset,
    selectedAgent: global ? agents.find((agent) => agent.id === agentId) : selectedAgent,
    setAgentId: (id: string) => {
      const next = new URLSearchParams(params);
      if (id) next.set("agent_id", id);
      else next.delete("agent_id");
      setOffset(0);
      setParams(next);
    },
  };
}

export function CrmScopeFilter({
  scope,
  label,
}: {
  scope: ReturnType<typeof useCrmScope>;
  label: string;
}) {
  if (!scope.global) return null;
  return (
    <div className="mb-4">
      <label className="block max-w-sm text-xs text-[var(--text-muted)]">
        {label}
        <select
          className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)]"
          value={scope.agentId}
          onChange={(event) => scope.setAgentId(event.target.value)}
        >
          <option value="">Todos los autorizados</option>
          {scope.agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </label>
      {scope.error && (
        <p role="alert" className="mt-2 text-sm text-[var(--error)]">
          {scope.error}
        </p>
      )}
    </div>
  );
}

export function CrmPagination({
  offset,
  total,
  loading,
  onChange,
  singlePageLabel,
}: {
  offset: number;
  total: number;
  loading: boolean;
  onChange: (offset: number) => void;
  singlePageLabel?: string;
}) {
  const lastOffset = Math.floor(Math.max(0, total - 1) / CRM_PAGE_SIZE) * CRM_PAGE_SIZE;
  const correctingOffset = offset > lastOffset;
  useEffect(() => {
    if (!loading && correctingOffset) onChange(lastOffset);
  }, [loading, correctingOffset, lastOffset, onChange]);
  const singlePage = singlePageLabel !== undefined && total <= CRM_PAGE_SIZE && !correctingOffset;
  return (
    <nav
      aria-label="Paginación de resultados"
      aria-busy={loading || correctingOffset}
      className="my-4 flex flex-wrap items-center justify-between gap-3 text-sm"
    >
      <div aria-live="polite">
        <span>
          {correctingOffset
            ? "Actualizando página…"
            : total === 0
              ? "Sin resultados"
              : singlePage
                ? singlePageLabel
                : `${offset + 1}–${Math.min(offset + CRM_PAGE_SIZE, total)} de ${total}`}
        </span>
        {singlePage && total > 0 && (
          <span className="mt-1 block text-xs text-[var(--text-secondary)]">
            Todas en esta página
          </span>
        )}
      </div>
      {!singlePage && (
        <div className="flex gap-2">
          <button
            type="button"
            disabled={loading || correctingOffset || offset === 0}
            onClick={() => onChange(Math.max(0, offset - CRM_PAGE_SIZE))}
            className="rounded border border-[var(--border-color)] px-3 py-2 disabled:opacity-40"
          >
            Anterior
          </button>
          <button
            type="button"
            disabled={loading || correctingOffset || offset + CRM_PAGE_SIZE >= total}
            onClick={() => onChange(offset + CRM_PAGE_SIZE)}
            className="rounded border border-[var(--border-color)] px-3 py-2 disabled:opacity-40"
          >
            Siguiente
          </button>
        </div>
      )}
    </nav>
  );
}

export function CrmOwnerLabel({
  item,
  label = "Responsable",
}: {
  item: CrmOwnership;
  label?: string;
}) {
  return item.owner_agent_name ? (
    <span className="mt-1 block text-xs text-[var(--text-muted)]">
      {label}: {item.owner_agent_name}
    </span>
  ) : null;
}

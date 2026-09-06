import { ListChecks, RefreshCw } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { FollowUpDetail } from "./FollowUpDetail";
import { FollowUpList } from "./FollowUpList";
import { KIND_LABELS, STATUS_LABELS } from "./presentation";
import type { FollowUpFilters, FollowUpKind, FollowUpStatus } from "./types";
import { useFollowUps } from "./useFollowUps";

const STATUSES: FollowUpStatus[] = [
  "scheduled",
  "dispatch_queued",
  "in_progress",
  "completed",
  "review_required",
  "cancelled",
];
const KINDS: FollowUpKind[] = ["commercial_follow_up", "meeting_coordination", "proposal_reminder"];
const SELECT =
  "mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";

export default function FollowUpsPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const workspace = useFollowUps(selectedAgent?.id);
  const canManage = hasPermission(user, PERMISSIONS.FOLLOW_UPS_MANAGE);
  const canReview = hasPermission(user, PERMISSIONS.FOLLOW_UPS_REVIEW);

  return (
    <div className="mx-auto max-w-[1600px]">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <ListChecks size={23} className="text-[var(--accent)]" aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">Seguimientos de {selectedAgent?.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            Cola durable, revisión humana y evidencia operativa sin exponer datos de contacto.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void workspace.refresh()}
          className="ml-auto inline-flex items-center gap-2 rounded border border-[var(--border-color)] px-3 py-2 text-sm"
        >
          <RefreshCw size={16} aria-hidden="true" />
          <span className="hidden sm:inline">Actualizar</span>
        </button>
      </header>

      <p
        role="note"
        className="mb-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 text-sm text-[var(--text-secondary)]"
      >
        La automatización es responsable de ejecutar y completar tareas. El operador sólo puede
        cancelar trabajo todavía seguro o resolver una revisión; nunca fuerza estados internos.
      </p>

      <FollowUpFiltersForm filters={workspace.filters} onChange={workspace.setFilters} />

      {workspace.error && (
        <p
          role="alert"
          className="mb-4 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]"
        >
          {workspace.error}
        </p>
      )}

      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(17rem,0.75fr)_minmax(0,2fr)]">
        <FollowUpList
          items={workspace.items}
          selectedId={workspace.detail?.id}
          loading={workspace.loadingList}
          hiddenOnMobile={Boolean(workspace.detail)}
          onSelect={workspace.open}
        />
        <FollowUpDetail
          agentId={selectedAgent?.id ?? ""}
          detail={workspace.detail}
          events={workspace.events}
          loading={workspace.loadingDetail}
          busy={workspace.busy}
          canManage={canManage}
          canReview={canReview}
          onBack={workspace.close}
          onCancel={workspace.cancel}
          onRequeue={workspace.requeue}
          onResolveReview={workspace.resolveReview}
        />
      </div>
    </div>
  );
}

function FollowUpFiltersForm({
  filters,
  onChange,
}: {
  filters: FollowUpFilters;
  onChange: (filters: FollowUpFilters) => void;
}) {
  return (
    <form
      aria-label="Filtros de seguimientos"
      className="mb-4 grid gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 sm:grid-cols-2"
      onSubmit={(event) => event.preventDefault()}
    >
      <label className="text-xs text-[var(--text-muted)]">
        Estado
        <select
          value={filters.status}
          onChange={(event) =>
            onChange({ ...filters, status: event.target.value as FollowUpFilters["status"] })
          }
          className={SELECT}
        >
          <option value="">Todos</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        Tipo
        <select
          value={filters.kind}
          onChange={(event) =>
            onChange({ ...filters, kind: event.target.value as FollowUpFilters["kind"] })
          }
          className={SELECT}
        >
          <option value="">Todos</option>
          {KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {KIND_LABELS[kind]}
            </option>
          ))}
        </select>
      </label>
    </form>
  );
}

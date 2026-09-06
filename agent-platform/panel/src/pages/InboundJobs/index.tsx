import { RefreshCw, Webhook } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { InboundJobDetail } from "./InboundJobDetail";
import { InboundJobList } from "./InboundJobList";
import { STATUS_LABELS } from "./presentation";
import type { InboundJobFilters, InboundJobStatus } from "./types";
import { useInboundJobs } from "./useInboundJobs";

const STATUSES: InboundJobStatus[] = [
  "queued",
  "processing",
  "completed",
  "routed_to_human",
  "ignored",
  "review_required",
  "cancelled",
];

export default function InboundJobsPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const workspace = useInboundJobs(selectedAgent?.id);
  const canReview = hasPermission(user, PERMISSIONS.INBOUND_REVIEW);

  return (
    <div className="mx-auto max-w-[1600px]">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <Webhook size={23} className="text-[var(--accent)]" aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">Ingresos externos de {selectedAgent?.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            Supervisión segura del ingreso multicanal antes de su procesamiento interno.
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
        El panel muestra estado y trazabilidad mínima. El contenido recibido, los contactos y los
        identificadores externos permanecen protegidos.
      </p>

      <StatusFilter filters={workspace.filters} onChange={workspace.setFilters} />

      {workspace.error && (
        <p
          role="alert"
          className="mb-4 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]"
        >
          {workspace.error}
        </p>
      )}

      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(17rem,0.75fr)_minmax(0,2fr)]">
        <InboundJobList
          items={workspace.items}
          selectedId={workspace.detail?.id}
          loading={workspace.loadingList}
          hiddenOnMobile={Boolean(workspace.detail)}
          onSelect={workspace.open}
        />
        <InboundJobDetail
          detail={workspace.detail}
          events={workspace.events}
          loading={workspace.loadingDetail}
          busy={workspace.busy}
          canReview={canReview}
          onBack={workspace.close}
          onRequeue={workspace.requeue}
          onCancel={workspace.cancel}
          onAcknowledge={workspace.acknowledge}
        />
      </div>
    </div>
  );
}

function StatusFilter({
  filters,
  onChange,
}: {
  filters: InboundJobFilters;
  onChange: (filters: InboundJobFilters) => void;
}) {
  return (
    <form
      aria-label="Filtros de ingresos externos"
      className="mb-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
      onSubmit={(event) => event.preventDefault()}
    >
      <label className="block max-w-sm text-xs text-[var(--text-muted)]">
        Estado
        <select
          value={filters.status}
          onChange={(event) =>
            onChange({ status: event.target.value as InboundJobFilters["status"] })
          }
          className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
        >
          <option value="">Todos</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </select>
      </label>
    </form>
  );
}

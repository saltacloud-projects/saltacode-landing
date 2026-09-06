import { CalendarDays, Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { MeetingDetail } from "./MeetingDetail";
import { MeetingList } from "./MeetingList";
import { STATUS_LABELS } from "./presentation";
import type { MeetingFilters, MeetingStatus } from "./types";
import { useMeetings } from "./useMeetings";

const FILTERABLE_STATUSES: Exclude<MeetingStatus, "calendar_pending">[] = [
  "requested",
  "slots_proposed",
  "awaiting_response",
  "slot_selected",
  "scheduled",
  "reschedule_requested",
  "review_required",
  "cancelled",
];
const INPUT =
  "mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";
const UUID_PATTERN = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";

export default function MeetingsPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedOpportunityId = searchParams.get("opportunity_id") ?? "";
  const [creating, setCreating] = useState(Boolean(requestedOpportunityId));
  const workspace = useMeetings(selectedAgent?.id, requestedOpportunityId);
  const canManage = hasPermission(user, PERMISSIONS.MEETINGS_MANAGE);

  useEffect(() => {
    if (!requestedOpportunityId) return;
    workspace.setFilters((current) => ({ ...current, opportunityId: requestedOpportunityId }));
    setCreating(true);
  }, [requestedOpportunityId, workspace.setFilters]);

  return (
    <div className="mx-auto max-w-[1600px]">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <CalendarDays size={23} className="text-[var(--accent)]" aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">Reuniones de {selectedAgent?.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            Coordinación auditable de horarios vinculada a oportunidades.
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => void workspace.refresh()}
            className="inline-flex items-center gap-2 rounded border border-[var(--border-color)] px-3 py-2 text-sm"
          >
            <RefreshCw size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Actualizar</span>
          </button>
          {canManage && (
            <button
              type="button"
              onClick={() => setCreating((value) => !value)}
              className="inline-flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white"
            >
              <Plus size={16} aria-hidden="true" /> Nueva
            </button>
          )}
        </div>
      </header>

      <p
        role="note"
        className="mb-4 rounded-lg border border-[var(--warning)]/35 bg-[var(--warning)]/5 p-3 text-sm text-[var(--text-secondary)]"
      >
        <strong>Calendario externo no configurado.</strong> Por ahora las confirmaciones son
        manuales y requieren evidencia. El panel no promete crear eventos ni enviar invitaciones.
      </p>

      {creating && canManage && (
        <CreateMeetingForm
          initialOpportunityId={requestedOpportunityId}
          busy={workspace.busy}
          onCancel={() => {
            setCreating(false);
            if (requestedOpportunityId) setSearchParams({}, { replace: true });
          }}
          onSubmit={async (input) => {
            const result = await workspace.create(input);
            if (result) {
              setCreating(false);
              setSearchParams({}, { replace: true });
            }
          }}
        />
      )}

      <MeetingFiltersForm filters={workspace.filters} onChange={workspace.setFilters} />

      {workspace.error && (
        <p
          role="alert"
          className="mb-4 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]"
        >
          {workspace.error}
        </p>
      )}
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(17rem,0.75fr)_minmax(0,2fr)]">
        <MeetingList
          items={workspace.items}
          selectedId={workspace.detail?.id}
          loading={workspace.loadingList}
          hiddenOnMobile={Boolean(workspace.detail)}
          onSelect={workspace.open}
        />
        <MeetingDetail
          agentId={selectedAgent?.id ?? ""}
          meeting={workspace.detail}
          loading={workspace.loadingDetail}
          busy={workspace.busy || workspace.loadingDetail}
          canManage={canManage}
          onBack={workspace.close}
          onProposeSlots={workspace.proposeSlots}
          onMarkAwaiting={workspace.markAwaiting}
          onSelectSlot={workspace.selectSlot}
          onScheduleManually={workspace.scheduleManually}
          onRequestReschedule={workspace.requestReschedule}
          onCancel={workspace.cancel}
          onRequireReview={workspace.requireReview}
        />
      </div>
    </div>
  );
}

function MeetingFiltersForm({
  filters,
  onChange,
}: {
  filters: MeetingFilters;
  onChange: (filters: MeetingFilters) => void;
}) {
  const [opportunityId, setOpportunityId] = useState(filters.opportunityId);

  useEffect(() => setOpportunityId(filters.opportunityId), [filters.opportunityId]);

  return (
    <form
      aria-label="Filtros de reuniones"
      className="mb-4 grid gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        onChange({ ...filters, opportunityId: opportunityId.trim() });
      }}
    >
      <label className="text-xs text-[var(--text-muted)]">
        Estado
        <select
          value={filters.status}
          onChange={(event) =>
            onChange({
              ...filters,
              status: event.target.value as MeetingFilters["status"],
            })
          }
          className={INPUT}
        >
          <option value="">Todos</option>
          {FILTERABLE_STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        ID de oportunidad
        <input
          value={opportunityId}
          placeholder="UUID completo"
          pattern={UUID_PATTERN}
          onChange={(event) => setOpportunityId(event.target.value)}
          className={`${INPUT} font-mono`}
        />
      </label>
      <div className="flex flex-wrap justify-end gap-2 sm:col-span-2">
        {(filters.opportunityId || opportunityId) && (
          <button
            type="button"
            onClick={() => {
              setOpportunityId("");
              onChange({ ...filters, opportunityId: "" });
            }}
            className="rounded border border-[var(--border-color)] px-3 py-2 text-sm"
          >
            Limpiar oportunidad
          </button>
        )}
        <button
          type="submit"
          className="rounded border border-[var(--accent)]/50 px-3 py-2 text-sm text-[var(--accent-hover)]"
        >
          Aplicar filtros
        </button>
      </div>
    </form>
  );
}

function CreateMeetingForm({
  initialOpportunityId,
  busy,
  onCancel,
  onSubmit,
}: {
  initialOpportunityId: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: { opportunity_id: string; conversation_id?: string }) => Promise<void>;
}) {
  const [opportunityId, setOpportunityId] = useState(initialOpportunityId);
  const [conversationId, setConversationId] = useState("");
  return (
    <form
      aria-labelledby="create-meeting-title"
      className="mb-4 rounded-lg border border-[var(--accent)]/35 bg-[var(--bg-card)] p-4"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit({
          opportunity_id: opportunityId.trim(),
          conversation_id: conversationId.trim() || undefined,
        });
      }}
    >
      <h3 id="create-meeting-title" className="font-semibold">
        Nueva reunión
      </h3>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        La oportunidad conserva la propiedad comercial. La conversación es opcional y no cambia su
        agente de ruta.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-[var(--text-muted)]">
          ID de oportunidad
          <input
            required
            pattern={UUID_PATTERN}
            value={opportunityId}
            onChange={(event) => setOpportunityId(event.target.value)}
            className={`${INPUT} font-mono`}
          />
        </label>
        <label className="text-xs text-[var(--text-muted)]">
          ID de conversación opcional
          <input
            pattern={UUID_PATTERN}
            value={conversationId}
            onChange={(event) => setConversationId(event.target.value)}
            className={`${INPUT} font-mono`}
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          className="rounded border border-[var(--border-color)] px-3 py-2 text-sm"
        >
          Cancelar
        </button>
        <button
          type="submit"
          disabled={busy || !opportunityId.trim()}
          className="rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Crear reunión
        </button>
      </div>
    </form>
  );
}

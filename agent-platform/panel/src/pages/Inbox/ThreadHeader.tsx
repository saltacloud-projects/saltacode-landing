import {
  ArrowLeft,
  type Bot,
  CirclePause,
  CirclePlay,
  LockKeyhole,
  SlidersHorizontal,
  UserRoundCheck,
  XCircle,
} from "lucide-react";
import type { ControlTransition, InboxConversation, InboxOperator } from "../../inbox/types";
import { CONTROL_LABELS, controlTone, conversationName } from "./presentation";

interface ThreadHeaderProps {
  controlsOpen?: boolean;
  onToggleControls?: () => void;
  conversation: InboxConversation;
  operators: InboxOperator[];
  currentAdminId: string;
  canManage: boolean;
  busy: boolean;
  reassignTo: string;
  onReassignChange: (value: string) => void;
  onBack: () => void;
  onTransition: (transition: Omit<ControlTransition, "expected_version">) => void;
}

export function ThreadHeader({
  conversation,
  currentAdminId,
  canManage,
  busy,
  onBack,
  onTransition,
  controlsOpen,
  onToggleControls,
}: ThreadHeaderProps) {
  const isClosed = conversation.control_mode === "closed" || conversation.status === "closed";
  const owns =
    conversation.control_mode === "human" && conversation.assigned_operator?.id === currentAdminId;
  return (
    <header className="relative z-10 shrink-0 border-b border-[var(--border-color)] bg-[var(--bg-card)] p-3">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={onBack}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl hover:bg-[var(--bg-hover)] lg:hidden"
          aria-label="Volver a conversaciones"
        >
          <ArrowLeft size={20} />
        </button>
        <span
          aria-hidden="true"
          className="hidden h-10 w-10 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] text-[var(--accent-hover)] sm:grid"
        >
          {conversationName(conversation).slice(0, 1).toLocaleUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold sm:text-base">
            {conversationName(conversation)}
          </h3>
          <p className="mt-1 truncate text-[11px] text-[var(--text-secondary)]">
            <span className="uppercase">{conversation.channel}</span> ·{" "}
            {conversation.automation_agent.name}
          </p>
        </div>
        <button
          type="button"
          aria-label="Detalles y controles"
          aria-expanded={controlsOpen}
          aria-controls="inbox-conversation-controls"
          onClick={onToggleControls}
          className={`inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl px-2 text-xs ${controlsOpen ? "bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] text-[var(--accent-hover)]" : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
        >
          <SlidersHorizontal size={18} />
          <span className="hidden sm:inline">Controles</span>
        </button>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span
          className={`rounded-full border px-2.5 py-1 text-[11px] ${controlTone(conversation.control_mode)}`}
        >
          {CONTROL_LABELS[conversation.control_mode]}
          {owns ? " · A tu cargo" : ""}
        </span>
        {canManage && !isClosed && !owns && (
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              onTransition({
                target_mode: "human",
                assigned_admin_id: currentAdminId,
                reason: "Taken over from operator inbox",
              })
            }
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[var(--accent)] px-3 text-xs font-semibold text-white disabled:opacity-50"
          >
            <UserRoundCheck size={16} />
            Tomar control
          </button>
        )}
      </div>
    </header>
  );
}

export function ConversationControls({
  conversation,
  operators,
  currentAdminId,
  canManage,
  busy,
  reassignTo,
  onReassignChange,
  onTransition,
}: ThreadHeaderProps) {
  const isClosed = conversation.control_mode === "closed" || conversation.status === "closed";
  const isCurrentOwner = conversation.assigned_operator?.id === currentAdminId;
  const canReassign =
    conversation.control_mode === "human" && isCurrentOwner && operators.length > 1;

  return (
    <section
      aria-label="Control de conversación"
      className="border-b border-[var(--border-color)] p-4"
    >
      <h4 className="text-sm font-semibold">Control de conversación</h4>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="min-w-0 rounded border border-[var(--border-color)] bg-[color-mix(in_srgb,var(--bg-secondary)_50%,transparent)] p-2.5">
          <dt className="text-[10px] font-medium uppercase tracking-wide text-[var(--text-secondary)]">
            Canal / agente de routing
          </dt>
          <dd className="mt-1 truncate text-sm font-medium">{conversation.routing_agent.name}</dd>
          <dd className="mt-0.5 truncate text-xs text-[var(--text-secondary)]">
            <span className="uppercase">{conversation.channel}</span> · {conversation.route_key}
          </dd>
        </div>
        <div className="min-w-0 rounded border border-[var(--border-color)] bg-[color-mix(in_srgb,var(--bg-secondary)_50%,transparent)] p-2.5">
          <dt className="text-[10px] font-medium uppercase tracking-wide text-[var(--text-secondary)]">
            Responde automáticamente
          </dt>
          <dd className="mt-1 truncate text-sm font-medium">
            {conversation.automation_agent.name}
          </dd>
          <dd className="mt-0.5 text-xs text-[var(--text-secondary)]">
            Versión {conversation.automation_version}
          </dd>
        </div>
      </dl>

      {conversation.assigned_operator && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <UserRoundCheck size={14} /> Responsable: {conversation.assigned_operator.name}
        </p>
      )}

      {canManage && !isClosed && (
        <div className="mt-3 flex flex-wrap gap-2">
          {conversation.control_mode !== "paused" && (
            <ActionButton
              label="Pausar"
              icon={CirclePause}
              disabled={busy}
              onClick={() =>
                onTransition({ target_mode: "paused", reason: "Paused from operator inbox" })
              }
            />
          )}
          {conversation.control_mode !== "automated" && (
            <ActionButton
              label="Reanudar IA"
              icon={CirclePlay}
              disabled={busy}
              onClick={() =>
                onTransition({ target_mode: "automated", reason: "Resumed from operator inbox" })
              }
            />
          )}
          <ActionButton
            label="Cerrar"
            icon={XCircle}
            disabled={busy}
            danger
            onClick={() => {
              if (window.confirm("¿Cerrar esta conversación? La acción queda auditada.")) {
                onTransition({ target_mode: "closed", reason: "Closed from operator inbox" });
              }
            }}
          />
        </div>
      )}

      {canManage && canReassign && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="min-w-48 flex-1 text-xs text-[var(--text-secondary)]">
            Reasignar a
            <select
              value={reassignTo}
              onChange={(event) => onReassignChange(event.target.value)}
              className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 py-2 text-sm text-[var(--text-primary)]"
            >
              {operators.map((operator) => (
                <option key={operator.id} value={operator.id}>
                  {operator.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || !reassignTo || reassignTo === currentAdminId}
            onClick={() =>
              onTransition({
                target_mode: "human",
                assigned_admin_id: reassignTo,
                reason: "Reassigned from operator inbox",
              })
            }
            className="min-h-11 rounded border border-[var(--border-color)] px-3 py-2 text-sm disabled:opacity-50"
          >
            Reasignar
          </button>
        </div>
      )}

      {!canManage && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <LockKeyhole size={13} /> Vista de solo lectura
        </p>
      )}
    </section>
  );
}

function ActionButton({
  label,
  icon: Icon,
  disabled,
  danger = false,
  onClick,
}: {
  label: string;
  icon: typeof Bot;
  disabled: boolean;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex min-h-11 items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50 ${danger ? "border-[color-mix(in_srgb,var(--error)_40%,transparent)] text-[var(--error)]" : "border-[var(--border-color)]"}`}
    >
      <Icon size={14} /> {label}
    </button>
  );
}

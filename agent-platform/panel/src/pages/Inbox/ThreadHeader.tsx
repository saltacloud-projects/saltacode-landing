import {
  ArrowLeft,
  type Bot,
  CirclePause,
  CirclePlay,
  LockKeyhole,
  UserRoundCheck,
  XCircle,
} from "lucide-react";
import type { ControlTransition, InboxConversation, InboxOperator } from "../../inbox/types";
import { CONTROL_LABELS, controlTone } from "./presentation";

interface ThreadHeaderProps {
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
  operators,
  currentAdminId,
  canManage,
  busy,
  reassignTo,
  onReassignChange,
  onBack,
  onTransition,
}: ThreadHeaderProps) {
  const isClosed = conversation.control_mode === "closed";
  const isCurrentOwner = conversation.assigned_operator?.id === currentAdminId;
  const canReassign =
    conversation.control_mode === "human" && isCurrentOwner && operators.length > 1;

  return (
    <header className="border-b border-[var(--border-color)] p-4">
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded p-1.5 hover:bg-[var(--bg-hover)] lg:hidden"
          aria-label="Volver a conversaciones"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-semibold">
            {conversation.display_name || `Visitante ${conversation.principal_id.slice(0, 8)}`}
          </h3>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            <span className="uppercase">{conversation.channel}</span> · {conversation.route_key}
          </p>
        </div>
        <span
          className={`shrink-0 rounded border px-2 py-1 text-xs ${controlTone(conversation.control_mode)}`}
        >
          {CONTROL_LABELS[conversation.control_mode]}
        </span>
      </div>

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
          {(!isCurrentOwner || conversation.control_mode !== "human") && (
            <ActionButton
              label="Tomar control"
              icon={UserRoundCheck}
              disabled={busy}
              onClick={() =>
                onTransition({
                  target_mode: "human",
                  assigned_admin_id: currentAdminId,
                  reason: "Taken over from operator inbox",
                })
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
          <label className="min-w-48 flex-1 text-xs text-[var(--text-muted)]">
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
            className="rounded border border-[var(--border-color)] px-3 py-2 text-sm disabled:opacity-50"
          >
            Reasignar
          </button>
        </div>
      )}

      {!canManage && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
          <LockKeyhole size={13} /> Vista de solo lectura
        </p>
      )}
    </header>
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
      className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50 ${danger ? "border-[var(--error)]/40 text-[var(--error)]" : "border-[var(--border-color)]"}`}
    >
      <Icon size={14} /> {label}
    </button>
  );
}

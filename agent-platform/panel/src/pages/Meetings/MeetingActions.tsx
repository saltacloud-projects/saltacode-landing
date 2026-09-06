import { Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { slotTime } from "./presentation";
import type { MeetingDetail, SlotProposalInput } from "./types";

const INPUT =
  "mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";

interface SlotDraft extends SlotProposalInput {
  clientId: string;
}

interface Props {
  meeting: MeetingDetail;
  busy: boolean;
  canManage: boolean;
  onProposeSlots: (slots: SlotProposalInput[], reason?: string) => Promise<unknown>;
  onMarkAwaiting: (reason?: string) => Promise<unknown>;
  onSelectSlot: (slotId: string, reason?: string) => Promise<unknown>;
  onScheduleManually: (input: {
    expected_opportunity_version: number;
    slot_id: string;
    evidence_type: string;
    evidence_reference: string;
    reason?: string;
  }) => Promise<unknown>;
  onRequestReschedule: (reason?: string) => Promise<unknown>;
  onCancel: (reason?: string) => Promise<unknown>;
  onRequireReview: (reason?: string) => Promise<unknown>;
}

function localDateTime(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function emptySlot(): SlotDraft {
  const startsAt = new Date(Date.now() + 24 * 60 * 60 * 1_000);
  startsAt.setMinutes(0, 0, 0);
  const endsAt = new Date(startsAt.getTime() + 60 * 60 * 1_000);
  return {
    clientId:
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    starts_at: localDateTime(startsAt),
    ends_at: localDateTime(endsAt),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Argentina/Salta",
  };
}

function ActionButton({ disabled, children }: { disabled: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="mt-3 w-full rounded border border-[var(--accent)]/50 px-3 py-2 text-sm font-medium text-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  );
}

export function MeetingActions({
  meeting,
  busy,
  canManage,
  onProposeSlots,
  onMarkAwaiting,
  onSelectSlot,
  onScheduleManually,
  onRequestReschedule,
  onCancel,
  onRequireReview,
}: Props) {
  const [slots, setSlots] = useState<SlotDraft[]>([emptySlot()]);
  const [proposalReason, setProposalReason] = useState("");
  const [selectedSlotId, setSelectedSlotId] = useState(meeting.selected_slot_id ?? "");
  const [selectionReason, setSelectionReason] = useState("");
  const [evidenceType, setEvidenceType] = useState("operator_confirmation");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [transitionReason, setTransitionReason] = useState("");

  const currentSlots = useMemo(
    () => meeting.slots.filter((slot) => slot.proposal_version === meeting.proposal_version),
    [meeting.proposal_version, meeting.slots],
  );
  const opportunityControlVersion = meeting.opportunity_control_version;
  const canPropose = [
    "requested",
    "slots_proposed",
    "awaiting_response",
    "reschedule_requested",
    "review_required",
  ].includes(meeting.status);
  const canSelect = ["slots_proposed", "awaiting_response"].includes(meeting.status);
  const supportsManualSchedule = [
    "slots_proposed",
    "awaiting_response",
    "slot_selected",
    "reschedule_requested",
    "review_required",
  ].includes(meeting.status);
  const canSchedule = supportsManualSchedule;
  const isTerminal = meeting.status === "cancelled";
  const isProviderOwned = meeting.status === "calendar_pending";

  if (!canManage) {
    return (
      <p className="rounded border border-[var(--border-color)] p-3 text-sm text-[var(--text-muted)]">
        Tu rol permite revisar las reuniones, pero no modificarlas.
      </p>
    );
  }

  if (isProviderOwned) {
    return (
      <p className="rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]">
        Esta reunión quedó en un estado reservado para una integración externa. No hay acciones
        manuales seguras disponibles desde el panel.
      </p>
    );
  }

  return (
    <section aria-labelledby="meeting-actions-title" className="space-y-3">
      <h4 id="meeting-actions-title" className="font-semibold">
        Acciones
      </h4>

      {canPropose && (
        <form
          className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
          onSubmit={(event) => {
            event.preventDefault();
            void onProposeSlots(
              slots.map((slot) => ({
                starts_at: new Date(slot.starts_at).toISOString(),
                ends_at: new Date(slot.ends_at).toISOString(),
                timezone: slot.timezone,
              })),
              proposalReason.trim() || undefined,
            );
          }}
        >
          <h5 className="text-sm font-semibold">Proponer horarios</h5>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            Una nueva propuesta reemplaza las opciones vigentes, pero conserva el historial.
          </p>
          <div className="mt-3 space-y-3">
            {slots.map((slot, index) => (
              <fieldset
                key={slot.clientId}
                className="grid gap-2 rounded border border-[var(--border-color)] p-3 sm:grid-cols-2"
              >
                <legend className="px-1 text-xs font-medium">Opción {index + 1}</legend>
                <label className="text-xs text-[var(--text-muted)]">
                  Inicio
                  <input
                    type="datetime-local"
                    required
                    value={slot.starts_at}
                    onChange={(event) =>
                      setSlots((current) =>
                        current.map((item, position) =>
                          position === index ? { ...item, starts_at: event.target.value } : item,
                        ),
                      )
                    }
                    className={INPUT}
                  />
                </label>
                <label className="text-xs text-[var(--text-muted)]">
                  Fin
                  <input
                    type="datetime-local"
                    required
                    value={slot.ends_at}
                    onChange={(event) =>
                      setSlots((current) =>
                        current.map((item, position) =>
                          position === index ? { ...item, ends_at: event.target.value } : item,
                        ),
                      )
                    }
                    className={INPUT}
                  />
                </label>
                <label className="text-xs text-[var(--text-muted)] sm:col-span-2">
                  Zona horaria del dispositivo
                  <input
                    required
                    readOnly
                    maxLength={64}
                    value={slot.timezone}
                    className={`${INPUT} opacity-75`}
                  />
                </label>
                {slots.length > 1 && (
                  <button
                    type="button"
                    onClick={() =>
                      setSlots((current) => current.filter((_, position) => position !== index))
                    }
                    className="inline-flex items-center gap-1 text-xs text-[var(--error)] sm:col-span-2"
                  >
                    <Trash2 size={14} aria-hidden="true" /> Quitar opción
                  </button>
                )}
              </fieldset>
            ))}
          </div>
          {slots.length < 10 && (
            <button
              type="button"
              onClick={() => setSlots((current) => [...current, emptySlot()])}
              className="mt-3 inline-flex items-center gap-1 text-xs text-[var(--accent-hover)]"
            >
              <Plus size={14} aria-hidden="true" /> Agregar opción
            </button>
          )}
          <label className="mt-3 block text-xs text-[var(--text-muted)]">
            Motivo opcional
            <input
              maxLength={1_000}
              value={proposalReason}
              onChange={(event) => setProposalReason(event.target.value)}
              className={INPUT}
            />
          </label>
          <ActionButton disabled={busy}>Guardar propuesta</ActionButton>
        </form>
      )}

      {currentSlots.length > 0 && (canSelect || canSchedule) && (
        <form
          className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (selectedSlotId) {
              void onSelectSlot(selectedSlotId, selectionReason.trim() || undefined);
            }
          }}
        >
          <h5 className="text-sm font-semibold">Elegir horario</h5>
          <fieldset className="mt-3 space-y-2">
            <legend className="sr-only">Horarios de la propuesta vigente</legend>
            {currentSlots.map((slot) => (
              <label
                key={slot.id}
                className="flex cursor-pointer items-start gap-2 rounded border border-[var(--border-color)] p-2 text-sm"
              >
                <input
                  type="radio"
                  name="meeting-slot"
                  value={slot.id}
                  checked={selectedSlotId === slot.id}
                  onChange={() => setSelectedSlotId(slot.id)}
                  className="mt-1"
                />
                <span>
                  {slotTime(slot.starts_at, slot.ends_at, slot.timezone)}
                  <small className="block text-[var(--text-muted)]">{slot.timezone}</small>
                </span>
              </label>
            ))}
          </fieldset>
          {canSelect && (
            <>
              <label className="mt-3 block text-xs text-[var(--text-muted)]">
                Motivo opcional
                <input
                  maxLength={1_000}
                  value={selectionReason}
                  onChange={(event) => setSelectionReason(event.target.value)}
                  className={INPUT}
                />
              </label>
              <ActionButton disabled={busy || !selectedSlotId}>Seleccionar horario</ActionButton>
            </>
          )}
        </form>
      )}

      {meeting.status === "slots_proposed" && (
        <TransitionForm
          title="Esperar respuesta"
          description="Registrá que la propuesta ya fue comunicada y ahora depende de la respuesta del contacto."
          actionLabel="Marcar esperando respuesta"
          busy={busy}
          onSubmit={onMarkAwaiting}
        />
      )}

      {canSchedule && currentSlots.length > 0 && (
        <form
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!selectedSlotId || !evidenceReference.trim()) return;
            void onScheduleManually({
              expected_opportunity_version: opportunityControlVersion,
              slot_id: selectedSlotId,
              evidence_type: evidenceType,
              evidence_reference: evidenceReference.trim(),
              reason: transitionReason.trim() || undefined,
            });
          }}
        >
          <h5 className="text-sm font-semibold">Confirmar manualmente</h5>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            Requiere evidencia verificable del acuerdo. La referencia se guarda como evidencia de
            auditoría y no vuelve a mostrarse en el panel.
          </p>
          <label className="mt-3 block text-xs text-[var(--text-muted)]">
            Tipo de evidencia
            <select
              value={evidenceType}
              onChange={(event) => setEvidenceType(event.target.value)}
              className={INPUT}
            >
              <option value="operator_confirmation">Confirmación del operador</option>
              <option value="email_confirmation">Confirmación por email</option>
              <option value="whatsapp_confirmation">Confirmación por WhatsApp</option>
            </select>
          </label>
          <label className="mt-3 block text-xs text-[var(--text-muted)]">
            Referencia de evidencia
            <input
              required
              autoComplete="off"
              maxLength={255}
              value={evidenceReference}
              onChange={(event) => setEvidenceReference(event.target.value)}
              className={INPUT}
            />
          </label>
          <label className="mt-3 block text-xs text-[var(--text-muted)]">
            Motivo opcional
            <input
              maxLength={1_000}
              value={transitionReason}
              onChange={(event) => setTransitionReason(event.target.value)}
              className={INPUT}
            />
          </label>
          <ActionButton disabled={busy || !selectedSlotId || !evidenceReference.trim()}>
            Confirmar reunión
          </ActionButton>
        </form>
      )}

      {meeting.status === "scheduled" && (
        <TransitionForm
          title="Solicitar reprogramación"
          description="Conserva el horario confirmado en el historial y abre una nueva coordinación."
          actionLabel="Solicitar reprogramación"
          busy={busy}
          reasonRequired
          onSubmit={onRequestReschedule}
        />
      )}

      {!isTerminal && (
        <div className="grid gap-3 sm:grid-cols-2">
          {meeting.status !== "review_required" && (
            <TransitionForm
              title="Revisión manual"
              description="Detiene el avance normal hasta que un operador revise el caso."
              actionLabel="Requerir revisión"
              busy={busy}
              reasonRequired
              onSubmit={onRequireReview}
            />
          )}
          <TransitionForm
            title="Cancelar"
            description="Cierra esta coordinación sin eliminar su historial."
            actionLabel="Cancelar reunión"
            busy={busy}
            reasonRequired
            destructive
            onSubmit={onCancel}
          />
        </div>
      )}
    </section>
  );
}

function TransitionForm({
  title,
  description,
  actionLabel,
  busy,
  reasonRequired = false,
  destructive = false,
  onSubmit,
}: {
  title: string;
  description: string;
  actionLabel: string;
  busy: boolean;
  reasonRequired?: boolean;
  destructive?: boolean;
  onSubmit: (reason?: string) => Promise<unknown>;
}) {
  const [reason, setReason] = useState("");
  return (
    <form
      className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (reasonRequired && !reason.trim()) return;
        void onSubmit(reason.trim() || undefined);
      }}
    >
      <h5 className="text-sm font-semibold">{title}</h5>
      <p className="mt-1 text-xs text-[var(--text-muted)]">{description}</p>
      <label className="mt-3 block text-xs text-[var(--text-muted)]">
        Motivo {reasonRequired ? "obligatorio" : "opcional"}
        <input
          required={reasonRequired}
          maxLength={1_000}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className={INPUT}
        />
      </label>
      <button
        type="submit"
        disabled={busy || (reasonRequired && !reason.trim())}
        className={`mt-3 w-full rounded border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
          destructive
            ? "border-[var(--error)]/50 text-[var(--error)]"
            : "border-[var(--accent)]/50 text-[var(--accent-hover)]"
        }`}
      >
        {actionLabel}
      </button>
    </form>
  );
}

import { useState } from "react";
import type {
  DeliveryEvidenceSource,
  DeliveryNotDeliveredReason,
  DeliveryResolutionInput,
} from "./types";

const INPUT =
  "mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";

interface Props {
  busy: boolean;
  onResolve: (input: DeliveryResolutionInput) => Promise<boolean>;
}

export default function DeliveryResolutionActions({ busy, onResolve }: Props) {
  const [providerMessageId, setProviderMessageId] = useState("");
  const [evidenceSource, setEvidenceSource] = useState<DeliveryEvidenceSource>("provider_api");
  const [deliveryConfirmed, setDeliveryConfirmed] = useState(false);
  const [reasonCode, setReasonCode] = useState<DeliveryNotDeliveredReason>(
    "provider_confirmed_not_delivered",
  );
  const [nonDeliveryConfirmed, setNonDeliveryConfirmed] = useState(false);

  return (
    <section aria-labelledby="delivery-resolution-title" className="mt-6 space-y-3">
      <div>
        <h4 id="delivery-resolution-title" className="font-semibold">
          Resolver entrega incierta
        </h4>
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          Estas confirmaciones son irreversibles. Ninguna opción reintenta ni reencola el mensaje.
        </p>
      </div>

      <form
        className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!providerMessageId.trim() || !deliveryConfirmed) return;
          void onResolve({
            action: "confirm_delivered",
            provider_message_id: providerMessageId.trim(),
            evidence_source: evidenceSource,
          });
        }}
      >
        <h5 className="text-sm font-semibold">Confirmar entrega</h5>
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          Usá evidencia directa del proveedor. El ID completo es write-only y no volverá a
          mostrarse.
        </p>
        <label className="mt-3 block text-xs text-[var(--text-muted)]">
          ID completo del mensaje en el proveedor
          <input
            required
            autoComplete="off"
            spellCheck={false}
            maxLength={255}
            value={providerMessageId}
            onChange={(event) => setProviderMessageId(event.target.value)}
            className={INPUT}
          />
        </label>
        <label className="mt-3 block text-xs text-[var(--text-muted)]">
          Fuente de evidencia
          <select
            value={evidenceSource}
            onChange={(event) => setEvidenceSource(event.target.value as DeliveryEvidenceSource)}
            className={INPUT}
          >
            <option value="provider_api">API del proveedor</option>
            <option value="provider_console">Consola del proveedor</option>
          </select>
        </label>
        <label className="mt-3 flex items-start gap-2 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={deliveryConfirmed}
            onChange={(event) => setDeliveryConfirmed(event.target.checked)}
            className="mt-0.5"
          />
          Confirmo que verifiqué la entrega directamente y entiendo que esta decisión es
          irreversible.
        </label>
        <button
          type="submit"
          disabled={busy || !providerMessageId.trim() || !deliveryConfirmed}
          className="mt-3 w-full rounded border border-emerald-500/50 px-3 py-2 text-sm font-medium text-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Confirmar como entregado
        </button>
      </form>

      <form
        className="rounded-lg border border-[var(--error)]/30 bg-[var(--error)]/5 p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!nonDeliveryConfirmed) return;
          void onResolve({ action: "confirm_not_delivered", reason_code: reasonCode });
        }}
      >
        <h5 className="text-sm font-semibold">Confirmar que no fue entregado</h5>
        <label className="mt-3 block text-xs text-[var(--text-muted)]">
          Evidencia de no entrega
          <select
            value={reasonCode}
            onChange={(event) => setReasonCode(event.target.value as DeliveryNotDeliveredReason)}
            className={INPUT}
          >
            <option value="provider_confirmed_not_delivered">
              El proveedor confirmó la no entrega
            </option>
            <option value="provider_record_not_found">El proveedor no encontró el registro</option>
            <option value="operator_verified_not_delivered">
              El operador verificó la no entrega
            </option>
          </select>
        </label>
        <label className="mt-3 flex items-start gap-2 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={nonDeliveryConfirmed}
            onChange={(event) => setNonDeliveryConfirmed(event.target.checked)}
            className="mt-0.5"
          />
          Confirmo la no entrega y entiendo que se cancelará definitivamente sin reintento.
        </label>
        <button
          type="submit"
          disabled={busy || !nonDeliveryConfirmed}
          className="mt-3 w-full rounded border border-[var(--error)]/50 px-3 py-2 text-sm font-medium text-[var(--error)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          Confirmar como no entregado
        </button>
      </form>
    </section>
  );
}

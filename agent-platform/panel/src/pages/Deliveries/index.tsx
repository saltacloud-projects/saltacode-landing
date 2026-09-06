import { AlertTriangle, ArrowLeft, RefreshCw, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { getDelivery, listDeliveries } from "./api";
import type { DeliveryDetail, DeliveryFilters, DeliveryStatus, DeliverySummary } from "./types";

const INITIAL_FILTERS: DeliveryFilters = { channel: "", status: "", conversationId: "" };

const STATUS_LABELS: Record<DeliveryStatus, string> = {
  queued: "En cola",
  dispatching: "Despachando",
  accepted: "Aceptado",
  delivered: "Entregado",
  read: "Leído",
  failed: "Fallido",
  delivery_unknown: "Entrega incierta",
  cancelled: "Cancelado",
};

function dateTime(value: string): string {
  return new Intl.DateTimeFormat("es-AR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusClass(status: DeliveryStatus): string {
  if (status === "delivery_unknown" || status === "failed") {
    return "border-[var(--error)]/40 bg-[var(--error)]/10 text-[var(--error)]";
  }
  if (status === "queued" || status === "dispatching") {
    return "border-[var(--warning)]/40 bg-[var(--warning)]/10 text-[var(--warning)]";
  }
  return "border-[var(--border-color)] bg-[var(--bg-hover)] text-[var(--text-secondary)]";
}

function DeliveryCard({
  delivery,
  selected,
  onSelect,
}: {
  delivery: DeliverySummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        selected
          ? "border-[var(--accent)] bg-[var(--bg-hover)]"
          : "border-[var(--border-color)] bg-[var(--bg-card)] hover:border-[var(--text-muted)]"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className={`rounded border px-2 py-0.5 text-xs ${statusClass(delivery.status)}`}>
          {STATUS_LABELS[delivery.status]}
        </span>
        <time className="text-xs text-[var(--text-muted)]">{dateTime(delivery.updated_at)}</time>
      </div>
      <p className="mt-2 truncate font-mono text-xs text-[var(--text-secondary)]">
        {delivery.correlation_id}
      </p>
      <p className="mt-2 text-sm text-[var(--text-primary)]">
        {delivery.channel} · #{delivery.sequence} · {delivery.attempt_count} intento(s)
      </p>
      {delivery.latest_safe_code && (
        <p className="mt-1 text-xs text-[var(--error)]">{delivery.latest_safe_code}</p>
      )}
      {delivery.is_fifo_blocking && (
        <p className="mt-2 text-xs text-[var(--warning)]">
          Bloquea {delivery.blocked_message_count} entrega(s) posterior(es) en esta conversación.
        </p>
      )}
    </button>
  );
}

function DeliveryDetailPanel({
  detail,
  loading,
  onBack,
}: {
  detail: DeliveryDetail | null;
  loading: boolean;
  onBack: () => void;
}) {
  if (loading) return <p role="status">Cargando detalle…</p>;
  if (!detail) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--border-color)] p-8 text-center text-sm text-[var(--text-muted)]">
        Seleccioná una entrega para revisar su evidencia.
      </div>
    );
  }

  return (
    <section
      aria-label="Detalle de entrega"
      className="min-w-0 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
    >
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex items-center gap-2 text-sm text-[var(--accent-hover)] lg:hidden"
      >
        <ArrowLeft size={16} /> Volver a entregas
      </button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">Entrega #{detail.sequence}</h3>
          <p className="mt-1 break-all font-mono text-xs text-[var(--text-muted)]">{detail.id}</p>
        </div>
        <span className={`rounded border px-2 py-1 text-xs ${statusClass(detail.status)}`}>
          {STATUS_LABELS[detail.status]}
        </span>
      </div>

      <div className="mt-4 rounded border border-[var(--warning)]/35 bg-[var(--warning)]/5 p-3 text-sm">
        <strong>Sólo observación.</strong> Una entrega incierta no se reintenta automáticamente:
        hacerlo podría duplicar mensajes o presupuestos.
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-[var(--text-muted)]">Canal</dt>
          <dd>{detail.channel}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-muted)]">Tipo</dt>
          <dd>{detail.kind}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-muted)]">Emisor</dt>
          <dd>{detail.sender_type}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-muted)]">Referencia del proveedor</dt>
          <dd className="font-mono">{detail.provider_reference ?? "No disponible"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-[var(--text-muted)]">Correlación</dt>
          <dd className="break-all font-mono text-xs">{detail.correlation_id}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-muted)]">Impacto FIFO</dt>
          <dd>
            {detail.is_fifo_blocking
              ? `${detail.blocked_message_count} entrega(s) en espera`
              : "No bloquea la cola"}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--text-muted)]">Versión de control</dt>
          <dd>{detail.control_version}</dd>
        </div>
      </dl>

      <section className="mt-6">
        <h4 className="font-medium">Intentos ({detail.attempts.length})</h4>
        <ol className="mt-2 space-y-2">
          {detail.attempts.map((attempt) => (
            <li
              key={attempt.id}
              className="rounded border border-[var(--border-color)] p-3 text-sm"
            >
              Intento {attempt.attempt_number} · control v{attempt.control_version}
              <time className="block text-xs text-[var(--text-muted)]">
                {dateTime(attempt.created_at)}
              </time>
            </li>
          ))}
          {detail.attempts.length === 0 && (
            <li className="text-sm text-[var(--text-muted)]">Sin intentos registrados.</li>
          )}
        </ol>
      </section>

      <section className="mt-6">
        <h4 className="font-medium">Trazabilidad</h4>
        <ol className="mt-2 space-y-2">
          {detail.events.map((event) => (
            <li key={event.id} className="rounded border border-[var(--border-color)] p-3 text-sm">
              <span>
                {event.from_status ?? "inicio"} → {event.to_status}
              </span>
              <span className="ml-2 text-[var(--text-muted)]">por {event.actor_type}</span>
              {event.safe_code && (
                <code className="mt-1 block break-all text-xs text-[var(--error)]">
                  {event.safe_code}
                </code>
              )}
              <time className="mt-1 block text-xs text-[var(--text-muted)]">
                {dateTime(event.created_at)}
              </time>
            </li>
          ))}
        </ol>
      </section>
    </section>
  );
}

export default function DeliveriesPage() {
  const { selectedAgent } = useAgentWorkspace();
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [items, setItems] = useState<DeliverySummary[]>([]);
  const [detail, setDetail] = useState<DeliveryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!selectedAgent) return;
    setLoading(true);
    setError("");
    try {
      const page = await listDeliveries(selectedAgent.id, filters);
      setItems(page.items);
      setDetail((current) =>
        current && !page.items.some((item) => item.id === current.id) ? null : current,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudieron cargar las entregas.");
    } finally {
      setLoading(false);
    }
  }, [selectedAgent, filters]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const open = async (deliveryId: string) => {
    if (!selectedAgent) return;
    setLoadingDetail(true);
    setError("");
    try {
      setDetail(await getDelivery(selectedAgent.id, deliveryId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo cargar el detalle.");
    } finally {
      setLoadingDetail(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <Send size={23} className="text-[var(--accent)]" />
        <div>
          <h2 className="text-xl font-semibold">Entregas de {selectedAgent?.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            Revisión segura de incidentes y evidencia de proveedor.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          className="ml-auto inline-flex items-center gap-2 rounded border border-[var(--border-color)] px-3 py-2 text-sm"
        >
          <RefreshCw size={16} /> <span className="hidden sm:inline">Actualizar</span>
        </button>
      </header>

      <div className="mb-4 flex items-start gap-2 rounded border border-[var(--error)]/30 bg-[var(--error)]/5 p-3 text-sm">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-[var(--error)]" />
        Las entregas inciertas y fallidas aparecen primero. Este espacio no permite reintentos
        ciegos.
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-[var(--text-muted)]">
          Canal
          <select
            value={filters.channel}
            onChange={(event) =>
              setFilters((current) => ({ ...current, channel: event.target.value }))
            }
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)]"
          >
            <option value="">Todos</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="web">Web</option>
          </select>
        </label>
        <label className="text-xs text-[var(--text-muted)]">
          Estado
          <select
            value={filters.status}
            onChange={(event) =>
              setFilters((current) => ({ ...current, status: event.target.value }))
            }
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)]"
          >
            <option value="">Incidentes primero</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--text-muted)]">
          ID de conversación
          <input
            value={filters.conversationId}
            onChange={(event) =>
              setFilters((current) => ({ ...current, conversationId: event.target.value }))
            }
            placeholder="UUID exacto"
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)]"
          />
        </label>
      </div>

      {error && (
        <p
          role="alert"
          className="mb-4 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]"
        >
          {error}
        </p>
      )}

      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(17rem,0.8fr)_minmax(0,1.7fr)]">
        <section
          aria-label="Lista de entregas"
          className={detail ? "hidden space-y-3 lg:block" : "space-y-3"}
        >
          {loading && <p role="status">Cargando entregas…</p>}
          {!loading && items.length === 0 && (
            <p className="rounded border border-dashed border-[var(--border-color)] p-6 text-center text-sm text-[var(--text-muted)]">
              No hay entregas para estos filtros.
            </p>
          )}
          {items.map((item) => (
            <DeliveryCard
              key={item.id}
              delivery={item}
              selected={detail?.id === item.id}
              onSelect={() => void open(item.id)}
            />
          ))}
        </section>
        <div className={detail ? "block" : "hidden lg:block"}>
          <DeliveryDetailPanel
            detail={detail}
            loading={loadingDetail}
            onBack={() => setDetail(null)}
          />
        </div>
      </div>
    </div>
  );
}

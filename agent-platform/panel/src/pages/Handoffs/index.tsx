import { ArrowRight, ArrowRightLeft, Plus, RefreshCw } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { createHandoffRoute, listHandoffRoutes, updateHandoffRoute } from "./api";
import { type HandoffRoute, type HandoffTrigger, routeVersion } from "./types";

const TRIGGER_LABELS: Record<HandoffTrigger, string> = {
  quote_requested: "Presupuesto solicitado",
  manual_escalation: "Escalación manual",
};

export default function HandoffsPage() {
  const { profiles, selectedAgent } = useAgentWorkspace();
  const [routes, setRoutes] = useState<HandoffRoute[]>([]);
  const [targetAgentId, setTargetAgentId] = useState("");
  const [trigger, setTrigger] = useState<HandoffTrigger>("quote_requested");
  const [isActive, setIsActive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busyRouteId, setBusyRouteId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const targetProfiles = profiles.filter((profile) => profile.id !== selectedAgent?.id);

  const refresh = useCallback(async () => {
    if (!selectedAgent) return;
    setLoading(true);
    setError("");
    try {
      setRoutes(await listHandoffRoutes(selectedAgent.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudieron cargar los handoffs.");
    } finally {
      setLoading(false);
    }
  }, [selectedAgent]);

  useEffect(() => {
    setRoutes([]);
    setTargetAgentId("");
    void refresh();
  }, [refresh]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedAgent || !targetAgentId) return;
    setCreating(true);
    setError("");
    try {
      await createHandoffRoute(selectedAgent.id, { targetAgentId, trigger, isActive });
      setTargetAgentId("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo crear la regla.");
    } finally {
      setCreating(false);
    }
  };

  const update = async (
    route: HandoffRoute,
    input: { targetAgentId?: string; isActive?: boolean },
  ) => {
    if (!selectedAgent) return;
    setBusyRouteId(route.id);
    setError("");
    try {
      await updateHandoffRoute(selectedAgent.id, route.id, {
        ...input,
        expectedVersion: routeVersion(route),
      });
      await refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "La regla cambió o no pudo actualizarse. Actualizá e intentá nuevamente.",
      );
    } finally {
      setBusyRouteId(null);
    }
  };

  const profileName = (profileId: string) =>
    profiles.find((profile) => profile.id === profileId)?.name ?? "Agente no disponible";

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <ArrowRightLeft size={23} className="text-[var(--accent)]" />
        <div>
          <h2 className="text-xl font-semibold">Handoffs de {selectedAgent?.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            Reglas determinísticas para transferir oportunidades a otro agente.
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

      <div className="mb-5 rounded border border-[var(--accent)]/30 bg-[var(--accent)]/5 p-3 text-sm text-[var(--text-secondary)]">
        La fuente es el agente seleccionado. El handoff cambia la propiedad de la
        <strong className="text-[var(--text-primary)]"> oportunidad</strong>; la conversación
        original conserva su agente y su historial.
      </div>

      <form
        onSubmit={(event) => void submit(event)}
        className="mb-6 grid gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 md:grid-cols-[1fr_1fr_auto_auto] md:items-end"
      >
        <label className="text-xs text-[var(--text-muted)]">
          Agente destino
          <select
            required
            value={targetAgentId}
            onChange={(event) => setTargetAgentId(event.target.value)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-sm text-[var(--text-primary)]"
          >
            <option value="">Seleccionar…</option>
            {targetProfiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--text-muted)]">
          Disparador
          <select
            value={trigger}
            onChange={(event) => setTrigger(event.target.value as HandoffTrigger)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-sm text-[var(--text-primary)]"
          >
            {Object.entries(TRIGGER_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-h-10 items-center gap-2 rounded border border-[var(--border-color)] px-3 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(event) => setIsActive(event.target.checked)}
          />
          Activa
        </label>
        <button
          type="submit"
          disabled={creating || !targetAgentId}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          <Plus size={16} /> {creating ? "Creando…" : "Crear regla"}
        </button>
      </form>

      {targetProfiles.length === 0 && (
        <p className="mb-4 rounded border border-[var(--warning)]/35 bg-[var(--warning)]/5 p-3 text-sm">
          Necesitás acceso visible a otro agente para configurarlo como destino.
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="mb-4 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]"
        >
          {error}
        </p>
      )}
      {loading && <p role="status">Cargando reglas…</p>}
      {!loading && routes.length === 0 && (
        <p className="rounded-lg border border-dashed border-[var(--border-color)] p-8 text-center text-sm text-[var(--text-muted)]">
          Este agente todavía no tiene reglas de handoff.
        </p>
      )}

      <ul aria-label="Reglas de handoff" className="grid gap-3">
        {routes.map((route) => (
          <li
            key={route.id}
            className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <strong>{selectedAgent?.name}</strong>
              <ArrowRight size={17} className="text-[var(--accent)]" />
              <select
                aria-label={`Destino para ${TRIGGER_LABELS[route.trigger]}`}
                value={route.target_agent_id}
                disabled={busyRouteId === route.id}
                onChange={(event) => void update(route, { targetAgentId: event.target.value })}
                className="min-w-0 flex-1 rounded border border-[var(--border-color)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm"
              >
                {!targetProfiles.some((profile) => profile.id === route.target_agent_id) && (
                  <option value={route.target_agent_id}>
                    {profileName(route.target_agent_id)}
                  </option>
                )}
                {targetProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={route.is_active}
                  disabled={busyRouteId === route.id}
                  onChange={(event) => void update(route, { isActive: event.target.checked })}
                />
                Activa
              </label>
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--text-muted)]">
              <span>{TRIGGER_LABELS[route.trigger]}</span>
              <span>Versión {routeVersion(route)}</span>
              {busyRouteId === route.id && <span role="status">Guardando…</span>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

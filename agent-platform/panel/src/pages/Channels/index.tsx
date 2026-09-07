import { Cable, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { ApiError, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { blockingMessage, channelLabel, READINESS_LABELS } from "../../runtime/channels";
import type { ChannelCatalog } from "../../runtime/types";

export default function ChannelsPage() {
  const { user } = useAuth();
  const { profiles, loading: loadingAgents, error: agentError } = useAgentWorkspace();
  const [catalog, setCatalog] = useState<ChannelCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const canReadConnections = hasPermission(user, PERMISSIONS.CONNECTIONS_READ);
  const canReadRoutes = hasPermission(user, PERMISSIONS.RUNTIME_READ);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    if (!canReadConnections) {
      setLoading(false);
      return;
    }
    api<ChannelCatalog>("/channel-catalog")
      .then((value) => {
        if (!cancelled) setCatalog(value);
      })
      .catch((value) => {
        if (!cancelled)
          setError(
            value instanceof ApiError && value.status === 403
              ? "No tenés permiso para consultar las conexiones."
              : "No se pudo consultar el estado de los canales.",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [canReadConnections]);

  return (
    <div className="max-w-6xl space-y-6">
      <header className="flex items-start gap-3">
        <Cable className="mt-1 text-[var(--accent)]" size={24} />
        <div>
          <h2 className="text-xl font-semibold">Canales</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Conectá cuentas y definí qué agente recibe cada ingreso, sin cambiar el contexto de
            operación del CRM.
          </p>
        </div>
      </header>
      <section
        aria-labelledby="channel-setup-title"
        className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5"
      >
        <h3 id="channel-setup-title" className="font-semibold">
          Cómo conectar un canal
        </h3>
        <ol className="mt-3 list-inside list-decimal space-y-2 text-sm text-[var(--text-secondary)]">
          <li>
            Creá la conexión con la cuenta y credenciales del proveedor. Los secretos se ingresan
            una vez y no se muestran al consultarlos.
          </li>
          <li>
            Creá una ruta para el agente de ingreso elegido. El gateway normaliza el mensaje y
            resuelve esa ruta; no el selector del panel.
          </li>
          <li>
            Configurá y verificá el ingreso externo que requiera el proveedor. Una conexión guardada
            no confirma que ya reciba mensajes.
          </li>
        </ol>
        {canReadConnections && (
          <Link
            className="mt-4 inline-flex min-h-11 items-center rounded bg-[var(--accent)] px-4 py-2 text-sm text-white"
            to="/channels/connections"
          >
            Administrar conexiones y credenciales
          </Link>
        )}
      </section>
      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status" className="flex items-center gap-2 text-sm">
          <LoaderCircle size={16} className="animate-spin" /> Consultando canales…
        </p>
      ) : (
        catalog && (
          <section
            aria-label="Disponibilidad de los canales"
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
          >
            {catalog.adapters.map((adapter) => {
              const connections = catalog.connections.filter(
                (connection) => connection.adapter_key === adapter.adapter_key,
              );
              return (
                <article
                  key={adapter.adapter_key}
                  className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
                >
                  <h3 className="font-semibold">{channelLabel(adapter.channel)}</h3>
                  <p className="mt-2 text-sm">
                    {adapter.adapter_implemented ? "Adaptador disponible" : "Integración pendiente"}
                  </p>
                  {!adapter.adapter_implemented && (
                    <p className="mt-2 text-xs text-[var(--text-muted)]">
                      Requiere implementación y habilitación externa; no se puede activar desde una
                      credencial.
                    </p>
                  )}
                  {adapter.blocking_codes.length > 0 && (
                    <ul className="mt-2 space-y-1 text-xs text-[var(--text-muted)]">
                      {adapter.blocking_codes.map((code) => (
                        <li key={code}>{blockingMessage(code)}</li>
                      ))}
                    </ul>
                  )}
                  {connections.length ? (
                    <ul className="mt-3 space-y-2">
                      {connections.map((connection) => (
                        <li
                          key={connection.connection_id}
                          className="border-t border-[var(--border-color)] pt-2 text-sm"
                        >
                          <strong>{connection.name}</strong>
                          <span className="mt-1 block text-xs text-[var(--text-muted)]">
                            {READINESS_LABELS[connection.readiness]} ·{" "}
                            {connection.active_route_count} rutas activas
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    adapter.adapter_implemented && (
                      <p className="mt-3 text-xs text-[var(--text-muted)]">
                        Sin conexiones configuradas.
                      </p>
                    )
                  )}
                </article>
              );
            })}
          </section>
        )
      )}
      {!canReadConnections && (
        <p className="text-sm text-[var(--text-muted)]">
          Tu acceso no incluye el catálogo de conexiones. Las rutas también requieren permiso sobre
          el agente de destino.
        </p>
      )}
      {canReadRoutes && (
        <section aria-labelledby="channel-routes-title" className="space-y-3">
          <div>
            <h3 id="channel-routes-title" className="font-semibold">
              Rutas de ingreso por agente
            </h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              Elegí el destino que vas a configurar. Una derivación posterior puede cambiar quién
              responde sin reescribir el agente ni el canal de ingreso.
            </p>
          </div>
          {agentError && (
            <p role="alert" className="text-sm text-red-400">
              {agentError}
            </p>
          )}
          {loadingAgents ? (
            <p role="status">Cargando agentes…</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {profiles.map((agent) => (
                <Link
                  key={agent.id}
                  to={`/agents/${agent.id}/channels`}
                  className="min-h-11 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
                >
                  <span className="block font-medium">{agent.name}</span>
                  <span className="mt-1 block text-xs text-[var(--text-muted)]">
                    Configurar rutas de ingreso ·{" "}
                    {agent.is_active ? "Agente habilitado" : "Agente inactivo"}
                  </span>
                </Link>
              ))}
              {profiles.length === 0 && (
                <p className="text-sm text-[var(--text-muted)]">
                  No hay agentes accesibles. Necesitás crear uno o recibir acceso antes de
                  configurar sus rutas.
                </p>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

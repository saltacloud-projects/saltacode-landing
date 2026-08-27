import { useEffect, useMemo, useRef, useState } from "react";
import { Cable, Globe2, LoaderCircle, MessageCircle, Plus, Save, X } from "lucide-react";
import { Link } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import type { AgentRoute, ChannelConnection, ChannelKind } from "../../runtime/types";

const INPUT = "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:opacity-60";

export default function AgentChannelsPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.RUNTIME_MANAGE);
  const canReadConnections = hasPermission(user, PERMISSIONS.CONNECTIONS_READ);
  const [routes, setRoutes] = useState<AgentRoute[]>([]);
  const [connections, setConnections] = useState<ChannelConnection[]>([]);
  const [routeSelections, setRouteSelections] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [channel, setChannel] = useState<ChannelKind>("web");
  const [routeKey, setRouteKey] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const createButton = useRef<HTMLButtonElement>(null);
  const busyState = useRef<string | null>(null);

  const load = async () => {
    if (!selectedAgent) return;
    setLoading(true);
    setError("");
    try {
      const [routeRows, connectionRows] = await Promise.all([
        api<AgentRoute[]>(`/profiles/${selectedAgent.id}/routes`),
        canReadConnections ? api<ChannelConnection[]>("/channel-connections") : Promise.resolve([]),
      ]);
      setRoutes(routeRows);
      setConnections(connectionRows);
      setRouteSelections(Object.fromEntries(routeRows.map((route) => [route.id, route.channel_connection_id])));
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudieron cargar las rutas del agente.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [selectedAgent?.id, canReadConnections]);

  const availableConnections = useMemo(
    () => connections.filter((connection) => connection.channel === channel && connection.is_active),
    [channel, connections],
  );

  useEffect(() => {
    if (!availableConnections.some((connection) => connection.id === connectionId)) {
      setConnectionId(availableConnections[0]?.id || "");
    }
  }, [availableConnections, connectionId]);

  useEffect(() => {
    busyState.current = busyId;
  }, [busyId]);

  useEffect(() => {
    if (!showCreate) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && busyState.current !== "create") setShowCreate(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      requestAnimationFrame(() => createButton.current?.focus());
    };
  }, [showCreate]);

  if (!selectedAgent) return null;

  const connectionName = (id: string) => connections.find((connection) => connection.id === id)?.name || id;
  const matchingConnections = (routeChannel: ChannelKind) => connections.filter((connection) => connection.channel === routeChannel && connection.is_active);

  const createRoute = async () => {
    if (!routeKey.trim() || !connectionId) return setError("Completá la route key y elegí una conexión compatible.");
    setBusyId("create");
    setError("");
    setNotice("");
    try {
      await api(`/profiles/${selectedAgent.id}/routes`, { method: "POST", body: JSON.stringify({ channel, route_key: routeKey.trim(), channel_connection_id: connectionId, is_active: true }) });
      setRouteKey("");
      setShowCreate(false);
      setNotice("Ruta creada. El canal ya puede resolver este agente por su route key.");
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo crear la ruta.");
    } finally {
      setBusyId(null);
    }
  };

  const updateRoute = async (route: AgentRoute, body: { channel_connection_id?: string; is_active?: boolean }) => {
    setBusyId(route.id);
    setError("");
    setNotice("");
    try {
      await api(`/profiles/${selectedAgent.id}/routes/${route.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setNotice("Ruta actualizada.");
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo actualizar la ruta.");
    } finally {
      setBusyId(null);
    }
  };

  const deactivate = async (route: AgentRoute) => {
    if (!window.confirm(`¿Desactivar la ruta ${route.route_key}?`)) return;
    setBusyId(route.id);
    setError("");
    try {
      await api(`/profiles/${selectedAgent.id}/routes/${route.id}/deactivate`, { method: "POST" });
      setNotice("Ruta desactivada.");
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo desactivar la ruta.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="max-w-6xl space-y-5">
      <header className="flex flex-wrap items-center gap-3"><Cable className="text-[var(--accent)]" size={22} /><div><h2 className="text-xl font-semibold">Canales de {selectedAgent.name}</h2><p className="text-sm text-[var(--text-muted)]">Rutas server-side que conectan un canal y una cuenta compartida con este agente.</p></div>{canManage && canReadConnections && <button ref={createButton} onClick={() => setShowCreate(true)} className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white"><Plus size={16} /> Nueva ruta</button>}</header>
      <aside className="rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-4 text-sm text-[var(--text-secondary)]"><strong className="text-[var(--text-primary)]">¿Qué es la route key?</strong> Es un identificador estable que recibe el servidor para resolver el agente. No es un secreto y el navegador público no elige un <code>agent_id</code> arbitrario. Para cambiar credenciales usá <Link to="/shared/channel-connections" className="text-[var(--accent)] hover:underline">Conexiones de canal</Link>.</aside>
      {!canReadConnections && <p className="rounded border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-300">Tenés permiso para ver rutas, pero no para leer las conexiones compartidas. Se muestran sus IDs y no se habilita la reasignación.</p>}
      {error && !showCreate && <p className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error}</p>}
      {notice && <p className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400" role="status">{notice}</p>}
      {loading ? <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status"><LoaderCircle className="animate-spin" size={16} /> Cargando rutas…</p> : <div className="grid gap-3 lg:grid-cols-2">{routes.map((route) => {
        const Icon = route.channel === "web" ? Globe2 : MessageCircle;
        const selectedConnection = routeSelections[route.id] || route.channel_connection_id;
        return <article key={route.id} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"><div className="flex items-start gap-3"><Icon className="mt-0.5 text-[var(--accent)]" size={19} /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold capitalize">{route.channel}</h3><span className={`rounded px-2 py-0.5 text-xs ${route.is_active ? "bg-emerald-500/10 text-emerald-400" : "bg-[var(--bg-hover)] text-[var(--text-muted)]"}`}>{route.is_active ? "Activa" : "Inactiva"}</span></div><code className="mt-1 block truncate text-xs text-[var(--text-secondary)]" title={route.route_key}>{route.route_key}</code></div></div><div className="mt-4"><label className="text-xs text-[var(--text-muted)]">Conexión de canal{canReadConnections ? <select disabled={!canManage} className={`${INPUT} mt-1`} value={selectedConnection} onChange={(event) => setRouteSelections({ ...routeSelections, [route.id]: event.target.value })}>{matchingConnections(route.channel).map((connection) => <option key={connection.id} value={connection.id}>{connection.name}{connection.has_credentials ? "" : " · sin secreto"}</option>)}</select> : <code className="mt-1 block truncate rounded border border-[var(--border-color)] p-2">{connectionName(route.channel_connection_id)}</code>}</label></div>{canManage && <div className="mt-4 flex flex-wrap gap-2">{canReadConnections && selectedConnection !== route.channel_connection_id && <button onClick={() => updateRoute(route, { channel_connection_id: selectedConnection })} disabled={busyId === route.id} className="flex items-center gap-1 rounded bg-[var(--accent)] px-2 py-1.5 text-xs text-white"><Save size={14} /> Guardar vínculo</button>}{route.is_active ? <button onClick={() => deactivate(route)} disabled={busyId === route.id} className="rounded border border-red-500/40 px-2 py-1.5 text-xs text-red-400">Desactivar</button> : <button onClick={() => updateRoute(route, { is_active: true })} disabled={busyId === route.id} className="rounded border border-emerald-500/40 px-2 py-1.5 text-xs text-emerald-400">Reactivar</button>}</div>}</article>;
      })}{routes.length === 0 && <p className="text-sm text-[var(--text-muted)]">Este agente todavía no tiene rutas de canal.</p>}</div>}

      {showCreate && <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && busyId !== "create") setShowCreate(false); }}><section className="w-full max-w-lg rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="route-title"><header className="flex items-center justify-between border-b border-[var(--border-color)] p-4"><h3 id="route-title" className="font-semibold">Nueva ruta server-side</h3><button onClick={() => setShowCreate(false)} aria-label="Cerrar"><X size={18} /></button></header><div className="grid gap-4 p-4"><label className="text-xs">Canal<select autoFocus className={`${INPUT} mt-1`} value={channel} onChange={(event) => setChannel(event.target.value as ChannelKind)}><option value="web">Web</option><option value="whatsapp">WhatsApp</option></select></label><label className="text-xs">Route key<input className={`${INPUT} mt-1 font-mono`} value={routeKey} onChange={(event) => setRouteKey(event.target.value)} placeholder="landing:principal" pattern="[a-z0-9][a-z0-9._:-]*" /><span className="mt-1 block text-[var(--text-muted)]">Minúsculas, números y los símbolos . _ : -. Debe ser única por canal.</span></label><label className="text-xs">Conexión<select className={`${INPUT} mt-1`} value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>{availableConnections.length === 0 && <option value="">No hay conexiones activas para este canal</option>}{availableConnections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}{connection.has_credentials ? "" : " · sin secreto"}</option>)}</select></label>{error && <p className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error}</p>}</div><footer className="flex justify-end gap-2 border-t border-[var(--border-color)] p-4"><button onClick={() => setShowCreate(false)} className="rounded border border-[var(--border-color)] px-3 py-2 text-sm">Cancelar</button><button onClick={createRoute} disabled={busyId === "create" || !connectionId} className="rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50">Crear ruta</button></footer></section></div>}
    </div>
  );
}

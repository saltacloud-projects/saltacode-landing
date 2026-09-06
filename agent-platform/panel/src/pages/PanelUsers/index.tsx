import { Bot, KeyRound, LoaderCircle, Pencil, Plus, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";

interface PanelUser {
  id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  permissions: string[];
}

interface PanelRole {
  key: string;
  name: string;
  description: string | null;
  permissions: string[];
  is_active: boolean;
}

interface AgentOption {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
}

interface AgentGrant {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_slug: string;
  permissions: string[];
  is_active: boolean;
}

interface AgentGrantCollection {
  user_id: string;
  available_permissions: string[];
  agents: AgentOption[];
  grants: AgentGrant[];
}

const INPUT =
  "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none";

const AGENT_PERMISSION_LABELS: Record<string, string> = {
  "dashboard.read": "Ver resumen",
  "profiles.read": "Ver identidad",
  "knowledge.read": "Ver conocimiento",
  "tools.read": "Ver herramientas",
  "tools.manage": "Administrar herramientas",
  "sources.read": "Ver fuentes",
  "sources.manage": "Administrar fuentes",
  "users.read": "Ver accesos de canales",
  "conversations.read": "Ver conversaciones",
  "conversations.manage": "Intervenir conversaciones",
  "opportunities.read": "Ver oportunidades",
  "opportunities.manage": "Administrar oportunidades",
  "quotes.approve": "Aprobar presupuestos",
  "deliveries.read": "Ver entregas",
  "deliveries.review": "Revisar entregas inciertas",
  "audit.read": "Ver auditoría",
  "promptlab.use": "Usar PromptLab",
  "documents.read": "Ver documentos",
  "documents.manage": "Administrar documentos",
  "documents.taxonomy": "Administrar categorías documentales",
  "documents.settings": "Configurar documentos",
  "runtime.read": "Ver runtime",
  "runtime.manage": "Administrar runtime",
};

export default function PanelUsersPage() {
  const [users, setUsers] = useState<PanelUser[]>([]);
  const [roles, setRoles] = useState<PanelRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<PanelUser | null>(null);
  const [resetting, setResetting] = useState<PanelUser | null>(null);
  const [granting, setGranting] = useState<PanelUser | null>(null);
  const [grantData, setGrantData] = useState<AgentGrantCollection | null>(null);
  const [grantDrafts, setGrantDrafts] = useState<Record<string, string[]>>({});
  const [grantBusyAgent, setGrantBusyAgent] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("document_manager");

  const load = useCallback(async () => {
    const [userRows, roleRows] = await Promise.all([
      api<PanelUser[]>("/panel-users/"),
      api<PanelRole[]>("/panel-users/roles"),
    ]);
    setUsers(userRows);
    setRoles(roleRows);
  }, []);

  useEffect(() => {
    load()
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [load]);

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/panel-users/", {
        method: "POST",
        body: JSON.stringify({ email, name, password, role }),
      });
      setEmail("");
      setName("");
      setPassword("");
      setRole("document_manager");
      setShowCreate(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear el usuario");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError("");
    try {
      await api(`/panel-users/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: editing.name,
          role: editing.role,
          is_active: editing.is_active,
        }),
      });
      setEditing(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar el usuario");
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async () => {
    if (!resetting || password.length < 8) return;
    setBusy(true);
    setError("");
    try {
      await api(`/panel-users/${resetting.id}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setPassword("");
      setResetting(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cambiar la contraseña");
    } finally {
      setBusy(false);
    }
  };

  const openAgentGrants = async (user: PanelUser) => {
    setGranting(user);
    setGrantData(null);
    setGrantDrafts({});
    setError("");
    try {
      const data = await api<AgentGrantCollection>(`/panel-users/${user.id}/agent-grants`);
      setGrantData(data);
      setGrantDrafts(
        Object.fromEntries(
          data.grants
            .filter((grant) => grant.is_active)
            .map((grant) => [grant.agent_id, grant.permissions]),
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los accesos por agente");
      setGranting(null);
    }
  };

  const setAgentEnabled = (agentId: string, enabled: boolean) => {
    if (!grantData) return;
    setGrantDrafts((current) => ({
      ...current,
      [agentId]: enabled
        ? grantData.available_permissions.includes("*")
          ? ["*"]
          : grantData.available_permissions
        : [],
    }));
  };

  const setAgentPermission = (agentId: string, permission: string, enabled: boolean) => {
    setGrantDrafts((current) => {
      const existing = current[agentId] || [];
      let permissions: string[];
      if (permission === "*") {
        permissions = enabled
          ? ["*"]
          : (grantData?.available_permissions.filter((value) => value !== "*") ?? []);
      } else {
        permissions = enabled
          ? [...existing.filter((value) => value !== "*"), permission]
          : existing.filter((value) => value !== permission);
      }
      return { ...current, [agentId]: [...new Set(permissions)] };
    });
  };

  const saveAgentGrant = async (agentId: string) => {
    if (!granting) return;
    const permissions = grantDrafts[agentId] || [];
    setGrantBusyAgent(agentId);
    setError("");
    try {
      if (permissions.length === 0) {
        await api(`/panel-users/${granting.id}/agent-grants/${agentId}`, {
          method: "DELETE",
        });
      } else {
        await api(`/panel-users/${granting.id}/agent-grants/${agentId}`, {
          method: "PUT",
          body: JSON.stringify({ permissions }),
        });
      }
      await openAgentGrants(granting);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar el acceso al agente");
    } finally {
      setGrantBusyAgent(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-bold">
            <ShieldCheck size={21} className="text-[var(--accent)]" />
            Accesos del panel
          </h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Cuentas administrativas y roles persistidos en PostgreSQL.
          </p>
        </div>
        <button
          type="button"
          className="flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white"
          onClick={() => {
            setPassword("");
            setShowCreate(true);
          }}
        >
          <Plus size={16} />
          Nuevo usuario
        </button>
      </div>
      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]">
        {loading ? (
          <div className="flex justify-center p-10">
            <LoaderCircle className="animate-spin text-[var(--accent)]" />
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--border-color)] bg-[var(--bg-secondary)] text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-3">Usuario</th>
                <th className="px-4 py-3">Rol</th>
                <th className="px-4 py-3">Estado</th>
                <th className="px-4 py-3 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-[var(--border-color)]/60">
                  <td className="px-4 py-3">
                    <p className="font-medium">{user.name}</p>
                    <p className="text-xs text-[var(--text-muted)]">{user.email}</p>
                  </td>
                  <td className="px-4 py-3">
                    {roles.find((item) => item.key === user.role)?.name || user.role}
                  </td>
                  <td className="px-4 py-3">
                    <span className={user.is_active ? "text-emerald-400" : "text-red-400"}>
                      {user.is_active ? "Activo" : "Inactivo"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        title="Administrar agentes"
                        className="rounded p-2 hover:bg-[var(--bg-hover)]"
                        onClick={() => void openAgentGrants(user)}
                      >
                        <Bot size={15} />
                      </button>
                      <button
                        type="button"
                        title="Editar"
                        className="rounded p-2 hover:bg-[var(--bg-hover)]"
                        onClick={() => setEditing({ ...user })}
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        title="Cambiar contraseña"
                        className="rounded p-2 hover:bg-[var(--bg-hover)]"
                        onClick={() => {
                          setPassword("");
                          setResetting(user);
                        }}
                      >
                        <KeyRound size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <section className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <h3 className="text-sm font-semibold">Roles disponibles</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {roles
            .filter((item) => item.is_active)
            .map((item) => (
              <article key={item.key} className="rounded border border-[var(--border-color)] p-3">
                <p className="font-medium">{item.name}</p>
                <p className="mt-1 text-xs text-[var(--text-muted)]">{item.description}</p>
                <p className="mt-2 text-xs text-[var(--text-secondary)]">
                  {item.permissions.includes("*")
                    ? "Todos los permisos"
                    : item.permissions.join(", ")}
                </p>
              </article>
            ))}
        </div>
      </section>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
            <div className="mb-4 flex justify-between">
              <h3 className="font-semibold">Nuevo usuario del panel</h3>
              <button type="button" onClick={() => setShowCreate(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3">
              <label className="block text-xs text-[var(--text-secondary)]">
                Nombre
                <input
                  className={`${INPUT} mt-1`}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label className="block text-xs text-[var(--text-secondary)]">
                Email
                <input
                  type="email"
                  className={`${INPUT} mt-1`}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
              <label className="block text-xs text-[var(--text-secondary)]">
                Contraseña inicial
                <input
                  type="password"
                  minLength={8}
                  className={`${INPUT} mt-1`}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <span className="mt-1 block text-[var(--text-muted)]">
                  Mínimo 8 caracteres. No se muestra después de crear la cuenta.
                </span>
              </label>
              <label className="block text-xs text-[var(--text-secondary)]">
                Rol
                <select
                  className={`${INPUT} mt-1`}
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  {roles
                    .filter((item) => item.is_active)
                    .map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.name}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-[var(--border-color)] px-3 py-2 text-sm"
                onClick={() => setShowCreate(false)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={busy || !name.trim() || !email.trim() || password.length < 8}
                onClick={create}
              >
                {busy ? "Creando..." : "Crear"}
              </button>
            </div>
          </div>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
            <div className="mb-4 flex justify-between">
              <h3 className="font-semibold">Editar {editing.email}</h3>
              <button type="button" onClick={() => setEditing(null)}>
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3">
              <label className="block text-xs text-[var(--text-secondary)]">
                Nombre
                <input
                  className={`${INPUT} mt-1`}
                  value={editing.name}
                  onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                />
              </label>
              <label className="block text-xs text-[var(--text-secondary)]">
                Rol
                <select
                  className={`${INPUT} mt-1`}
                  value={editing.role}
                  onChange={(e) => setEditing({ ...editing, role: e.target.value })}
                >
                  {roles
                    .filter((item) => item.is_active)
                    .map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editing.is_active}
                  onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })}
                />
                Cuenta activa
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-[var(--border-color)] px-3 py-2 text-sm"
                onClick={() => setEditing(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={busy || !editing.name.trim()}
                onClick={save}
              >
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}

      {granting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold">Agentes de {granting.name}</h3>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  El rol define el máximo permitido; cada grant limita ese acceso a un agente.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setGranting(null);
                  setGrantData(null);
                }}
                aria-label="Cerrar accesos por agente"
              >
                <X size={18} />
              </button>
            </div>
            {!grantData ? (
              <p className="flex items-center gap-2 py-8 text-sm text-[var(--text-muted)]">
                <LoaderCircle className="animate-spin" size={16} /> Cargando accesos…
              </p>
            ) : grantData.agents.length === 0 ? (
              <p className="py-8 text-sm text-[var(--text-muted)]">No hay agentes configurados.</p>
            ) : (
              <div className="space-y-3">
                {grantData.agents.map((agent) => {
                  const permissions = grantDrafts[agent.id] || [];
                  const enabled = permissions.length > 0;
                  const hasWildcard = permissions.includes("*");
                  return (
                    <article
                      key={agent.id}
                      className="rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-4"
                    >
                      <div className="flex flex-wrap items-center gap-3">
                        <label className="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium">
                          <input
                            type="checkbox"
                            checked={enabled}
                            onChange={(event) => setAgentEnabled(agent.id, event.target.checked)}
                          />
                          <span className="truncate">{agent.name}</span>
                          {!agent.is_active && (
                            <span className="text-xs font-normal text-[var(--text-muted)]">
                              Inactivo
                            </span>
                          )}
                        </label>
                        <button
                          type="button"
                          className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                          disabled={grantBusyAgent === agent.id}
                          onClick={() => void saveAgentGrant(agent.id)}
                        >
                          {grantBusyAgent === agent.id ? "Guardando…" : "Guardar"}
                        </button>
                      </div>
                      <code className="mt-1 block text-xs text-[var(--text-muted)]">
                        {agent.slug}
                      </code>
                      {enabled && (
                        <div className="mt-3 border-t border-[var(--border-color)] pt-3">
                          {grantData.available_permissions.includes("*") && (
                            <label className="flex items-center gap-2 text-xs font-medium">
                              <input
                                type="checkbox"
                                checked={hasWildcard}
                                onChange={(event) =>
                                  setAgentPermission(agent.id, "*", event.target.checked)
                                }
                              />
                              Acceso completo al agente
                            </label>
                          )}
                          {!hasWildcard && (
                            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                              {grantData.available_permissions
                                .filter((permission) => permission !== "*")
                                .map((permission) => (
                                  <label
                                    key={permission}
                                    className="flex items-center gap-2 text-xs text-[var(--text-secondary)]"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={permissions.includes(permission)}
                                      onChange={(event) =>
                                        setAgentPermission(
                                          agent.id,
                                          permission,
                                          event.target.checked,
                                        )
                                      }
                                    />
                                    {AGENT_PERMISSION_LABELS[permission] || permission}
                                  </label>
                                ))}
                            </div>
                          )}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {resetting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
            <div className="mb-4 flex justify-between">
              <h3 className="font-semibold">Cambiar contraseña</h3>
              <button type="button" onClick={() => setResetting(null)}>
                <X size={18} />
              </button>
            </div>
            <p className="mb-3 text-sm text-[var(--text-secondary)]">{resetting.email}</p>
            <input
              type="password"
              minLength={8}
              className={INPUT}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Nueva contraseña"
            />
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-[var(--border-color)] px-3 py-2 text-sm"
                onClick={() => setResetting(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={busy || password.length < 8}
                onClick={resetPassword}
              >
                Actualizar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

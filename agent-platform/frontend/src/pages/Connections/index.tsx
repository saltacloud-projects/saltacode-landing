import {
  Cable,
  CheckCircle2,
  CloudCog,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  PowerOff,
  RotateCw,
  Trash2,
  X,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import type { ChannelConnection, ChannelKind, ProviderConnection } from "../../runtime/types";

type ConnectionKind = "provider" | "channel";
type Connection = ProviderConnection | ChannelConnection;

interface ConnectionForm {
  name: string;
  slug: string;
  channel: ChannelKind;
  baseUrl: string;
  externalAccountId: string;
  settings: string;
  apiKey: string;
  accessToken: string;
  verifyToken: string;
  appSecret: string;
  isActive: boolean;
}

const INPUT =
  "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";

function emptyForm(): ConnectionForm {
  return {
    name: "",
    slug: "",
    channel: "web",
    baseUrl: "",
    externalAccountId: "",
    settings: "{}",
    apiKey: "",
    accessToken: "",
    verifyToken: "",
    appSecret: "",
    isActive: true,
  };
}

function isChannel(connection: Connection): connection is ChannelConnection {
  return "channel" in connection;
}

function formattedSettings(settings: Record<string, unknown>): string {
  return JSON.stringify(settings || {}, null, 2);
}

function ConnectionLibraryPage({ kind }: { kind: ConnectionKind }) {
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.CONNECTIONS_MANAGE);
  const endpoint = kind === "provider" ? "/provider-connections" : "/channel-connections";
  const [rows, setRows] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Connection | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ConnectionForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const initialInput = useRef<HTMLInputElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setRows(await api<Connection[]>(endpoint));
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudieron cargar las conexiones.");
    } finally {
      setLoading(false);
    }
  }, [endpoint]);

  const closeForm = useCallback(() => {
    if (saving) return;
    setShowForm(false);
    setEditing(null);
    setForm(emptyForm());
    requestAnimationFrame(() => returnFocus.current?.focus());
  }, [saving]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!showForm) return;
    initialInput.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeForm();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [showForm, closeForm]);

  const rememberFocus = () => {
    returnFocus.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
  };

  const openCreate = () => {
    rememberFocus();
    setEditing(null);
    setForm(emptyForm());
    setError("");
    setShowForm(true);
  };

  const openEdit = (connection: Connection) => {
    rememberFocus();
    setEditing(connection);
    setForm({
      ...emptyForm(),
      name: connection.name,
      slug: connection.slug,
      channel: isChannel(connection) ? connection.channel : "web",
      baseUrl: !isChannel(connection) ? connection.base_url || "" : "",
      externalAccountId: isChannel(connection) ? connection.external_account_id || "" : "",
      settings: formattedSettings(connection.settings),
      isActive: connection.is_active,
    });
    setError("");
    setShowForm(true);
  };

  const parseSettings = (): Record<string, unknown> | null => {
    try {
      const value: unknown = JSON.parse(form.settings || "{}");
      if (!value || Array.isArray(value) || typeof value !== "object") {
        setError("La configuración debe ser un objeto JSON.");
        return null;
      }
      return value as Record<string, unknown>;
    } catch {
      setError("La configuración no contiene JSON válido.");
      return null;
    }
  };

  const save = async () => {
    const settings = parseSettings();
    if (!settings) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const whatsappSecretParts = [form.accessToken, form.verifyToken, form.appSecret];
      if (
        kind === "channel" &&
        form.channel === "whatsapp" &&
        whatsappSecretParts.some(Boolean) &&
        !whatsappSecretParts.every(Boolean)
      ) {
        setError("Para rotar WhatsApp completá access token, verify token y app secret.");
        setSaving(false);
        return;
      }
      const credentials =
        kind === "provider"
          ? form.apiKey
            ? { api_key: form.apiKey }
            : undefined
          : form.channel === "whatsapp" && whatsappSecretParts.every(Boolean)
            ? {
                access_token: form.accessToken,
                verify_token: form.verifyToken,
                app_secret: form.appSecret,
              }
            : undefined;
      const common = {
        name: form.name.trim(),
        settings,
        is_active: form.isActive,
        ...(credentials && { credentials }),
      };
      if (editing) {
        const body =
          kind === "provider"
            ? { ...common, base_url: form.baseUrl.trim() || null }
            : { ...common, external_account_id: form.externalAccountId.trim() || null };
        await api(`${endpoint}/${editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
      } else {
        const body =
          kind === "provider"
            ? {
                ...common,
                slug: form.slug.trim(),
                provider_type: "openai",
                base_url: form.baseUrl.trim() || null,
              }
            : {
                ...common,
                slug: form.slug.trim(),
                channel: form.channel,
                external_account_id: form.externalAccountId.trim() || null,
              };
        await api(endpoint, { method: "POST", body: JSON.stringify(body) });
      }
      setShowForm(false);
      setEditing(null);
      setForm(emptyForm());
      setNotice(
        editing
          ? credentials
            ? "Conexión actualizada y secreto rotado."
            : "Conexión actualizada; el secreto existente no fue leído ni modificado."
          : "Conexión creada. El secreto quedó almacenado como write-only.",
      );
      await load();
      requestAnimationFrame(() => returnFocus.current?.focus());
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo guardar la conexión.");
    } finally {
      setSaving(false);
    }
  };

  const testProvider = async (connection: Connection) => {
    if (kind !== "provider") return;
    setTestingId(connection.id);
    setNotice("");
    setError("");
    try {
      const result = await api<{ ok: boolean; duration_ms: number; error_code?: string | null }>(
        `${endpoint}/${connection.id}/test`,
        { method: "POST" },
      );
      setNotice(
        result.ok
          ? `Proveedor disponible · ${result.duration_ms} ms.`
          : `La prueba falló (${result.error_code || "error_desconocido"}) · ${result.duration_ms} ms.`,
      );
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo probar el proveedor.");
    } finally {
      setTestingId(null);
    }
  };

  const clearCredentials = async (connection: Connection) => {
    if (!window.confirm(`¿Eliminar definitivamente el secreto de ${connection.name}?`)) return;
    setBusyId(connection.id);
    setNotice("");
    setError("");
    try {
      await api(`${endpoint}/${connection.id}`, {
        method: "PATCH",
        body: JSON.stringify({ clear_credentials: true }),
      });
      setNotice("Secreto eliminado. La conexión no podrá autenticar hasta que cargues uno nuevo.");
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo eliminar el secreto.");
    } finally {
      setBusyId(null);
    }
  };

  const deactivate = async (connection: Connection) => {
    if (!window.confirm(`¿Desactivar la conexión ${connection.name}?`)) return;
    setBusyId(connection.id);
    setNotice("");
    setError("");
    try {
      await api(`${endpoint}/${connection.id}/deactivate`, { method: "POST" });
      setNotice("Conexión desactivada. Las dependencias existentes pueden quedar sin servicio.");
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo desactivar la conexión.");
    } finally {
      setBusyId(null);
    }
  };

  const title = kind === "provider" ? "Conexiones de IA" : "Conexiones de canal";
  const description =
    kind === "provider"
      ? "Proveedores compartidos para los runtimes. Las API keys son write-only."
      : "Cuentas web y WhatsApp compartidas que pueden vincularse a rutas de agentes.";
  const Icon = kind === "provider" ? CloudCog : Cable;

  return (
    <div className="max-w-7xl space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <Icon className="text-[var(--accent)]" size={22} />
        <div>
          <h2 className="text-xl font-semibold">{title}</h2>
          <p className="text-sm text-[var(--text-muted)]">{description}</p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={openCreate}
            className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white"
          >
            <Plus size={16} /> Nueva conexión
          </button>
        )}
      </header>
      {error && !showForm && (
        <p
          className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400"
          role="alert"
        >
          {error}
        </p>
      )}
      {notice && (
        <p
          className="rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-3 text-sm"
          role="status"
        >
          {notice}
        </p>
      )}
      {loading ? (
        <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status">
          <LoaderCircle className="animate-spin" size={16} /> Cargando conexiones…
        </p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {rows.map((connection) => (
            <article
              key={connection.id}
              className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
            >
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{connection.name}</h3>
                    <code className="text-xs text-[var(--text-muted)]">{connection.slug}</code>
                  </div>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    {isChannel(connection) ? connection.channel : connection.provider_type}
                  </p>
                </div>
                <span
                  className={`rounded px-2 py-1 text-xs ${connection.is_active ? "bg-emerald-500/10 text-emerald-400" : "bg-[var(--bg-hover)] text-[var(--text-muted)]"}`}
                >
                  {connection.is_active ? "Activa" : "Inactiva"}
                </span>
              </div>
              <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
                <div>
                  <dt className="text-[var(--text-muted)]">Credencial</dt>
                  <dd className="mt-1 flex items-center gap-1">
                    {isChannel(connection) && connection.channel === "web" ? (
                      <>
                        <CheckCircle2 size={13} className="text-[var(--text-muted)]" />
                        No aplica al canal web
                      </>
                    ) : (
                      <>
                        {connection.has_credentials ? (
                          <CheckCircle2 size={13} className="text-emerald-400" />
                        ) : (
                          <KeyRound size={13} className="text-amber-400" />
                        )}
                        {connection.has_credentials ? "Configurada (write-only)" : "Sin configurar"}
                      </>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[var(--text-muted)]">Cuenta o endpoint</dt>
                  <dd
                    className="mt-1 truncate"
                    title={
                      isChannel(connection)
                        ? connection.external_account_id || undefined
                        : connection.base_url || undefined
                    }
                  >
                    {isChannel(connection)
                      ? connection.external_account_id || "No informado"
                      : connection.base_url || "Predeterminado del proveedor"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[var(--text-muted)]">Configuración</dt>
                  <dd className="mt-1">
                    {Object.keys(connection.settings || {}).length} propiedades
                  </dd>
                </div>
                <div>
                  <dt className="text-[var(--text-muted)]">Actualizada por</dt>
                  <dd className="mt-1 truncate">{connection.updated_by || "Sistema"}</dd>
                </div>
              </dl>
              {canManage && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => openEdit(connection)}
                    className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-1.5 text-xs"
                  >
                    <Pencil size={14} /> Editar o rotar
                  </button>
                  {kind === "provider" && (
                    <button
                      type="button"
                      onClick={() => testProvider(connection)}
                      disabled={testingId === connection.id}
                      className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-1.5 text-xs"
                    >
                      <RotateCw
                        className={testingId === connection.id ? "animate-spin" : ""}
                        size={14}
                      />{" "}
                      Probar conexión
                    </button>
                  )}
                  {connection.has_credentials &&
                    !(isChannel(connection) && connection.channel === "web") && (
                      <button
                        type="button"
                        onClick={() => clearCredentials(connection)}
                        disabled={busyId === connection.id}
                        className="flex items-center gap-1 rounded border border-amber-500/40 px-2 py-1.5 text-xs text-amber-300"
                      >
                        <Trash2 size={14} /> Eliminar secreto
                      </button>
                    )}
                  {connection.is_active && (
                    <button
                      type="button"
                      onClick={() => deactivate(connection)}
                      disabled={busyId === connection.id}
                      className="flex items-center gap-1 rounded border border-red-500/40 px-2 py-1.5 text-xs text-red-400"
                    >
                      <PowerOff size={14} /> Desactivar
                    </button>
                  )}
                </div>
              )}
            </article>
          ))}
          {rows.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">
              Todavía no hay conexiones configuradas.
            </p>
          )}
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            className="absolute inset-0 cursor-default"
            onClick={closeForm}
          />
          <section
            className="relative max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="connection-form-title"
          >
            <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--border-color)] bg-[var(--bg-card)] p-4">
              <h3 id="connection-form-title" className="font-semibold">
                {editing
                  ? "Editar conexión compartida"
                  : `Nueva ${kind === "provider" ? "conexión de IA" : "conexión de canal"}`}
              </h3>
              <button type="button" onClick={closeForm} aria-label="Cerrar">
                <X size={18} />
              </button>
            </header>
            <div className="grid gap-4 p-4 md:grid-cols-2">
              <label className="text-xs">
                Nombre
                <input
                  ref={initialInput}
                  className={`${INPUT} mt-1`}
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                />
              </label>
              <label className="text-xs">
                Slug
                <input
                  disabled={Boolean(editing)}
                  className={`${INPUT} mt-1 disabled:opacity-60`}
                  value={form.slug}
                  onChange={(event) => setForm({ ...form, slug: event.target.value })}
                  placeholder="openai-principal"
                />
              </label>
              {kind === "provider" ? (
                <label className="text-xs md:col-span-2">
                  URL base opcional
                  <input
                    className={`${INPUT} mt-1 font-mono`}
                    value={form.baseUrl}
                    onChange={(event) => setForm({ ...form, baseUrl: event.target.value })}
                    placeholder="https://api.openai.com/v1"
                  />
                </label>
              ) : (
                <>
                  <label className="text-xs">
                    Canal
                    <select
                      disabled={Boolean(editing)}
                      className={`${INPUT} mt-1 disabled:opacity-60`}
                      value={form.channel}
                      onChange={(event) =>
                        setForm({ ...form, channel: event.target.value as ChannelKind })
                      }
                    >
                      <option value="web">Web</option>
                      <option value="whatsapp">WhatsApp</option>
                    </select>
                  </label>
                  <label className="text-xs">
                    ID de cuenta externa
                    <input
                      className={`${INPUT} mt-1 font-mono`}
                      value={form.externalAccountId}
                      onChange={(event) =>
                        setForm({ ...form, externalAccountId: event.target.value })
                      }
                    />
                  </label>
                </>
              )}
              {kind === "provider" && (
                <label className="text-xs md:col-span-2">
                  <span className="flex items-center gap-1">
                    <KeyRound size={13} />
                    {editing
                      ? "Nueva API key (vacío conserva el secreto actual)"
                      : "API key opcional"}
                  </span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    className={`${INPUT} mt-1`}
                    value={form.apiKey}
                    onChange={(event) => setForm({ ...form, apiKey: event.target.value })}
                  />
                  <span className="mt-1 block text-[var(--text-muted)]">
                    El servidor sólo informa si existe; nunca devuelve su valor.
                  </span>
                </label>
              )}
              {kind === "channel" && form.channel === "whatsapp" && (
                <fieldset className="grid gap-3 rounded border border-[var(--border-color)] p-3 md:col-span-2">
                  <legend className="px-1 text-xs font-medium">
                    Credenciales de WhatsApp write-only
                  </legend>
                  <label className="text-xs">
                    Access token
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={`${INPUT} mt-1`}
                      value={form.accessToken}
                      onChange={(event) => setForm({ ...form, accessToken: event.target.value })}
                    />
                  </label>
                  <label className="text-xs">
                    Verify token
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={`${INPUT} mt-1`}
                      value={form.verifyToken}
                      onChange={(event) => setForm({ ...form, verifyToken: event.target.value })}
                    />
                  </label>
                  <label className="text-xs">
                    App secret
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={`${INPUT} mt-1`}
                      value={form.appSecret}
                      onChange={(event) => setForm({ ...form, appSecret: event.target.value })}
                    />
                  </label>
                  <p className="text-xs text-[var(--text-muted)]">
                    Para rotar, completá los tres valores. Vacíos conservan el secreto existente.
                  </p>
                </fieldset>
              )}
              {kind === "channel" && form.channel === "web" && (
                <p className="rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 text-xs text-[var(--text-muted)] md:col-span-2">
                  El canal web no admite ni necesita credenciales.
                </p>
              )}
              <label className="text-xs md:col-span-2">
                Configuración JSON
                <textarea
                  rows={7}
                  spellCheck={false}
                  className={`${INPUT} mt-1 resize-y font-mono`}
                  value={form.settings}
                  onChange={(event) => setForm({ ...form, settings: event.target.value })}
                />
                <span className="mt-1 block text-[var(--text-muted)]">
                  Este JSON es visible para administradores. No guardes tokens ni secretos acá.
                </span>
              </label>
              <label className="flex items-center gap-2 text-sm md:col-span-2">
                <input
                  type="checkbox"
                  checked={form.isActive}
                  onChange={(event) => setForm({ ...form, isActive: event.target.checked })}
                />{" "}
                Conexión activa
              </label>
              {error && (
                <p className="text-sm text-red-400 md:col-span-2" role="alert">
                  {error}
                </p>
              )}
            </div>
            <footer className="flex flex-wrap justify-end gap-2 border-t border-[var(--border-color)] p-4">
              <button
                type="button"
                onClick={closeForm}
                className="rounded border border-[var(--border-color)] px-3 py-2 text-sm"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50"
              >
                {saving ? (
                  <LoaderCircle className="animate-spin" size={15} />
                ) : editing && (form.apiKey || form.accessToken) ? (
                  <RotateCw size={15} />
                ) : (
                  <CheckCircle2 size={15} />
                )}{" "}
                Guardar
              </button>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}

export function ProviderConnectionsPage(): ReactNode {
  return <ConnectionLibraryPage kind="provider" />;
}

export function ChannelConnectionsPage(): ReactNode {
  return <ConnectionLibraryPage kind="channel" />;
}

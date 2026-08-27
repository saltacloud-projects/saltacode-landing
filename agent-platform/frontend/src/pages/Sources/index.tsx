import { useState } from "react";
import { Cable, CheckCircle2, KeyRound, LoaderCircle, Pencil, Plus, TestTube2, Trash2, X } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAgentResourceLibrary } from "../../agents/useAgentResourceLibrary";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface Source {
  id: string;
  name: string;
  slug: string;
  source_type: string;
  base_url: string;
  allowed_hosts: string[];
  auth_type: string;
  auth_config: Record<string, unknown>;
  default_headers: Record<string, string>;
  has_credentials: boolean;
  is_active: boolean;
  is_public: boolean;
  verify_tls: boolean;
  allow_private_network: boolean;
  timeout_seconds: number;
  max_response_bytes: number;
}

interface HeaderRow { name: string; value: string }
interface SourceForm {
  name: string;
  slug: string;
  base_url: string;
  allowed_hosts: string;
  auth_type: string;
  credential_username: string;
  credential_password: string;
  credential_value: string;
  api_key_name: string;
  api_key_location: "header" | "query";
  headers: HeaderRow[];
  clear_credentials: boolean;
  is_active: boolean;
  is_public: boolean;
  verify_tls: boolean;
  allow_private_network: boolean;
  timeout_seconds: number;
  max_response_bytes: number;
}

const emptyForm = (): SourceForm => ({
  name: "", slug: "", base_url: "https://", allowed_hosts: "", auth_type: "none",
  credential_username: "", credential_password: "", credential_value: "",
  api_key_name: "X-API-Key", api_key_location: "header", headers: [], clear_credentials: false,
  is_active: true, is_public: false, verify_tls: true, allow_private_network: false,
  timeout_seconds: 30, max_response_bytes: 2_000_000,
});
const INPUT = "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";

function credentials(form: SourceForm): Record<string, string> | undefined {
  if (form.auth_type === "none" || form.clear_credentials) return undefined;
  if (form.auth_type === "basic") {
    if (!form.credential_username && !form.credential_password) return undefined;
    return { username: form.credential_username, password: form.credential_password };
  }
  if (!form.credential_value) return undefined;
  return form.auth_type === "api_key" ? { value: form.credential_value } : { token: form.credential_value };
}

export default function SourcesPage({ scope = "agent" }: { scope?: "agent" | "library" }) {
  const { user } = useAuth();
  const { selectedAgent } = useAgentWorkspace();
  const agentId = scope === "agent" ? selectedAgent?.id : undefined;
  const resources = useAgentResourceLibrary<Source>(agentId, "sources", "/sources/");
  const canManage = hasPermission(user, PERMISSIONS.SOURCES_MANAGE);
  const [editing, setEditing] = useState<Source | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<SourceForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testPaths, setTestPaths] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const openCreate = () => { setEditing(null); setForm(emptyForm()); setError(""); setShowForm(true); };
  const closeForm = () => { if (saving) return; setEditing(null); setShowForm(false); setForm(emptyForm()); };
  const openEdit = (source: Source) => {
    setEditing(source);
    setForm({
      ...emptyForm(), name: source.name, slug: source.slug, base_url: source.base_url,
      allowed_hosts: source.allowed_hosts.join(", "), auth_type: source.auth_type,
      api_key_name: String(source.auth_config.name || "X-API-Key"),
      api_key_location: source.auth_config.in === "query" ? "query" : "header",
      headers: Object.entries(source.default_headers || {}).map(([name, value]) => ({ name, value })),
      is_active: source.is_active, is_public: source.is_public, verify_tls: source.verify_tls,
      allow_private_network: source.allow_private_network, timeout_seconds: source.timeout_seconds,
      max_response_bytes: source.max_response_bytes,
    });
    setError("");
    setShowForm(true);
  };

  const save = async () => {
    setError("");
    const duplicateHeaders = form.headers.map((header) => header.name.trim().toLowerCase()).filter(Boolean);
    if (new Set(duplicateHeaders).size !== duplicateHeaders.length) return setError("Los nombres de headers no pueden repetirse.");
    setSaving(true);
    try {
      const auth_config = form.auth_type === "api_key" ? { name: form.api_key_name, in: form.api_key_location } : {};
      const default_headers = Object.fromEntries(form.headers.filter((header) => header.name.trim()).map((header) => [header.name.trim(), header.value]));
      const body: Record<string, unknown> = {
        name: form.name.trim(), base_url: form.base_url.trim(),
        allowed_hosts: form.allowed_hosts.split(",").map((value) => value.trim()).filter(Boolean),
        auth_type: form.auth_type, auth_config, default_headers,
        is_active: form.is_active, is_public: form.is_public, verify_tls: form.verify_tls,
        allow_private_network: form.allow_private_network,
        timeout_seconds: Number(form.timeout_seconds), max_response_bytes: Number(form.max_response_bytes),
      };
      const secret = credentials(form);
      if (secret) body.credentials = secret;
      if (editing && form.clear_credentials) body.clear_credentials = true;

      if (editing) {
        await api(`/sources/${editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
      } else {
        const created = await api<Source>("/sources/", { method: "POST", body: JSON.stringify({ ...body, slug: form.slug.trim(), source_type: "http" }) });
        if (agentId) await api(`/agents/${agentId}/sources/${created.id}`, { method: "PUT" });
      }
      setEditing(null);
      setShowForm(false);
      setForm(emptyForm());
      setNotice(agentId && !editing ? "Fuente creada en la biblioteca y asignada al agente." : "Fuente guardada. Los secretos son write-only y no vuelven a mostrarse.");
      await resources.refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo guardar la fuente.");
    } finally {
      setSaving(false);
    }
  };

  const testSource = async (source: Source) => {
    const path = (testPaths[source.id] || "/").trim();
    if (!path.startsWith("/")) return setNotice("La ruta de prueba debe comenzar con '/'.");
    setTesting(source.id); setNotice("");
    try {
      const result = await api<{ ok: boolean; status_code: number | null; error_code: string | null }>(`/sources/${source.id}/test`, { method: "POST", body: JSON.stringify({ path }) });
      setNotice(result.ok ? `Conexión válida${result.status_code ? ` · HTTP ${result.status_code}` : ""}.` : `Falló la prueba: ${result.error_code || "sin respuesta"}.`);
    } catch (value) {
      setNotice(value instanceof Error ? value.message : "No se pudo probar la fuente.");
    } finally { setTesting(null); }
  };

  const SourceCard = ({ source, assignment }: { source: Source; assignment?: "assigned" | "available" }) => (
    <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
      <div className="flex items-start gap-3"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h4 className="font-semibold">{source.name}</h4><code className="text-xs text-[var(--text-muted)]">{source.slug}</code></div><p className="mt-1 truncate text-xs text-[var(--text-secondary)]" title={source.base_url}>{source.base_url}</p></div><span className={`rounded px-2 py-1 text-xs ${source.is_active ? "bg-[var(--success)]/15 text-[var(--success)]" : "bg-[var(--bg-hover)] text-[var(--text-muted)]"}`}>{source.is_active ? "Activa" : "Inactiva"}</span></div>
      <dl className="mt-4 grid grid-cols-2 gap-2 text-xs"><div><dt className="text-[var(--text-muted)]">Autenticación</dt><dd>{source.auth_type} {source.has_credentials && "· configurada"}</dd></div><div><dt className="text-[var(--text-muted)]">Headers</dt><dd>{Object.keys(source.default_headers || {}).length}</dd></div><div><dt className="text-[var(--text-muted)]">Exposición</dt><dd>{source.is_public ? "Web permitida" : "Canales privados"}</dd></div><div><dt className="text-[var(--text-muted)]">TLS</dt><dd>{source.verify_tls ? "Verificado" : "Desactivado"}</dd></div></dl>
      {canManage && <div className="mt-4 flex flex-wrap items-end gap-2"><label className="min-w-32 flex-1 text-[11px] text-[var(--text-muted)]">Ruta de prueba (GET)<input aria-label={`Ruta de prueba para ${source.name}`} className={`${INPUT} mt-1 py-1.5 font-mono text-xs`} value={testPaths[source.id] || "/"} onChange={(event) => setTestPaths({ ...testPaths, [source.id]: event.target.value })} /></label><button onClick={() => testSource(source)} disabled={testing === source.id} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-2 text-xs"><TestTube2 size={14} /> Probar</button><button onClick={() => openEdit(source)} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-2 text-xs"><Pencil size={14} /> Editar biblioteca</button>{assignment === "assigned" && <button onClick={() => resources.unassign(source.id)} disabled={resources.busyId === source.id} className="rounded border border-amber-500/40 px-2 py-2 text-xs text-amber-300">Desasignar</button>}{assignment === "available" && <button onClick={() => resources.assign(source.id)} disabled={resources.busyId === source.id} className="rounded bg-[var(--accent)] px-2 py-2 text-xs text-white">Asignar</button>}</div>}
    </article>
  );

  return (
    <div className="max-w-7xl space-y-6">
      <header className="flex flex-wrap items-center gap-3"><Cable className="text-[var(--accent)]" size={22} /><div><h2 className="text-xl font-semibold">{agentId ? `Fuentes de ${selectedAgent?.name}` : "Biblioteca de fuentes"}</h2><p className="text-sm text-[var(--text-muted)]">{agentId ? "Asigná APIs compartidas a este agente. Los cambios de una fuente afectan a todos sus consumidores." : "APIs y credenciales cifradas disponibles para asignar a agentes."}</p></div>{canManage && <button onClick={openCreate} className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white"><Plus size={16} /> Nueva fuente</button>}</header>
      {(error || resources.error) && <p className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error || resources.error}</p>}
      {notice && <p className="rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-3 text-sm" role="status">{notice}</p>}
      {resources.loading ? <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status"><LoaderCircle className="animate-spin" size={16} /> Cargando fuentes…</p> : agentId ? <>
        <section><h3 className="mb-3 font-semibold">Asignadas ({resources.assigned.length})</h3><div className="grid gap-3 lg:grid-cols-2">{resources.assigned.map((source) => <SourceCard key={source.id} source={source} assignment="assigned" />)}{resources.assigned.length === 0 && <p className="text-sm text-[var(--text-muted)]">Este agente todavía no tiene fuentes asignadas.</p>}</div></section>
        <section><h3 className="mb-3 font-semibold">Disponibles en la biblioteca ({resources.available.length})</h3><div className="grid gap-3 lg:grid-cols-2">{resources.available.map((source) => <SourceCard key={source.id} source={source} assignment="available" />)}{resources.available.length === 0 && <p className="text-sm text-[var(--text-muted)]">No quedan fuentes disponibles para asignar.</p>}</div></section>
      </> : <div className="grid gap-3 lg:grid-cols-2">{resources.library.map((source) => <SourceCard key={source.id} source={source} />)}{resources.library.length === 0 && <p className="text-sm text-[var(--text-muted)]">Todavía no hay fuentes configuradas.</p>}</div>}

      {showForm && <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) closeForm(); }}><section className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="source-title"><header className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--border-color)] bg-[var(--bg-card)] p-4"><h3 id="source-title" className="font-semibold">{editing ? "Editar fuente compartida" : "Nueva fuente HTTP"}</h3><button aria-label="Cerrar" onClick={closeForm}><X size={18} /></button></header><div className="grid gap-4 p-4 md:grid-cols-2">
        <label className="text-xs">Nombre<input className={`${INPUT} mt-1`} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className="text-xs">Slug<input disabled={Boolean(editing)} className={`${INPUT} mt-1 disabled:opacity-60`} value={form.slug} onChange={(event) => setForm({ ...form, slug: event.target.value })} placeholder="crm-comercial" /></label><label className="text-xs md:col-span-2">URL base<input className={`${INPUT} mt-1 font-mono`} value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /></label><label className="text-xs md:col-span-2">Hosts permitidos, separados por coma<input className={`${INPUT} mt-1 font-mono`} value={form.allowed_hosts} onChange={(event) => setForm({ ...form, allowed_hosts: event.target.value })} placeholder="api.example.com" /></label>
        <label className="text-xs">Autenticación<select className={`${INPUT} mt-1`} value={form.auth_type} onChange={(event) => setForm({ ...form, auth_type: event.target.value, clear_credentials: false })}><option value="none">Sin autenticación</option><option value="bearer">Bearer</option><option value="token">Token</option><option value="api_key">API key</option><option value="basic">Basic</option></select></label>
        {form.auth_type === "basic" ? <><label className="text-xs">Usuario<input className={`${INPUT} mt-1`} autoComplete="off" value={form.credential_username} onChange={(event) => setForm({ ...form, credential_username: event.target.value, clear_credentials: false })} /></label><label className="text-xs">Contraseña<input type="password" className={`${INPUT} mt-1`} autoComplete="new-password" value={form.credential_password} onChange={(event) => setForm({ ...form, credential_password: event.target.value, clear_credentials: false })} /></label></> : form.auth_type !== "none" && <label className="text-xs"><span className="flex items-center gap-1"><KeyRound size={13} />{editing ? "Nuevo secreto (vacío conserva el actual)" : "Secreto"}</span><input type="password" className={`${INPUT} mt-1`} autoComplete="new-password" value={form.credential_value} onChange={(event) => setForm({ ...form, credential_value: event.target.value, clear_credentials: false })} /></label>}
        {form.auth_type === "api_key" && <><label className="text-xs">Nombre de API key<input className={`${INPUT} mt-1`} value={form.api_key_name} onChange={(event) => setForm({ ...form, api_key_name: event.target.value })} /></label><label className="text-xs">Ubicación<select className={`${INPUT} mt-1`} value={form.api_key_location} onChange={(event) => setForm({ ...form, api_key_location: event.target.value as "header" | "query" })}><option value="header">Header</option><option value="query">Query</option></select></label></>}
        {editing?.has_credentials && <label className="flex items-center gap-2 text-sm md:col-span-2"><input type="checkbox" checked={form.clear_credentials} onChange={(event) => setForm({ ...form, clear_credentials: event.target.checked, credential_value: "", credential_password: "", credential_username: "" })} /> Eliminar las credenciales guardadas</label>}
        <fieldset className="space-y-2 md:col-span-2"><legend className="text-xs font-medium">Headers por defecto sin secretos</legend>{form.headers.map((header, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"><input aria-label={`Nombre del header ${index + 1}`} className={`${INPUT} font-mono`} value={header.name} onChange={(event) => setForm({ ...form, headers: form.headers.map((row, position) => position === index ? { ...row, name: event.target.value } : row) })} placeholder="Accept" /><input aria-label={`Valor del header ${index + 1}`} className={`${INPUT} font-mono`} value={header.value} onChange={(event) => setForm({ ...form, headers: form.headers.map((row, position) => position === index ? { ...row, value: event.target.value } : row) })} placeholder="application/json" /><button aria-label={`Quitar header ${index + 1}`} onClick={() => setForm({ ...form, headers: form.headers.filter((_, position) => position !== index) })} className="rounded border border-[var(--border-color)] p-2 text-red-400"><Trash2 size={15} /></button></div>)}<button onClick={() => setForm({ ...form, headers: [...form.headers, { name: "", value: "" }] })} className="rounded border border-[var(--border-color)] px-2 py-1.5 text-xs">Agregar header</button><p className="text-xs text-[var(--text-muted)]">Authorization, cookies y otros secretos deben configurarse en Autenticación.</p></fieldset>
        <label className="text-xs">Timeout (segundos)<input type="number" min={1} max={120} className={`${INPUT} mt-1`} value={form.timeout_seconds} onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })} /></label><label className="text-xs">Respuesta máxima (bytes)<input type="number" min={1024} className={`${INPUT} mt-1`} value={form.max_response_bytes} onChange={(event) => setForm({ ...form, max_response_bytes: Number(event.target.value) })} /></label>
        <fieldset className="grid gap-2 text-sm md:col-span-2"><legend className="mb-2 text-xs text-[var(--text-muted)]">Política compartida</legend><label><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} /> <span className="ml-2">Fuente activa</span></label><label><input type="checkbox" checked={form.is_public} onChange={(event) => setForm({ ...form, is_public: event.target.checked })} /> <span className="ml-2">Disponible para canal web</span></label><label><input type="checkbox" checked={form.verify_tls} onChange={(event) => setForm({ ...form, verify_tls: event.target.checked })} /> <span className="ml-2">Verificar certificado TLS</span></label><label><input type="checkbox" checked={form.allow_private_network} onChange={(event) => setForm({ ...form, allow_private_network: event.target.checked })} /> <span className="ml-2">Permitir red privada controlada</span></label></fieldset>
        {error && <p className="text-sm text-[var(--error)] md:col-span-2" role="alert">{error}</p>}
      </div><footer className="flex justify-end gap-2 border-t border-[var(--border-color)] p-4"><button onClick={closeForm} className="rounded border border-[var(--border-color)] px-3 py-2 text-sm">Cancelar</button><button onClick={save} disabled={saving} className="flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50">{saving ? <LoaderCircle className="animate-spin" size={15} /> : <CheckCircle2 size={15} />} Guardar</button></footer></section></div>}
    </div>
  );
}

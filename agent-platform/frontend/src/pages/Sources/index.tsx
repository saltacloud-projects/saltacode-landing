import { useEffect, useState } from "react";
import { Cable, CheckCircle2, LoaderCircle, Pencil, Plus, TestTube2, X } from "lucide-react";
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
  is_active: boolean;
  is_public: boolean;
  verify_tls: boolean;
  allow_private_network: boolean;
  timeout_seconds: number;
  max_response_bytes: number;
}

const EMPTY: SourceForm = {
  name: "",
  slug: "",
  base_url: "https://",
  allowed_hosts: "",
  auth_type: "none",
  credential_username: "",
  credential_password: "",
  credential_value: "",
  api_key_name: "X-API-Key",
  api_key_location: "header",
  is_active: true,
  is_public: false,
  verify_tls: true,
  allow_private_network: false,
  timeout_seconds: 30,
  max_response_bytes: 2_000_000,
};

const INPUT = "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";

function credentials(form: SourceForm): Record<string, string> | undefined {
  if (form.auth_type === "none") return undefined;
  if (form.auth_type === "basic") {
    if (!form.credential_username && !form.credential_password) return undefined;
    return { username: form.credential_username, password: form.credential_password };
  }
  if (!form.credential_value) return undefined;
  return form.auth_type === "api_key" ? { value: form.credential_value } : { token: form.credential_value };
}

export default function SourcesPage() {
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.SOURCES_MANAGE);
  const [items, setItems] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Source | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<SourceForm>({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = () => api<Source[]>("/sources/").then(setItems);
  useEffect(() => { load().finally(() => setLoading(false)); }, []);

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY });
    setError("");
    setShowForm(true);
  };

  const openEdit = (source: Source) => {
    setEditing(source);
    setForm({
      ...EMPTY,
      name: source.name,
      slug: source.slug,
      base_url: source.base_url,
      allowed_hosts: source.allowed_hosts.join(", "),
      auth_type: source.auth_type,
      api_key_name: String(source.auth_config.name || "X-API-Key"),
      api_key_location: source.auth_config.in === "query" ? "query" : "header",
      is_active: source.is_active,
      is_public: source.is_public,
      verify_tls: source.verify_tls,
      allow_private_network: source.allow_private_network,
      timeout_seconds: source.timeout_seconds,
      max_response_bytes: source.max_response_bytes,
    });
    setError("");
    setShowForm(true);
  };

  const save = async () => {
    setError("");
    setSaving(true);
    try {
      const auth_config = form.auth_type === "api_key"
        ? { name: form.api_key_name, in: form.api_key_location }
        : {};
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        base_url: form.base_url.trim(),
        allowed_hosts: form.allowed_hosts.split(",").map((value) => value.trim()).filter(Boolean),
        auth_type: form.auth_type,
        auth_config,
        is_active: form.is_active,
        is_public: form.is_public,
        verify_tls: form.verify_tls,
        allow_private_network: form.allow_private_network,
        timeout_seconds: Number(form.timeout_seconds),
        max_response_bytes: Number(form.max_response_bytes),
      };
      const secret = credentials(form);
      if (secret) body.credentials = secret;
      if (editing) {
        await api(`/sources/${editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
      } else {
        await api("/sources/", {
          method: "POST",
          body: JSON.stringify({ ...body, slug: form.slug.trim(), source_type: "http" }),
        });
      }
      setEditing(null);
      setShowForm(false);
      setForm({ ...EMPTY });
      setNotice("Fuente guardada. Las credenciales nunca se vuelven a mostrar.");
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo guardar la fuente.");
    } finally {
      setSaving(false);
    }
  };

  const testSource = async (source: Source) => {
    setTesting(source.id);
    setNotice("");
    try {
      const result = await api<{ ok: boolean; status_code: number | null; error_code: string | null }>(`/sources/${source.id}/test`, {
        method: "POST",
        body: JSON.stringify({ path: "/" }),
      });
      setNotice(result.ok ? `Conexión válida${result.status_code ? ` · HTTP ${result.status_code}` : ""}.` : `Falló la prueba: ${result.error_code || "sin respuesta"}.`);
    } catch (value) {
      setNotice(value instanceof Error ? value.message : "No se pudo probar la fuente.");
    } finally {
      setTesting(null);
    }
  };

  return (
    <div className="max-w-6xl">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <Cable className="text-[var(--accent)]" size={22} />
        <div>
          <h2 className="text-xl font-semibold">Fuentes de integración</h2>
          <p className="text-sm text-[var(--text-muted)]">APIs y credenciales cifradas que pueden usar las herramientas.</p>
        </div>
        {canManage && <button onClick={openCreate} className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white"><Plus size={16} /> Nueva fuente</button>}
      </header>

      {notice && <p className="mb-4 rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-3 text-sm">{notice}</p>}
      {loading ? <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]"><LoaderCircle className="animate-spin" size={16} /> Cargando fuentes…</p> : (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((source) => (
            <article key={source.id} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{source.name}</h3><code className="text-xs text-[var(--text-muted)]">{source.slug}</code></div>
                  <p className="mt-1 truncate text-xs text-[var(--text-secondary)]" title={source.base_url}>{source.base_url}</p>
                </div>
                <span className={`rounded px-2 py-1 text-xs ${source.is_active ? "bg-[var(--success)]/15 text-[var(--success)]" : "bg-[var(--bg-hover)] text-[var(--text-muted)]"}`}>{source.is_active ? "Activa" : "Inactiva"}</span>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <div><dt className="text-[var(--text-muted)]">Autenticación</dt><dd>{source.auth_type} {source.has_credentials && "· configurada"}</dd></div>
                <div><dt className="text-[var(--text-muted)]">Exposición</dt><dd>{source.is_public ? "Web pública permitida" : "Canales privados"}</dd></div>
                <div><dt className="text-[var(--text-muted)]">TLS</dt><dd>{source.verify_tls ? "Verificado" : "Desactivado"}</dd></div>
                <div><dt className="text-[var(--text-muted)]">Red privada</dt><dd>{source.allow_private_network ? "Permitida" : "Bloqueada"}</dd></div>
              </dl>
              {canManage && <div className="mt-4 flex gap-2"><button onClick={() => testSource(source)} disabled={testing === source.id} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-1.5 text-xs"><TestTube2 size={14} /> Probar</button><button onClick={() => openEdit(source)} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-1.5 text-xs"><Pencil size={14} /> Editar</button></div>}
            </article>
          ))}
          {items.length === 0 && <p className="text-sm text-[var(--text-muted)]">Todavía no hay fuentes configuradas.</p>}
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) { setEditing(null); setShowForm(false); setForm({ ...EMPTY }); } }}>
          <section className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="source-title">
            <header className="sticky top-0 flex items-center justify-between border-b border-[var(--border-color)] bg-[var(--bg-card)] p-4"><h3 id="source-title" className="font-semibold">{editing ? "Editar fuente" : "Nueva fuente"}</h3><button aria-label="Cerrar" onClick={() => { setEditing(null); setShowForm(false); setForm({ ...EMPTY }); }}><X size={18} /></button></header>
            <div className="grid gap-4 p-4 md:grid-cols-2">
              <label className="text-xs">Nombre<input className={`${INPUT} mt-1`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
              <label className="text-xs">Slug<input disabled={Boolean(editing)} className={`${INPUT} mt-1 disabled:opacity-60`} value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} placeholder="crm-comercial" /></label>
              <label className="text-xs md:col-span-2">URL base<input className={`${INPUT} mt-1 font-mono`} value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></label>
              <label className="text-xs md:col-span-2">Hosts permitidos, separados por coma<input className={`${INPUT} mt-1 font-mono`} value={form.allowed_hosts} onChange={(e) => setForm({ ...form, allowed_hosts: e.target.value })} placeholder="api.example.com" /></label>
              <label className="text-xs">Autenticación<select className={`${INPUT} mt-1`} value={form.auth_type} onChange={(e) => setForm({ ...form, auth_type: e.target.value })}><option value="none">Sin autenticación</option><option value="bearer">Bearer</option><option value="token">Token</option><option value="api_key">API key</option><option value="basic">Basic</option></select></label>
              {form.auth_type === "basic" ? <><label className="text-xs">Usuario<input className={`${INPUT} mt-1`} autoComplete="off" value={form.credential_username} onChange={(e) => setForm({ ...form, credential_username: e.target.value })} /></label><label className="text-xs">Contraseña<input type="password" className={`${INPUT} mt-1`} autoComplete="new-password" value={form.credential_password} onChange={(e) => setForm({ ...form, credential_password: e.target.value })} /></label></> : form.auth_type !== "none" && <label className="text-xs">{editing ? "Nuevo secreto (dejar vacío conserva el actual)" : "Secreto"}<input type="password" className={`${INPUT} mt-1`} autoComplete="new-password" value={form.credential_value} onChange={(e) => setForm({ ...form, credential_value: e.target.value })} /></label>}
              {form.auth_type === "api_key" && <><label className="text-xs">Nombre de API key<input className={`${INPUT} mt-1`} value={form.api_key_name} onChange={(e) => setForm({ ...form, api_key_name: e.target.value })} /></label><label className="text-xs">Ubicación<select className={`${INPUT} mt-1`} value={form.api_key_location} onChange={(e) => setForm({ ...form, api_key_location: e.target.value as "header" | "query" })}><option value="header">Header</option><option value="query">Query</option></select></label></>}
              <label className="text-xs">Timeout (segundos)<input type="number" min={1} max={120} className={`${INPUT} mt-1`} value={form.timeout_seconds} onChange={(e) => setForm({ ...form, timeout_seconds: Number(e.target.value) })} /></label>
              <label className="text-xs">Respuesta máxima (bytes)<input type="number" min={1024} className={`${INPUT} mt-1`} value={form.max_response_bytes} onChange={(e) => setForm({ ...form, max_response_bytes: Number(e.target.value) })} /></label>
              <fieldset className="grid gap-2 text-sm md:col-span-2"><legend className="mb-2 text-xs text-[var(--text-muted)]">Política</legend><label><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> <span className="ml-2">Fuente activa</span></label><label><input type="checkbox" checked={form.is_public} onChange={(e) => setForm({ ...form, is_public: e.target.checked })} /> <span className="ml-2">Disponible para el canal web público</span></label><label><input type="checkbox" checked={form.verify_tls} onChange={(e) => setForm({ ...form, verify_tls: e.target.checked })} /> <span className="ml-2">Verificar certificado TLS</span></label><label><input type="checkbox" checked={form.allow_private_network} onChange={(e) => setForm({ ...form, allow_private_network: e.target.checked })} /> <span className="ml-2">Permitir red privada (solo infraestructura controlada)</span></label></fieldset>
              {error && <p className="text-sm text-[var(--error)] md:col-span-2">{error}</p>}
            </div>
            <footer className="flex justify-end gap-2 border-t border-[var(--border-color)] p-4"><button onClick={() => { setEditing(null); setShowForm(false); setForm({ ...EMPTY }); }} className="rounded border border-[var(--border-color)] px-3 py-2 text-sm">Cancelar</button><button onClick={save} disabled={saving} className="flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50">{saving ? <LoaderCircle className="animate-spin" size={15} /> : <CheckCircle2 size={15} />} Guardar</button></footer>
          </section>
        </div>
      )}
    </div>
  );
}

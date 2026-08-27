import { useEffect, useState } from "react";
import { ArrowLeft, Bot, CircleCheck, LoaderCircle, Pencil, Power, Save } from "lucide-react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface Profile {
  id: string;
  name: string;
  slug: string;
  version: number;
  is_active: boolean;
  is_public: boolean;
  retention_days: number;
  description: string | null;
  prompt_identity: string;
  prompt_domain: string;
  prompt_guardrails: string;
  unauthorized_message: string;
  error_message: string;
  created_at: string;
  updated_at: string;
}

const INPUT = "w-full rounded-md border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";
const PROMPTS: { key: "prompt_identity" | "prompt_domain" | "prompt_guardrails"; label: string; help: string }[] = [
  { key: "prompt_identity", label: "Identidad", help: "Rol, tono y forma de presentarse." },
  { key: "prompt_domain", label: "Dominio", help: "Qué puede resolver y qué información debe priorizar." },
  { key: "prompt_guardrails", label: "Guardrails", help: "Límites de seguridad, privacidad y comportamiento." },
];

export default function ProfilesPage() {
  const { user } = useAuth();
  const canEdit = hasPermission(user, PERMISSIONS.ALL);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [editing, setEditing] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activating, setActivating] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = () => api<Profile[]>("/profiles/").then(setProfiles);
  useEffect(() => { load().finally(() => setLoading(false)); }, []);

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    setError("");
    try {
      const { id, version, is_active, created_at, updated_at, ...body } = editing;
      void id; void version; void is_active; void created_at; void updated_at;
      await api(`/profiles/${editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setEditing(null);
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo guardar el agente.");
    } finally { setSaving(false); }
  };

  const activate = async (id: string) => {
    setActivating(id);
    try { await api(`/profiles/${id}/activate`, { method: "POST" }); await load(); }
    finally { setActivating(null); }
  };

  if (editing) return (
    <div className="max-w-4xl">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <button onClick={() => setEditing(null)} className="flex items-center gap-1 text-sm text-[var(--text-secondary)]"><ArrowLeft size={16} /> Volver</button>
        <h2 className="text-xl font-semibold">Editar agente: <span className="text-[var(--accent)]">{editing.name}</span></h2>
        <button onClick={save} disabled={saving} className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />} Guardar</button>
      </header>
      <div className="space-y-4">
        <section className="grid gap-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5 md:grid-cols-2">
          <label className="text-sm">Nombre<input className={`${INPUT} mt-1`} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></label>
          <label className="text-sm">Slug<input className={`${INPUT} mt-1 font-mono`} value={editing.slug} onChange={(e) => setEditing({ ...editing, slug: e.target.value })} /></label>
          <label className="text-sm">Retención de historial (días)<input type="number" min={1} max={365} className={`${INPUT} mt-1`} value={editing.retention_days} onChange={(e) => setEditing({ ...editing, retention_days: Number(e.target.value) })} /></label>
          <label className="flex items-center gap-2 self-end rounded border border-[var(--border-color)] p-2 text-sm"><input type="checkbox" checked={editing.is_public} onChange={(e) => setEditing({ ...editing, is_public: e.target.checked })} /> Disponible para el canal web público</label>
          <label className="text-sm md:col-span-2">Descripción<textarea rows={2} className={`${INPUT} mt-1`} value={editing.description || ""} onChange={(e) => setEditing({ ...editing, description: e.target.value || null })} /></label>
        </section>
        {PROMPTS.map((field) => <section key={field.key} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5"><div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><div><label className="text-sm font-medium">{field.label}</label><p className="text-xs text-[var(--text-muted)]">{field.help}</p></div><span className="text-xs text-[var(--text-muted)]">{editing[field.key].length.toLocaleString("es-AR")} caracteres</span></div><textarea rows={7} className={`${INPUT} resize-y font-mono`} value={editing[field.key]} onChange={(e) => setEditing({ ...editing, [field.key]: e.target.value })} /></section>)}
        <section className="grid gap-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5 md:grid-cols-2"><label className="text-sm">Mensaje no autorizado<textarea rows={3} className={`${INPUT} mt-1`} value={editing.unauthorized_message} onChange={(e) => setEditing({ ...editing, unauthorized_message: e.target.value })} /></label><label className="text-sm">Mensaje ante error<textarea rows={3} className={`${INPUT} mt-1`} value={editing.error_message} onChange={(e) => setEditing({ ...editing, error_message: e.target.value })} /></label></section>
        {error && <p className="text-sm text-[var(--error)]">{error}</p>}
      </div>
    </div>
  );

  return <div className="max-w-5xl"><header className="mb-6 flex items-center gap-2"><Bot className="text-[var(--accent)]" size={22} /><div><h2 className="text-xl font-semibold">Agentes</h2><p className="text-sm text-[var(--text-muted)]">Perfiles independientes, canales y política de retención.</p></div></header>{loading ? <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]"><LoaderCircle className="animate-spin" size={16} /> Cargando…</p> : <div className="grid gap-3 md:grid-cols-2">{profiles.map((profile) => <article key={profile.id} className={`rounded-lg border bg-[var(--bg-card)] p-4 ${profile.is_active ? "border-[var(--success)]" : "border-[var(--border-color)]"}`}><div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{profile.name}</h3><code className="text-xs text-[var(--text-muted)]">{profile.slug}</code>{profile.is_active && <span className="flex items-center gap-1 rounded bg-[var(--success)]/15 px-2 py-0.5 text-xs text-[var(--success)]"><CircleCheck size={12} /> Activo</span>}</div><p className="mt-2 text-sm text-[var(--text-secondary)]">{profile.description || "Sin descripción"}</p><p className="mt-3 text-xs text-[var(--text-muted)]">{profile.is_public ? "Canal web habilitado" : "Canales privados"} · historial {profile.retention_days} días</p>{canEdit && <div className="mt-4 flex gap-2"><button onClick={() => setEditing(profile)} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-3 py-1.5 text-sm"><Pencil size={14} /> Editar</button>{!profile.is_active && <button onClick={() => activate(profile.id)} disabled={activating === profile.id} className="flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white disabled:opacity-50">{activating === profile.id ? <LoaderCircle className="animate-spin" size={14} /> : <Power size={14} />} Activar</button>}</div>}</article>)}</div>}</div>;
}

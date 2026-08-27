import { useEffect, useState } from "react";
import { Bot, CircleCheck, ExternalLink, LoaderCircle, Power, Save } from "lucide-react";
import { Link } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import type { AgentProfile } from "../../agents/types";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

const INPUT = "w-full rounded-md border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";
const PROMPTS: { key: "prompt_identity" | "prompt_domain" | "prompt_guardrails"; label: string; help: string }[] = [
  { key: "prompt_identity", label: "Identidad", help: "Rol, tono y forma de presentarse." },
  { key: "prompt_domain", label: "Dominio", help: "Qué puede resolver y qué información debe priorizar." },
  { key: "prompt_guardrails", label: "Guardrails", help: "Límites de seguridad, privacidad y comportamiento." },
];

export default function ProfilesPage() {
  const { user } = useAuth();
  const { profiles, loading, error, refreshProfiles } = useAgentWorkspace();
  const canEdit = hasPermission(user, PERMISSIONS.ALL);
  const [activating, setActivating] = useState<string | null>(null);

  const activate = async (id: string) => {
    setActivating(id);
    try {
      await api(`/profiles/${id}/activate`, { method: "POST" });
      await refreshProfiles();
    } finally {
      setActivating(null);
    }
  };

  return (
    <div className="max-w-6xl">
      <header className="mb-6 flex items-center gap-3">
        <Bot className="text-[var(--accent)]" size={22} />
        <div>
          <h2 className="text-xl font-semibold">Agentes</h2>
          <p className="text-sm text-[var(--text-muted)]">Elegí un agente para administrar su espacio de trabajo.</p>
        </div>
      </header>
      {error && <div className="mb-4 rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error}</div>}
      {loading ? (
        <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status"><LoaderCircle className="animate-spin" size={16} /> Cargando agentes…</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {profiles.map((profile) => (
            <article key={profile.id} className={`rounded-lg border bg-[var(--bg-card)] p-4 ${profile.is_active ? "border-[var(--success)]/60" : "border-[var(--border-color)]"}`}>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">{profile.name}</h3>
                {profile.is_active && <span className="flex items-center gap-1 rounded bg-[var(--success)]/15 px-2 py-0.5 text-xs text-[var(--success)]"><CircleCheck size={12} /> Activo</span>}
              </div>
              <code className="mt-1 block text-xs text-[var(--text-muted)]">{profile.slug}</code>
              <p className="mt-3 text-sm text-[var(--text-secondary)]">{profile.description || "Sin descripción"}</p>
              <p className="mt-3 text-xs text-[var(--text-muted)]">{profile.is_public ? "Disponible para web" : "Sin exposición web"} · historial {profile.retention_days} días</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link to={`/agents/${profile.id}/overview`} className="flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white"><ExternalLink size={14} /> Abrir espacio</Link>
                {canEdit && !profile.is_active && <button onClick={() => activate(profile.id)} disabled={activating === profile.id} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-3 py-1.5 text-sm disabled:opacity-50">{activating === profile.id ? <LoaderCircle className="animate-spin" size={14} /> : <Power size={14} />} Activar</button>}
              </div>
            </article>
          ))}
          {profiles.length === 0 && <p className="text-sm text-[var(--text-muted)]">No hay agentes disponibles.</p>}
        </div>
      )}
    </div>
  );
}

export function AgentIdentityPage() {
  const { user } = useAuth();
  const { selectedAgent, refreshProfiles } = useAgentWorkspace();
  const canEdit = hasPermission(user, PERMISSIONS.ALL);
  const [draft, setDraft] = useState<AgentProfile | null>(selectedAgent ? { ...selectedAgent } : null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(selectedAgent ? { ...selectedAgent } : null);
  }, [selectedAgent]);

  if (!selectedAgent || !draft) return null;

  const save = async () => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const { id, version, is_active, created_at, updated_at, ...body } = draft;
      void id; void version; void is_active; void created_at; void updated_at;
      await api(`/profiles/${selectedAgent.id}`, { method: "PATCH", body: JSON.stringify(body) });
      await refreshProfiles();
      setNotice("Identidad guardada.");
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo guardar el agente.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-4xl space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="text-xl font-semibold">Identidad de {selectedAgent.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">Perfil, comportamiento, disponibilidad y retención del agente seleccionado.</p>
        </div>
        {canEdit && <button onClick={save} disabled={saving} className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />} Guardar</button>}
      </header>
      {notice && <p className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400" role="status">{notice}</p>}
      {error && <p className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error}</p>}
      <section className="grid gap-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5 md:grid-cols-2">
        <label className="text-sm">Nombre<input readOnly={!canEdit} className={`${INPUT} mt-1`} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
        <label className="text-sm">Slug<input readOnly={!canEdit} className={`${INPUT} mt-1 font-mono`} value={draft.slug} onChange={(event) => setDraft({ ...draft, slug: event.target.value })} /></label>
        <label className="text-sm">Retención de historial (días)<input readOnly={!canEdit} type="number" min={1} max={365} className={`${INPUT} mt-1`} value={draft.retention_days} onChange={(event) => setDraft({ ...draft, retention_days: Number(event.target.value) })} /></label>
        <label className="flex items-center gap-2 self-end rounded border border-[var(--border-color)] p-3 text-sm"><input disabled={!canEdit} type="checkbox" checked={draft.is_public} onChange={(event) => setDraft({ ...draft, is_public: event.target.checked })} /> Disponible para selección web pública</label>
        <label className="text-sm md:col-span-2">Descripción<textarea readOnly={!canEdit} rows={2} className={`${INPUT} mt-1`} value={draft.description || ""} onChange={(event) => setDraft({ ...draft, description: event.target.value || null })} /></label>
      </section>
      {PROMPTS.map((field) => (
        <section key={field.key} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><div><label htmlFor={field.key} className="text-sm font-medium">{field.label}</label><p className="text-xs text-[var(--text-muted)]">{field.help}</p></div><span className="text-xs text-[var(--text-muted)]">{draft[field.key].length.toLocaleString("es-AR")} caracteres</span></div>
          <textarea id={field.key} readOnly={!canEdit} rows={7} className={`${INPUT} resize-y font-mono`} value={draft[field.key]} onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })} />
        </section>
      ))}
      <section className="grid gap-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5 md:grid-cols-2">
        <label className="text-sm">Mensaje no autorizado<textarea readOnly={!canEdit} rows={3} className={`${INPUT} mt-1`} value={draft.unauthorized_message} onChange={(event) => setDraft({ ...draft, unauthorized_message: event.target.value })} /></label>
        <label className="text-sm">Mensaje ante error<textarea readOnly={!canEdit} rows={3} className={`${INPUT} mt-1`} value={draft.error_message} onChange={(event) => setDraft({ ...draft, error_message: event.target.value })} /></label>
      </section>
    </div>
  );
}

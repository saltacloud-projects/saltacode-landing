import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Brain, Save, Pencil, ArrowLeft, LoaderCircle, Database, Plus, X } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface Block {
  id: string; key: string; title: string; content: string;
  is_enabled: boolean; sort_order: number;
  created_at: string; updated_at: string;
}

function Switch({ checked, onChange, disabled }: { checked: boolean; onChange: () => void; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={onChange}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${checked ? "bg-[var(--accent)]" : "bg-[var(--border-color)]"}`}>
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
    </button>
  );
}

const HELP = "text-xs text-[var(--text-muted)]";

export default function KnowledgePage() {
  const { user } = useAuth();
  const canEdit = hasPermission(user, PERMISSIONS.ALL);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [editing, setEditing] = useState<Block | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = () => api<Block[]>("/knowledge-blocks/").then(setBlocks);
  useEffect(() => { load().finally(() => setLoading(false)); }, []);

  const toggle = async (key: string, enabled: boolean) => {
    setToggling(key);
    try {
      await api(`/knowledge-blocks/${key}`, { method: "PATCH", body: JSON.stringify({ is_enabled: !enabled }) });
      await load();
    } finally { setToggling(null); }
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await api(`/knowledge-blocks/${editing.key}`, {
        method: "PATCH",
        body: JSON.stringify({ title: editing.title, content: editing.content }),
      });
      setEditing(null);
      await load();
    } finally { setSaving(false); }
  };

  const createBlock = async () => {
    if (!newKey.trim() || !newTitle.trim() || !newContent.trim()) {
      setCreateError("Todos los campos son obligatorios");
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      await api("/knowledge-blocks/", {
        method: "POST",
        body: JSON.stringify({ key: newKey.trim(), title: newTitle.trim(), content: newContent.trim() }),
      });
      setShowCreate(false);
      setNewKey(""); setNewTitle(""); setNewContent("");
      await load();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Error al crear el bloque");
    } finally { setCreating(false); }
  };

  // ----------------------------- Vista edicion -----------------------------
  if (editing) return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => setEditing(null)}
            className="flex items-center gap-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
            <ArrowLeft size={16} /> Volver
          </button>
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">
            Editar bloque: <span className="font-mono text-[var(--accent)]">{editing.key}</span>
          </h2>
        </div>
        <button onClick={save} disabled={saving}
          className="flex items-center gap-2 px-4 py-2 text-sm rounded-md bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white disabled:opacity-50 transition-colors">
          {saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
          {saving ? "Guardando..." : "Guardar"}
        </button>
      </div>
      <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-lg p-5 space-y-5">
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">Titulo</label>
          <input value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })}
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
          <p className={`mt-1 ${HELP}`}>Nombre descriptivo del bloque visible en el panel</p>
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-sm font-medium text-[var(--text-primary)]">Contenido</label>
            <span className={`${HELP} tabular-nums`}>{editing.content.length.toLocaleString("es-AR")} caracteres</span>
          </div>
          <p className={`${HELP} mb-2`}>Texto que se inyecta en el system prompt del agente cuando el bloque esta habilitado. Podes usar placeholders como {"{fecha_actual}"}, {"{mes_actual}"}, {"{mes_anterior}"}.</p>
          <textarea rows={22} value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })}
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-md px-3 py-2 text-sm font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] resize-y" />
        </div>
      </div>
    </div>
  );

  // ----------------------------- Vista lista -----------------------------
  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Brain size={22} className="text-[var(--accent)]" />
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Bloques de Conocimiento</h2>
          <span className="text-sm text-[var(--text-muted)]">({blocks.length})</span>
        </div>
        {canEdit && <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white transition-colors">
          <Plus size={14} /> Nuevo bloque
        </button>}
      </div>

      <p className={`${HELP} mb-4`}>
        Cada bloque habilitado se inyecta automaticamente al system prompt del agente, en orden de sort_order. Podes crear, editar, habilitar o deshabilitar bloques sin tocar codigo.
      </p>

      {/* Modal crear bloque */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-lg w-full max-w-lg">
            <div className="flex items-center justify-between border-b border-[var(--border-color)] px-4 py-3">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Nuevo bloque de conocimiento</h3>
              <button onClick={() => { setShowCreate(false); setCreateError(""); }}
                className="p-1 rounded text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                <X size={16} />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Key (identificador unico)</label>
                <input value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="ej: politicas_credito"
                  className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
                <p className={`mt-1 ${HELP}`}>Identificador interno sin espacios. No se puede cambiar despues.</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Titulo</label>
                <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="ej: Politicas de credito a proveedores"
                  className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
                <p className={`mt-1 ${HELP}`}>Nombre descriptivo visible en el panel</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Contenido</label>
                <textarea rows={6} value={newContent} onChange={(e) => setNewContent(e.target.value)}
                  placeholder="Texto que se inyectara al system prompt del agente..."
                  className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] resize-y" />
                <p className={`mt-1 ${HELP}`}>Se inyecta al prompt cuando el bloque esta habilitado. Podes usar placeholders temporales.</p>
              </div>
              {createError && <p className="text-xs text-[var(--error)]">{createError}</p>}
              <div className="flex justify-end gap-2">
                <button onClick={() => { setShowCreate(false); setCreateError(""); }}
                  className="px-3 py-1.5 text-sm rounded bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]">
                  Cancelar
                </button>
                <button onClick={createBlock} disabled={creating}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white disabled:opacity-50">
                  {creating ? <LoaderCircle size={14} className="animate-spin" /> : <Plus size={14} />}
                  {creating ? "Creando..." : "Crear bloque"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-[var(--text-secondary)] text-sm">
          <LoaderCircle size={16} className="animate-spin" /> Cargando bloques...
        </div>
      ) : blocks.length === 0 ? (
        <p className="text-[var(--text-muted)] text-sm">No hay bloques de conocimiento.</p>
      ) : (
        <div className="space-y-3">
          {blocks.map((b) => (
            <div key={b.key}
              className={`bg-[var(--bg-card)] border rounded-lg p-4 transition-colors ${b.is_enabled ? "border-[var(--border-color)]" : "border-[var(--border-color)] opacity-60"}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {b.key.startsWith("db_") && <Database size={14} className="text-[var(--text-secondary)]" />}
                    <span className="font-mono font-semibold text-sm text-[var(--text-primary)]">{b.key}</span>
                    <span className={`${HELP} tabular-nums`}>{b.content.length.toLocaleString("es-AR")} caracteres</span>
                    <span className={`${HELP}`}>orden: {b.sort_order}</span>
                  </div>
                  <p className="text-sm text-[var(--text-primary)] mt-1.5">{b.title}</p>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <div className="flex items-center gap-2">
                    {toggling === b.key ? (
                      <LoaderCircle size={16} className="animate-spin text-[var(--text-secondary)]" />
                    ) : (
                      <Switch disabled={!canEdit} checked={b.is_enabled} onChange={() => toggle(b.key, b.is_enabled)} />
                    )}
                    <span className="text-xs text-[var(--text-secondary)] w-16">
                      {b.is_enabled ? "Habilitado" : "Deshabilitado"}
                    </span>
                  </div>
                  {canEdit && <button onClick={() => setEditing(b)}
                    className="flex items-center gap-1 px-3 py-1.5 text-sm rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors">
                    <Pencil size={14} /> Editar
                  </button>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

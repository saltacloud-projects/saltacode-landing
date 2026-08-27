import { useState } from "react";
import { ArrowLeft, Brain, LoaderCircle, Pencil, Plus, Save, X } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAgentResourceLibrary } from "../../agents/useAgentResourceLibrary";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface Block { id: string; key: string; title: string; content: string; is_enabled: boolean; sort_order: number; created_at: string; updated_at: string }
const INPUT = "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";

export default function KnowledgePage({ scope = "agent" }: { scope?: "agent" | "library" }) {
  const { user } = useAuth();
  const { selectedAgent } = useAgentWorkspace();
  const agentId = scope === "agent" ? selectedAgent?.id : undefined;
  const resources = useAgentResourceLibrary<Block>(agentId, "knowledge-blocks", "/knowledge-blocks/");
  const canEdit = hasPermission(user, PERMISSIONS.ALL);
  const [editing, setEditing] = useState<Block | null>(null);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const toggle = async (block: Block) => {
    setToggling(block.id); setError("");
    try { await api(`/knowledge-blocks/${block.key}`, { method: "PATCH", body: JSON.stringify({ is_enabled: !block.is_enabled }) }); await resources.refresh(); }
    catch (value) { setError(value instanceof Error ? value.message : "No se pudo actualizar el bloque."); }
    finally { setToggling(null); }
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true); setError("");
    try { await api(`/knowledge-blocks/${editing.key}`, { method: "PATCH", body: JSON.stringify({ title: editing.title, content: editing.content, sort_order: editing.sort_order }) }); setEditing(null); await resources.refresh(); }
    catch (value) { setError(value instanceof Error ? value.message : "No se pudo guardar el bloque."); }
    finally { setSaving(false); }
  };

  const createBlock = async () => {
    if (!newKey.trim() || !newTitle.trim() || !newContent.trim()) return setError("Todos los campos son obligatorios.");
    setCreating(true); setError("");
    try {
      const created = await api<Block>("/knowledge-blocks/", { method: "POST", body: JSON.stringify({ key: newKey.trim(), title: newTitle.trim(), content: newContent.trim() }) });
      if (agentId) await api(`/agents/${agentId}/knowledge-blocks/${created.id}`, { method: "PUT" });
      setShowCreate(false); setNewKey(""); setNewTitle(""); setNewContent(""); await resources.refresh();
    } catch (value) { setError(value instanceof Error ? value.message : "No se pudo crear el bloque."); }
    finally { setCreating(false); }
  };

  if (editing) return <div className="max-w-4xl"><header className="mb-6 flex flex-wrap items-center gap-3"><button onClick={() => setEditing(null)} className="flex items-center gap-1 text-sm text-[var(--text-secondary)]"><ArrowLeft size={16} /> Volver</button><div><h2 className="text-xl font-semibold">Editar recurso compartido</h2><code className="text-xs text-[var(--accent)]">{editing.key}</code></div>{canEdit && <button onClick={save} disabled={saving} className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />} Guardar</button>}</header>{error && <p className="mb-4 rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error}</p>}<section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5"><label className="block text-sm">Título<input readOnly={!canEdit} className={`${INPUT} mt-1`} value={editing.title} onChange={(event) => setEditing({ ...editing, title: event.target.value })} /></label><label className="block text-sm">Orden<input readOnly={!canEdit} type="number" className={`${INPUT} mt-1`} value={editing.sort_order} onChange={(event) => setEditing({ ...editing, sort_order: Number(event.target.value) })} /></label><label className="block text-sm">Contenido<textarea readOnly={!canEdit} rows={22} className={`${INPUT} mt-1 resize-y font-mono`} value={editing.content} onChange={(event) => setEditing({ ...editing, content: event.target.value })} /></label><p className="text-xs text-amber-300">Este bloque pertenece a la biblioteca compartida. Editarlo afecta a todos los agentes que lo tengan asignado.</p></section></div>;

  const BlockCard = ({ block, assignment }: { block: Block; assignment?: "assigned" | "available" }) => <article className={`rounded-lg border bg-[var(--bg-card)] p-4 ${block.is_enabled ? "border-[var(--border-color)]" : "border-[var(--border-color)] opacity-60"}`}><div className="flex items-start gap-3"><div className="min-w-0 flex-1"><h4 className="font-semibold">{block.title}</h4><code className="text-xs text-[var(--text-muted)]">{block.key}</code></div><span className="rounded bg-[var(--bg-hover)] px-2 py-1 text-xs">orden {block.sort_order}</span></div><p className="mt-3 line-clamp-3 whitespace-pre-wrap text-sm text-[var(--text-secondary)]">{block.content}</p>{canEdit && <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => toggle(block)} disabled={toggling === block.id} className="rounded border border-[var(--border-color)] px-2 py-1.5 text-xs">{block.is_enabled ? "Deshabilitar globalmente" : "Habilitar globalmente"}</button><button onClick={() => setEditing({ ...block })} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-1.5 text-xs"><Pencil size={13} /> Editar biblioteca</button>{assignment === "assigned" && <button onClick={() => resources.unassign(block.id)} disabled={resources.busyId === block.id} className="rounded border border-amber-500/40 px-2 py-1.5 text-xs text-amber-300">Desasignar</button>}{assignment === "available" && <button onClick={() => resources.assign(block.id)} disabled={resources.busyId === block.id} className="rounded bg-[var(--accent)] px-2 py-1.5 text-xs text-white">Asignar</button>}</div>}</article>;

  return <div className="max-w-6xl space-y-6"><header className="flex flex-wrap items-center gap-3"><Brain size={22} className="text-[var(--accent)]" /><div><h2 className="text-xl font-semibold">{agentId ? `Conocimiento de ${selectedAgent?.name}` : "Biblioteca de conocimiento"}</h2><p className="text-sm text-[var(--text-muted)]">{agentId ? "Asigná únicamente los bloques que este agente debe recibir." : "Bloques reutilizables. Su contenido y estado son globales."}</p></div>{canEdit && <button onClick={() => { setError(""); setShowCreate(true); }} className="ml-auto flex items-center gap-1.5 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white"><Plus size={14} /> Nuevo bloque</button>}</header>{(error || resources.error) && <p className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error || resources.error}</p>}{resources.loading ? <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status"><LoaderCircle className="animate-spin" size={16} /> Cargando…</p> : agentId ? <><section><h3 className="mb-3 font-semibold">Asignados ({resources.assigned.length})</h3><div className="grid gap-3 md:grid-cols-2">{resources.assigned.map((block) => <BlockCard key={block.id} block={block} assignment="assigned" />)}{resources.assigned.length === 0 && <p className="text-sm text-[var(--text-muted)]">Sin bloques asignados.</p>}</div></section><section><h3 className="mb-3 font-semibold">Disponibles ({resources.available.length})</h3><div className="grid gap-3 md:grid-cols-2">{resources.available.map((block) => <BlockCard key={block.id} block={block} assignment="available" />)}{resources.available.length === 0 && <p className="text-sm text-[var(--text-muted)]">No quedan bloques disponibles.</p>}</div></section></> : <div className="grid gap-3 md:grid-cols-2">{resources.library.map((block) => <BlockCard key={block.id} block={block} />)}{resources.library.length === 0 && <p className="text-sm text-[var(--text-muted)]">No hay bloques en la biblioteca.</p>}</div>}
  {showCreate && <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"><section className="w-full max-w-lg rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]" role="dialog" aria-modal="true" aria-labelledby="block-title"><header className="flex items-center justify-between border-b border-[var(--border-color)] p-4"><h3 id="block-title" className="font-semibold">Nuevo bloque compartido</h3><button aria-label="Cerrar" onClick={() => setShowCreate(false)}><X size={17} /></button></header><div className="space-y-4 p-4"><label className="block text-xs">Key<input className={`${INPUT} mt-1 font-mono`} value={newKey} onChange={(event) => setNewKey(event.target.value)} /></label><label className="block text-xs">Título<input className={`${INPUT} mt-1`} value={newTitle} onChange={(event) => setNewTitle(event.target.value)} /></label><label className="block text-xs">Contenido<textarea rows={8} className={`${INPUT} mt-1 font-mono`} value={newContent} onChange={(event) => setNewContent(event.target.value)} /></label>{error && <p className="text-sm text-red-400" role="alert">{error}</p>}</div><footer className="flex justify-end gap-2 border-t border-[var(--border-color)] p-4"><button onClick={() => setShowCreate(false)} className="rounded border border-[var(--border-color)] px-3 py-2 text-sm">Cancelar</button><button onClick={createBlock} disabled={creating} className="flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50">{creating ? <LoaderCircle className="animate-spin" size={14} /> : <Plus size={14} />} Crear</button></footer></section></div>}
  </div>;
}

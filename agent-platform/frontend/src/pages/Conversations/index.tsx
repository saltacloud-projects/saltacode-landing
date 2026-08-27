import { useEffect, useState } from "react";
import { LoaderCircle, MessageSquare, RefreshCw, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";

interface Conversation {
  id: string;
  agent_slug: string;
  principal_id: string;
  display_name: string | null;
  channel: string;
  status: string;
  message_count: number;
  last_message_at: string | null;
  transcript_consent: boolean;
  consent_version: string | null;
}

interface Message {
  id: string;
  role: string;
  content: string;
  status: string;
  tool_names: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

function formatDate(value: string | null): string {
  if (!value) return "Sin mensajes";
  return new Intl.DateTimeFormat("es-AR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

export default function ConversationsPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canDelete = hasPermission(user, PERMISSIONS.CONVERSATIONS_MANAGE);
  const [items, setItems] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [channel, setChannel] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);

  const load = async () => {
    const query = channel ? `?channel=${encodeURIComponent(channel)}` : "";
    const rows = await api<Conversation[]>(`/conversations/${query}`);
    setItems(rows);
    if (selected && !rows.some((row) => row.id === selected.id)) {
      setSelected(null);
      setMessages([]);
    }
  };

  useEffect(() => { setLoading(true); load().finally(() => setLoading(false)); }, [channel]);

  const open = async (conversation: Conversation) => {
    setSelected(conversation);
    setLoadingMessages(true);
    try {
      setMessages(await api<Message[]>(`/conversations/${conversation.id}/messages`));
    } finally {
      setLoadingMessages(false);
    }
  };

  const remove = async () => {
    if (!selected || !confirm("¿Eliminar esta conversación y todo su historial?")) return;
    await api(`/conversations/${selected.id}`, { method: "DELETE" });
    setSelected(null);
    setMessages([]);
    await load();
  };

  return (
    <div className="max-w-7xl">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <MessageSquare size={22} className="text-[var(--accent)]" />
        <div><h2 className="text-xl font-semibold">Conversaciones</h2><p className="text-sm text-[var(--text-muted)]">Historial unificado de web, WhatsApp y futuros canales.</p></div>
        <div className="ml-auto flex gap-2"><select className="rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm" value={channel} onChange={(event) => setChannel(event.target.value)}><option value="">Todos los canales</option><option value="web">Web</option><option value="whatsapp">WhatsApp</option><option value="api">API</option></select><button onClick={load} aria-label="Actualizar" className="rounded border border-[var(--border-color)] p-2"><RefreshCw size={17} /></button></div>
      </header>
      {selectedAgent && <p className="mb-4 rounded border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-300">Compatibilidad: el backend todavía devuelve conversaciones de todos los agentes. Cada fila muestra su agente real; esta vista no aplica un filtro de servidor para {selectedAgent.name}.</p>}

      <div className="grid min-h-[65vh] gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <section className="overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]">
          {loading ? <p className="flex items-center gap-2 p-4 text-sm text-[var(--text-muted)]"><LoaderCircle className="animate-spin" size={16} /> Cargando…</p> : (
            <div className="max-h-[70vh] divide-y divide-[var(--border-color)] overflow-y-auto">
              {items.map((conversation) => (
                <button key={conversation.id} onClick={() => open(conversation)} className={`w-full p-4 text-left transition-colors hover:bg-[var(--bg-hover)] ${selected?.id === conversation.id ? "bg-[var(--bg-hover)]" : ""}`}>
                  <div className="flex items-center gap-2"><strong className="truncate text-sm">{conversation.display_name || `Visitante ${conversation.principal_id.slice(0, 8)}`}</strong><span className="ml-auto rounded bg-[var(--accent)]/15 px-2 py-0.5 text-[10px] uppercase text-[var(--accent)]">{conversation.channel}</span></div>
                  <p className="mt-1 text-xs text-[var(--text-muted)]">{conversation.agent_slug} · {conversation.message_count} mensajes</p>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">{formatDate(conversation.last_message_at)}</p>
                </button>
              ))}
              {items.length === 0 && <p className="p-5 text-sm text-[var(--text-muted)]">No hay conversaciones para este filtro.</p>}
            </div>
          )}
        </section>

        <section className="flex min-h-[420px] flex-col overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]">
          {!selected ? <div className="grid flex-1 place-items-center p-6 text-center text-sm text-[var(--text-muted)]">Seleccioná una conversación para revisar su historial.</div> : <>
            <header className="flex flex-wrap items-center gap-3 border-b border-[var(--border-color)] p-4"><div><h3 className="font-semibold">{selected.display_name || "Visitante"}</h3><p className="text-xs text-[var(--text-muted)]">{selected.channel} · consentimiento {selected.transcript_consent ? selected.consent_version || "registrado" : "no registrado"}</p></div>{canDelete && <button onClick={remove} className="ml-auto flex items-center gap-1 rounded border border-[var(--error)]/40 px-2 py-1.5 text-xs text-[var(--error)]"><Trash2 size={14} /> Eliminar</button>}</header>
            <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4" role="log" aria-label="Historial de conversación">
              {loadingMessages ? <LoaderCircle className="animate-spin text-[var(--text-muted)]" size={18} /> : messages.map((message) => (
                <article key={message.id} className={`max-w-[88%] rounded-xl px-3 py-2 text-sm ${message.role === "user" ? "ml-auto bg-[var(--accent)] text-white" : "mr-auto border border-[var(--border-color)] bg-[var(--bg-secondary)]"}`}>
                  <p className="whitespace-pre-wrap break-words">{message.content}</p>
                  <footer className={`mt-2 flex flex-wrap gap-1 text-[10px] ${message.role === "user" ? "text-white/75" : "text-[var(--text-muted)]"}`}><span>{formatDate(message.created_at)}</span>{message.tool_names.map((tool) => <code key={tool} className="rounded bg-black/10 px-1">{tool}</code>)}</footer>
                </article>
              ))}
            </div>
          </>}
        </section>
      </div>
    </div>
  );
}

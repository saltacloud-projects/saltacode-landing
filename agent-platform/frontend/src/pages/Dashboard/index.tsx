import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle, AlertTriangle, Save, Send, Trash2, Loader2, Copy,
  Bot, Brain, Wrench, Users, MessageSquare, ArrowRight, Search, ClipboardList, FlaskConical, Files,
} from "lucide-react";
import { api, ApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */
interface Profile {
  id: string; name: string; is_active: boolean;
  prompt_identity: string; prompt_domain: string; prompt_guardrails: string;
  unauthorized_message: string; error_message: string;
  [k: string]: unknown;
}
interface ConfigStatus { is_ready: boolean; issues: { level: string; category: string; message: string }[]; }
interface KBBlock { key: string; title: string; content: string; is_enabled: boolean; }
interface ToolItem { tool_name: string; is_enabled: boolean; }
interface UserItem { phone_number: string; name: string | null; is_active: boolean; }
interface ConvItem { phone_number: string; name: string | null; message_count: number; }
interface DocumentStats { documents_total: number; published: number; processing: number; failed: number; chunks: number; storage_bytes: number; queue_depth: number; }
interface AuditItem {
  id: string; phone_number: string; status: string; tool_used: string | null;
  duration_ms: number | null; response_preview: string | null; created_at: string;
}
interface TestResult {
  response_text: string; tools_used: string[]; iterations: number;
  total_tool_calls: number; duration_ms: number; status: string;
}

/* ------------------------------------------------------------------ */
/* Tabs config for profile                                             */
/* ------------------------------------------------------------------ */
const PROFILE_TABS: { key: keyof Profile | "_structure"; label: string; tooltip: string }[] = [
  { key: "prompt_identity", label: "Identidad", tooltip: "Nombre, personalidad, dominio de conocimiento y datos verificados de la empresa" },
  { key: "prompt_guardrails", label: "Guardrails", tooltip: "Reglas y limites que el agente nunca debe romper (seguridad de datos)" },
  { key: "unauthorized_message", label: "No autorizado", tooltip: "Mensaje operativo para usuarios que no estan en la whitelist (lo usa el pipeline, no el LLM)" },
  { key: "error_message", label: "Error", tooltip: "Mensaje operativo cuando ocurre un error interno (lo usa el pipeline, no el LLM)" },
  { key: "_structure", label: "Estructura del Prompt", tooltip: "Vista desglosada de como se arma el system prompt completo que recibe el modelo" },
];

/* ------------------------------------------------------------------ */
/* Helper                                                              */
/* ------------------------------------------------------------------ */
const HELP = "text-xs text-[var(--text-muted)]";
const CARD = "bg-[var(--bg-card)] border border-[var(--border-color)] rounded-lg";
const LINK = "inline-flex items-center gap-1 text-xs text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors";

function SectionLink({ to, label }: { to: string; label: string }) {
  return <Link to={to} className={LINK}>{label} <ArrowRight size={12} /></Link>;
}

/* ================================================================== */
/* Dashboard                                                           */
/* ================================================================== */
export default function DashboardPage() {
  const { user } = useAuth();
  const canEdit = hasPermission(user, PERMISSIONS.ALL);
  /* ---- state ---- */
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [editProfile, setEditProfile] = useState<Profile | null>(null);
  const [activeTab, setActiveTab] = useState<string>(PROFILE_TABS[0].key as string);
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);

  const [blocks, setBlocks] = useState<KBBlock[]>([]);
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [convs, setConvs] = useState<ConvItem[]>([]);
  const [audits, setAudits] = useState<AuditItem[]>([]);
  const [documentStats, setDocumentStats] = useState<DocumentStats | null>(null);

  // test agent — persistir en sessionStorage para no perder al navegar
  const [testMsg, setTestMsg] = useState("");
  const [testing, setTesting] = useState(false);
  const [chatHistory, setChatHistory] = useState<{ role: string; text: string; meta?: TestResult }[]>(() => {
    try {
      const saved = sessionStorage.getItem("agent_test_chat");
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });

  // Persistir chat history en sessionStorage
  useEffect(() => {
    try { sessionStorage.setItem("agent_test_chat", JSON.stringify(chatHistory)); } catch {}
  }, [chatHistory]);

  // audit filters
  const [auditStatus, setAuditStatus] = useState("");
  const [auditPhone, setAuditPhone] = useState("");

  // prompt structure
  interface PromptSection { name: string; source: string; source_key: string | null; content: string; char_count: number; }
  interface PromptStructure { sections: PromptSection[]; total_chars: number; tools_count: number; tools_list: string[]; }
  const [promptStructure, setPromptStructure] = useState<PromptStructure | null>(null);
  const [loadingStructure, setLoadingStructure] = useState(false);

  /* ---- load ---- */
  useEffect(() => {
    api<ConfigStatus>("/config/status").then(setConfig).catch(() => {});
    api<Profile[]>("/profiles/").then((ps) => {
      const active = ps.find((p) => p.is_active) || ps[0];
      if (active) { setProfile(active); setEditProfile({ ...active }); }
    }).catch(() => {});
    api<KBBlock[]>("/knowledge-blocks/").then(setBlocks).catch(() => {});
    api<ToolItem[]>("/tools/").then(setTools).catch(() => {});
    api<UserItem[]>("/users/").then(setUsers).catch(() => {});
    api<ConvItem[]>("/conversations/").then(setConvs).catch(() => {});
    api<DocumentStats>("/documents/stats").then(setDocumentStats).catch(() => {});
    loadAudit();
  }, []);

  const loadAudit = () => {
    const p = new URLSearchParams();
    if (auditStatus) p.set("status", auditStatus);
    if (auditPhone) p.set("phone", auditPhone);
    p.set("limit", "10");
    api<AuditItem[]>(`/audit/?${p}`).then(setAudits).catch(() => {});
  };

  /* ---- save profile ---- */
  const saveProfile = async () => {
    if (!editProfile || !profile) return;
    setSaving(true);
    setSaveOk(false);
    try {
      const body: Record<string, string> = {};
      // Incluir TODOS los campos editables, no solo los tabs
      for (const t of PROFILE_TABS) {
        if (t.key !== "_structure") body[t.key as string] = editProfile[t.key] as string;
      }
      body.name = editProfile.name;
      body.prompt_domain = editProfile.prompt_domain as string; // campo editable en tab Identidad
      await api(`/profiles/${profile.id}`, { method: "PATCH", body: JSON.stringify(body) });
      const ps = await api<Profile[]>("/profiles/");
      const active = ps.find((p) => p.is_active) || ps[0];
      if (active) { setProfile(active); setEditProfile({ ...active }); }
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 3000);
    } finally { setSaving(false); }
  };

  /* ---- test agent ---- */
  const runTest = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!testMsg.trim() || testing) return;
    const msg = testMsg.trim();
    setTestMsg("");
    setChatHistory((h) => [...h, { role: "user", text: msg }]);
    setTesting(true);
    try {
      // Construir historial de conversacion para contexto
      const history = chatHistory
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.text }));
      const res = await api<TestResult>("/promptlab/test-agent", {
        method: "POST", body: JSON.stringify({ message: msg, conversation_history: history }),
      });
      setChatHistory((h) => [...h, { role: "assistant", text: res.response_text, meta: res }]);
    } catch (err) {
      setChatHistory((h) => [...h, { role: "error", text: err instanceof ApiError ? err.message : "Error" }]);
    } finally { setTesting(false); }
  };

  /* ================================================================ */
  /* Render                                                            */
  /* ================================================================ */
  return (
    <div className="space-y-6">
      {/* Title */}
      <div>
        <h2 className="text-xl font-bold text-[var(--text-primary)]">Panel de Administracion</h2>
        <p className={HELP}>Gestiona y configura tu agente empresarial</p>
      </div>

      {/* Config status */}
      {config && (
        <div className={`${CARD} p-3 flex items-start gap-3 ${config.is_ready ? "border-[var(--success)]" : "border-[var(--error)]"}`}>
          {config.is_ready
            ? <CheckCircle size={18} className="text-[var(--success)] mt-0.5 shrink-0" />
            : <AlertTriangle size={18} className="text-[var(--error)] mt-0.5 shrink-0" />}
          <div className="min-w-0">
            <p className={`text-sm font-medium ${config.is_ready ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
              {config.is_ready ? "Agente configurado y operativo" : "Agente NO configurado"}
            </p>
            {config.issues.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {config.issues.map((i, idx) => (
                  <li key={idx} className={`text-xs ${i.level === "error" ? "text-[var(--error)]" : "text-[var(--warning)]"}`}>
                    <span className="font-mono text-[var(--text-muted)] mr-1">[{i.category}]</span>{i.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* ============================================================ */}
      {/* ROW 1: Profile (left) + Prompt Test (right)                   */}
      {/* ============================================================ */}
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Profile editor with tabs */}
        <section className={`${CARD} flex-1 min-w-0`}>
          <div className="flex items-center justify-between border-b border-[var(--border-color)] px-4 py-3">
            <div>
              <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                <Bot size={16} className="text-[var(--accent)]" />
                Perfil del Agente: <span className="text-[var(--accent)]">{profile?.name || "..."}</span>
              </h3>
              <p className={HELP}>Configuracion de identidad, comportamiento y mensajes del agente</p>
            </div>
            <div className="flex items-center gap-2">
              {saveOk && (
                <span className="flex items-center gap-1 text-xs text-[var(--success)]">
                  <CheckCircle size={14} /> Guardado
                </span>
              )}
              {canEdit && <button onClick={saveProfile} disabled={saving}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white disabled:opacity-50 transition-colors">
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {saving ? "Guardando..." : "Guardar cambios"}
              </button>}
            </div>
          </div>

          {/* Tabs */}
          <div className="flex overflow-x-auto border-b border-[var(--border-color)] px-4 gap-0">
            {PROFILE_TABS.map((t) => (
              <button key={t.key as string} onClick={() => {
                  setActiveTab(t.key as string);
                  if (t.key === "_structure" && !promptStructure) {
                    setLoadingStructure(true);
                    api<PromptStructure>("/promptlab/prompt-structure")
                      .then(setPromptStructure)
                      .finally(() => setLoadingStructure(false));
                  }
                }}
                title={t.tooltip}
                className={`whitespace-nowrap px-3 py-2 text-xs border-b-2 transition-colors ${
                  activeTab === t.key
                    ? "border-[var(--accent)] text-[var(--accent)]"
                    : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                }`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Active tab content */}
          {editProfile && (
            <div className="p-4">
              {activeTab === "prompt_identity" && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Columna izquierda: Nombre + Identidad */}
                  <div className="space-y-4">
                    <div>
                      <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Nombre del agente</label>
                      <input readOnly={!canEdit} value={editProfile.name} onChange={(e) => setEditProfile({ ...editProfile, name: e.target.value })}
                        className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
                      <p className={`mt-1 ${HELP}`}>Nombre interno para identificar al agente</p>
                    </div>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-medium text-[var(--text-secondary)]">Identidad / Rol</label>
                        <span className={HELP}>{(editProfile.prompt_identity as string).length} / 1000</span>
                      </div>
                      <textarea readOnly={!canEdit} rows={8} value={editProfile.prompt_identity as string}
                        onChange={(e) => setEditProfile({ ...editProfile, prompt_identity: e.target.value })}
                        className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--accent)] resize-y" />
                      <p className={`mt-1 ${HELP}`}>Define quien es el agente, su personalidad y estilo de comunicacion</p>
                    </div>
                  </div>
                  {/* Columna derecha: Dominio */}
                  <div>
                    <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Dominio de conocimiento</label>
                    <textarea readOnly={!canEdit} rows={14} value={editProfile.prompt_domain as string}
                      onChange={(e) => setEditProfile({ ...editProfile, prompt_domain: e.target.value })}
                      className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--accent)] resize-y" />
                    <p className={`mt-1 ${HELP}`}>Sobre que temas puede responder el agente</p>
                  </div>
                </div>
              )}
              {activeTab === "_structure" && (
                <div>
                  {loadingStructure ? (
                    <div className="flex items-center gap-2 py-4 text-[var(--text-secondary)] text-sm">
                      <Loader2 size={16} className="animate-spin" /> Cargando estructura...
                    </div>
                  ) : promptStructure ? (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <p className={HELP}>Desglose de las secciones que componen el system prompt enviado al modelo</p>
                        <div className="flex items-center gap-3">
                          <span className="text-xs font-mono text-[var(--text-secondary)]">{promptStructure.total_chars.toLocaleString("es-AR")} caracteres total</span>
                          <button
                            onClick={() => {
                              const separator = "\n" + "=".repeat(60) + "\n";
                              const full = promptStructure.sections.map((s) =>
                                `[${s.source.toUpperCase()}] ${s.name} (${s.char_count} chars)${s.source_key ? " ← " + s.source_key : ""}\n${s.content}`
                              ).join(separator) + separator + `[TOOLS] ${promptStructure.tools_count} herramientas registradas\n${promptStructure.tools_list.join(", ")}`;
                              navigator.clipboard.writeText(full);
                            }}
                            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
                            title="Copiar el prompt completo estructurado al portapapeles"
                          >
                            <Copy size={12} /> Copiar prompt completo
                          </button>
                        </div>
                      </div>
                      {promptStructure.sections.map((s, i) => {
                        const sourceColors: Record<string, string> = {
                          perfil: "bg-[var(--accent)]/15 text-[var(--accent)]",
                          knowledge_block: "bg-[var(--success)]/15 text-[var(--success)]",
                          codigo: "bg-[var(--warning)]/15 text-[var(--warning)]",
                          memoria: "bg-purple-500/15 text-purple-400",
                        };
                        return (
                          <div key={i} className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-[var(--text-primary)]">{s.name}</span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded ${sourceColors[s.source] || ""}`}>{s.source}</span>
                              </div>
                              <div className="flex items-center gap-2">
                                {s.source_key && <span className="font-mono text-[10px] text-[var(--text-muted)]">{s.source_key}</span>}
                                <span className="text-xs text-[var(--text-muted)]">{s.char_count.toLocaleString("es-AR")} chars</span>
                              </div>
                            </div>
                            <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap max-h-32 overflow-y-auto font-mono leading-relaxed">{s.content.slice(0, 500)}{s.content.length > 500 ? "..." : ""}</pre>
                          </div>
                        );
                      })}
                      <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg p-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium text-[var(--text-primary)]">Herramientas (function calling)</span>
                          <span className="text-xs text-[var(--text-muted)]">{promptStructure.tools_count} tools registradas</span>
                        </div>
                        <p className={HELP}>Se envian como tools[] del API de OpenAI, no dentro del system prompt</p>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {promptStructure.tools_list.map((t) => (
                            <span key={t} className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">{t}</span>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className={HELP}>Selecciona este tab para cargar la estructura del prompt</p>
                  )}
                </div>
              )}
              {activeTab !== "prompt_identity" && activeTab !== "_structure" && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs font-medium text-[var(--text-secondary)]">
                      {PROFILE_TABS.find((t) => t.key === activeTab)?.label}
                    </label>
                    <span className={HELP}>{((editProfile[activeTab] as string) || "").length} caracteres</span>
                  </div>
                  <p className={`mb-2 ${HELP}`}>{PROFILE_TABS.find((t) => t.key === activeTab)?.tooltip}</p>
                  <textarea readOnly={!canEdit} rows={8} value={(editProfile[activeTab] as string) || ""}
                    onChange={(e) => setEditProfile({ ...editProfile, [activeTab]: e.target.value })}
                    className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--accent)] resize-y" />
                </div>
              )}
            </div>
          )}
        </section>

        {/* Prompt test chat */}
        <section className={`${CARD} lg:w-[380px] flex flex-col`}>
          <div className="flex items-center justify-between border-b border-[var(--border-color)] px-4 py-3">
            <div>
              <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                <FlaskConical size={16} className="text-[var(--accent)]" />
                Prueba del Agente (Prompt Preview)
              </h3>
              <p className={HELP}>Ejecuta consultas reales contra el agente</p>
            </div>
            <button onClick={() => setChatHistory([])} title="Limpiar chat"
              className="p-1.5 rounded text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors">
              <Trash2 size={14} />
            </button>
          </div>

          {/* Chat messages */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3 max-h-[400px] min-h-[200px]">
            {chatHistory.length === 0 && (
              <p className={`text-center py-8 ${HELP}`}>Escribe un mensaje para probar el agente</p>
            )}
            {chatHistory.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                  m.role === "user"
                    ? "bg-[var(--accent)] text-white"
                    : m.role === "error"
                    ? "bg-[var(--error)]/20 text-[var(--error)]"
                    : "bg-[var(--bg-secondary)] text-[var(--text-primary)]"
                }`}>
                  <p className="whitespace-pre-wrap text-sm">{m.text}</p>
                  {m.meta && (
                    <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-[var(--border-color)]">
                      {m.meta.tools_used.length > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">
                          {m.meta.tools_used.join(", ")}
                        </span>
                      )}
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">
                        {m.meta.duration_ms}ms
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {testing && (
              <div className="flex justify-start">
                <div className="bg-[var(--bg-secondary)] rounded-lg px-3 py-2">
                  <Loader2 size={14} className="animate-spin text-[var(--text-muted)]" />
                </div>
              </div>
            )}
          </div>

          {/* Warning + input */}
          <div className="border-t border-[var(--border-color)] p-3 space-y-2">
            <div className="flex items-center gap-1.5 text-[10px] text-[var(--warning)]">
              <AlertTriangle size={12} />
              Las pruebas pueden ejecutar integraciones reales. Usá fuentes de prueba y evitá efectos no deseados.
            </div>
            <form onSubmit={runTest} className="flex gap-2">
              <input value={testMsg} onChange={(e) => setTestMsg(e.target.value)}
                placeholder="Escribe un mensaje de prueba..."
                className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]" />
              <button type="submit" disabled={testing || !testMsg.trim()}
                className="p-2 rounded bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white disabled:opacity-50 transition-colors">
                <Send size={14} />
              </button>
            </form>
          </div>
        </section>
      </div>

      {/* ============================================================ */}
      {/* ROW 2: KB + Tools + Users + Conversations (4 cards)           */}
      {/* ============================================================ */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Knowledge Blocks */}
        <div className={`${CARD} p-4`}>
          <div className="flex items-center gap-2 mb-1">
            <Brain size={16} className="text-[var(--text-secondary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Bloques de Conocimiento</h3>
          </div>
          <p className={`${HELP} mb-3`}>Contenido editable inyectado al prompt del agente</p>
          <div className="space-y-2">
            {blocks.slice(0, 4).map((b) => (
              <div key={b.key} className="flex items-center justify-between text-sm">
                <div className="min-w-0">
                  <p className="font-mono text-xs text-[var(--text-primary)] truncate">{b.key}</p>
                  <p className={HELP}>{b.title}</p>
                </div>
                <span className={HELP}>{b.content.length.toLocaleString("es-AR")} caracteres</span>
              </div>
            ))}
          </div>
          <div className="mt-3"><SectionLink to="/knowledge" label="Ver todos los bloques" /></div>
        </div>

        {/* Tools */}
        <div className={`${CARD} p-4`}>
          <div className="flex items-center gap-2 mb-1">
            <Wrench size={16} className="text-[var(--text-secondary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Tools (APIs)</h3>
          </div>
          <p className={`${HELP} mb-3`}>Herramientas disponibles para el agente</p>
          <div className="space-y-1.5">
            {tools.slice(0, 5).map((t) => (
              <div key={t.tool_name} className="flex items-center justify-between text-sm">
                <span className="font-mono text-xs text-[var(--text-primary)] truncate">{t.tool_name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                  t.is_enabled ? "bg-[var(--success)]/15 text-[var(--success)]" : "bg-[var(--bg-hover)] text-[var(--text-muted)]"
                }`}>{t.is_enabled ? "Activa" : "Inactiva"}</span>
              </div>
            ))}
          </div>
          <div className="mt-3"><SectionLink to="/tools" label="Ver todas las tools" /></div>
        </div>

        {/* Users */}
        <div className={`${CARD} p-4`}>
          <div className="flex items-center gap-2 mb-1">
            <Users size={16} className="text-[var(--text-secondary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Usuarios</h3>
          </div>
          <p className={`${HELP} mb-3`}>Usuarios de WhatsApp autorizados</p>
          <div className="space-y-1.5">
            {users.filter((u) => u.is_active).slice(0, 5).map((u) => (
              <div key={u.phone_number} className="flex items-center justify-between text-sm">
                <span className="text-xs text-[var(--text-primary)]">{u.name || "Sin nombre"}</span>
                <span className="font-mono text-[10px] text-[var(--text-muted)]">{u.phone_number}</span>
              </div>
            ))}
          </div>
          <div className="mt-3"><SectionLink to="/users" label="Ver todos los usuarios" /></div>
        </div>

        {/* Conversations */}
        <div className={`${CARD} p-4`}>
          <div className="flex items-center gap-2 mb-1">
            <MessageSquare size={16} className="text-[var(--text-secondary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Conversaciones</h3>
          </div>
          <p className={`${HELP} mb-3`}>Historial de interacciones por usuario</p>
          <div className="space-y-1.5">
            {convs.slice(0, 5).map((c) => (
              <div key={c.phone_number} className="flex items-center justify-between text-sm">
                <span className="text-xs text-[var(--text-primary)]">{c.name || c.phone_number}</span>
                <span className={HELP}>{c.message_count} msgs</span>
              </div>
            ))}
          </div>
          <div className="mt-3"><SectionLink to="/conversations" label="Ver todas las conversaciones" /></div>
        </div>
      </div>

      <section className={`${CARD} p-4`}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-[var(--accent)]/15 p-2 text-[var(--accent)]"><Files size={20} /></div>
            <div><h3 className="text-sm font-semibold text-[var(--text-primary)]">Documentos RAG</h3><p className={HELP}>Manuales y procedimientos recuperados automáticamente por el agente</p></div>
          </div>
          {documentStats ? <div className="flex flex-wrap gap-5 text-center">
            <div><p className="text-lg font-semibold">{documentStats.documents_total}</p><p className={HELP}>documentos</p></div>
            <div><p className="text-lg font-semibold text-[var(--success)]">{documentStats.published}</p><p className={HELP}>publicados</p></div>
            <div><p className="text-lg font-semibold text-[var(--warning)]">{documentStats.processing}</p><p className={HELP}>procesando</p></div>
            <div><p className="text-lg font-semibold text-[var(--error)]">{documentStats.failed}</p><p className={HELP}>fallidos</p></div>
            <div><p className="text-lg font-semibold">{documentStats.chunks}</p><p className={HELP}>fragmentos</p></div>
          </div> : <p className={HELP}>RAG aún no inicializado</p>}
          <SectionLink to="/documents" label="Administrar documentos" />
        </div>
      </section>

      {/* ============================================================ */}
      {/* ROW 3: Audit inline                                           */}
      {/* ============================================================ */}
      <section className={CARD}>
        <div className="border-b border-[var(--border-color)] px-4 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
            <ClipboardList size={16} className="text-[var(--text-secondary)]" />
            Auditoria
          </h3>
          <p className={HELP}>Registro de las ultimas interacciones del agente</p>
        </div>
        <div className="px-4 py-3 flex flex-wrap gap-2 border-b border-[var(--border-color)]">
          <select value={auditStatus} onChange={(e) => { setAuditStatus(e.target.value); }}
            className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-2 py-1 text-xs text-[var(--text-primary)]">
            <option value="">Todos los estados</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="blocked">blocked</option>
          </select>
          <input value={auditPhone} onChange={(e) => setAuditPhone(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadAudit()}
            placeholder="Filtrar por telefono..."
            className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-2 py-1 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)] w-40" />
          <button onClick={loadAudit}
            className="flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white transition-colors">
            <Search size={12} /> Buscar
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-[var(--bg-secondary)] text-[var(--text-secondary)]">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Fecha</th>
                <th className="px-4 py-2 text-left font-medium">Telefono</th>
                <th className="px-4 py-2 text-left font-medium">Status</th>
                <th className="px-4 py-2 text-left font-medium">Tool</th>
                <th className="px-4 py-2 text-left font-medium">Duracion</th>
                <th className="px-4 py-2 text-left font-medium">Respuesta</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-color)]">
              {audits.map((a) => (
                <tr key={a.id} className="hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="px-4 py-2 whitespace-nowrap text-[var(--text-primary)]">
                    {new Date(a.created_at).toLocaleString("es-AR")}
                  </td>
                  <td className="px-4 py-2 font-mono text-[var(--text-primary)]">{a.phone_number}</td>
                  <td className="px-4 py-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      a.status === "success" ? "bg-[var(--success)]/15 text-[var(--success)]"
                      : a.status === "error" ? "bg-[var(--error)]/15 text-[var(--error)]"
                      : "bg-[var(--warning)]/15 text-[var(--warning)]"
                    }`}>{a.status}</span>
                  </td>
                  <td className="px-4 py-2 font-mono text-[var(--text-muted)]">{a.tool_used || "–"}</td>
                  <td className="px-4 py-2 text-[var(--text-muted)]">{a.duration_ms ? `${a.duration_ms}ms` : "–"}</td>
                  <td className="px-4 py-2 text-[var(--text-primary)] truncate max-w-xs">{a.response_preview || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {audits.length === 0 && <p className={`text-center py-6 ${HELP}`}>Sin registros</p>}
        </div>
        <div className="px-4 py-3 border-t border-[var(--border-color)] text-center">
          <SectionLink to="/audit" label="Ver toda la auditoria" />
        </div>
      </section>
    </div>
  );
}

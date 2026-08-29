import { AlertTriangle, Eye, Loader2, Search, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AgentAuthorizedUser } from "../../access/types";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { ApiError, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface PromptPreviewResponse {
  system_prompt: string;
  char_count: number;
  profile_name: string | null;
  placeholders_resolved: string[];
}

interface ToolInvocation {
  tool: string;
  args?: Record<string, unknown>;
  status?: string;
}

interface TestAgentResponse {
  response_text: string;
  tools_used: string[];
  tool_invocations: ToolInvocation[];
  iterations: number;
  total_tool_calls: number;
  duration_ms: number;
  status: string;
  rag_hits: {
    reference_code: string;
    title: string;
    page: number | null;
    location: string | null;
    score: number;
  }[];
}
interface ConversationSearchResult {
  id: string;
  conversation_id: string;
  display_name: string | null;
  channel: string;
  route_key: string;
  external_thread_id: string;
  role: string;
  content: string;
  created_at: string;
}

const HELP = "text-xs text-[var(--text-muted)]";

function Pill({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 py-1 text-xs text-[var(--text-secondary)]">
      <span className="text-[var(--text-muted)]">{label}:</span>
      <span className="font-mono text-[var(--text-primary)]">{value}</span>
    </span>
  );
}

export default function PromptLabPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canReadUsers = hasPermission(user, PERMISSIONS.USERS_READ);
  const activeAgentId = useRef<string | null>(selectedAgent?.id ?? null);
  const resetAgentId = useRef<string | null>(selectedAgent?.id ?? null);
  activeAgentId.current = selectedAgent?.id ?? null;
  // --- Preview del system prompt ---
  const [prompt, setPrompt] = useState<PromptPreviewResponse | null>(null);
  const [loadingPrompt, setLoadingPrompt] = useState(false);
  const [promptError, setPromptError] = useState<string | null>(null);

  const loadPrompt = async () => {
    const agentId = selectedAgent?.id;
    if (!agentId) {
      setPromptError("Seleccioná un agente para cargar su prompt.");
      return;
    }
    setLoadingPrompt(true);
    setPromptError(null);
    try {
      const res = await api<PromptPreviewResponse>("/promptlab/prompt-preview", {
        method: "POST",
        body: JSON.stringify({ agent_id: agentId }),
      });
      if (activeAgentId.current === agentId) setPrompt(res);
    } catch (e) {
      if (activeAgentId.current === agentId)
        setPromptError(e instanceof ApiError ? e.message : "Error al cargar el prompt");
    } finally {
      if (activeAgentId.current === agentId) setLoadingPrompt(false);
    }
  };

  // --- Test del agente ---
  const [message, setMessage] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestAgentResponse | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [users, setUsers] = useState<AgentAuthorizedUser[]>([]);
  const [testUserId, setTestUserId] = useState("");
  useEffect(() => {
    const agentId = selectedAgent?.id;
    setUsers([]);
    setTestUserId("");
    if (!canReadUsers || !agentId) return;
    let active = true;
    api<AgentAuthorizedUser[]>(`/agents/${agentId}/authorized-users`)
      .then((rows) => {
        if (active) setUsers(rows.filter((row) => row.is_active));
      })
      .catch(() => {
        if (active) setUsers([]);
      });
    return () => {
      active = false;
    };
  }, [canReadUsers, selectedAgent?.id]);
  useEffect(() => {
    const agentId = selectedAgent?.id ?? null;
    if (resetAgentId.current === agentId) return;
    resetAgentId.current = agentId;
    setPrompt(null);
    setTestResult(null);
    setResults([]);
    setSearched(false);
    setPromptError(null);
    setTestError(null);
    setSearchError(null);
    setLoadingPrompt(false);
    setTesting(false);
    setSearching(false);
  }, [selectedAgent?.id]);

  const runTest = async () => {
    const agentId = selectedAgent?.id;
    if (!agentId || !message.trim()) return;
    setTesting(true);
    setTestError(null);
    try {
      const res = await api<TestAgentResponse>("/promptlab/test-agent", {
        method: "POST",
        body: JSON.stringify({
          agent_id: agentId,
          message: message.trim(),
          user_id: testUserId || null,
        }),
      });
      if (activeAgentId.current === agentId) setTestResult(res);
    } catch (e) {
      if (activeAgentId.current === agentId)
        setTestError(e instanceof ApiError ? e.message : "Error al ejecutar la prueba");
    } finally {
      if (activeAgentId.current === agentId) setTesting(false);
    }
  };

  // --- Búsqueda en conversaciones ---
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ConversationSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const search = async () => {
    const agentId = selectedAgent?.id;
    if (!agentId) {
      setSearchError("Seleccioná un agente para buscar en sus conversaciones.");
      return;
    }
    if (query.trim().length < 2) {
      setSearchError("La búsqueda requiere al menos 2 caracteres.");
      return;
    }
    setSearching(true);
    setSearchError(null);
    try {
      const params = new URLSearchParams({ q: query.trim(), agent_id: agentId });
      const res = await api<ConversationSearchResult[]>(
        `/promptlab/search-conversations?${params}`,
      );
      if (activeAgentId.current !== agentId) return;
      setResults(res);
      setSearched(true);
    } catch (e) {
      if (activeAgentId.current === agentId)
        setSearchError(e instanceof ApiError ? e.message : "Error en la búsqueda");
    } finally {
      if (activeAgentId.current === agentId) setSearching(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-[var(--text-primary)]">PromptLab</h2>
        <p className={HELP}>
          Inspeccioná el system prompt real, probá el agente y buscá en el historial de
          conversaciones.
        </p>
      </div>
      {selectedAgent && (
        <p className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm text-emerald-300">
          El preview, el test y la búsqueda se ejecutan explícitamente para{" "}
          <strong>{selectedAgent.name}</strong>.
        </p>
      )}

      {/* Paneles superiores: Preview + Test */}
      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Panel izquierdo (60%) — Preview del system prompt */}
        <section className="flex flex-col rounded border border-[var(--border-color)] bg-[var(--bg-card)] lg:w-3/5">
          <div className="flex items-center justify-between border-b border-[var(--border-color)] px-4 py-3">
            <div className="flex items-center gap-2">
              <Eye className="h-4 w-4 text-[var(--accent)]" />
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">System prompt</h3>
            </div>
            <button
              type="button"
              onClick={loadPrompt}
              disabled={loadingPrompt}
              className="inline-flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {loadingPrompt ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
              {loadingPrompt ? "Cargando..." : "Cargar prompt actual"}
            </button>
          </div>

          <div className="space-y-3 p-4">
            <p className={HELP}>
              Este es el system prompt completo que recibe el modelo. Incluye identidad, directivas,
              hints de bases de datos y memoria.
            </p>

            {promptError && <p className="text-xs text-[var(--error)]">{promptError}</p>}

            {prompt && (
              <div className="flex flex-wrap gap-2">
                {prompt.profile_name && <Pill label="perfil" value={prompt.profile_name} />}
                <Pill label="chars" value={prompt.char_count} />
                {prompt.placeholders_resolved.length > 0 && (
                  <Pill label="placeholders" value={prompt.placeholders_resolved.join(", ")} />
                )}
              </div>
            )}

            <textarea
              readOnly
              value={prompt?.system_prompt ?? ""}
              placeholder='Presioná "Cargar prompt actual" para ver el system prompt.'
              rows={22}
              className="w-full resize-none rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 font-mono text-xs leading-relaxed text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none"
            />
          </div>
        </section>

        {/* Panel derecho (40%) — Test del agente */}
        <section className="flex flex-col rounded border border-[var(--border-color)] bg-[var(--bg-card)] lg:w-2/5">
          <div className="flex items-center gap-2 border-b border-[var(--border-color)] px-4 py-3">
            <Send className="h-4 w-4 text-[var(--accent)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Test del agente</h3>
          </div>

          <div className="space-y-3 p-4">
            <p className={HELP}>
              Ejecuta una consulta real contra el agente. Puede usar las herramientas habilitadas
              para el contexto elegido. No persiste la conversación.
            </p>

            <div className="flex items-start gap-2 rounded border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" />
              <p className="text-xs text-[var(--warning)]">
                Las pruebas pueden ejecutar integraciones reales. Usá fuentes de prueba y evitá
                efectos no deseados.
              </p>
            </div>

            <div>
              <label
                htmlFor="promptlab-access-context"
                className="mb-1 block text-xs font-medium text-[var(--text-secondary)]"
              >
                Contexto de acceso
              </label>
              <select
                id="promptlab-access-context"
                value={testUserId}
                onChange={(e) => setTestUserId(e.target.value)}
                className="mb-3 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-2 text-sm text-[var(--text-primary)]"
              >
                <option value="">Administrador (área General)</option>
                {users.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name || item.phone_number}
                  </option>
                ))}
              </select>
              <label
                htmlFor="promptlab-message"
                className="mb-1 block text-xs font-medium text-[var(--text-secondary)]"
              >
                Mensaje
              </label>
              <textarea
                id="promptlab-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runTest();
                }}
                placeholder="Escribí un mensaje de prueba..."
                rows={3}
                className="w-full resize-none rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] focus:outline-none"
              />
              <p className={`mt-1 ${HELP}`}>Ctrl/Cmd + Enter para enviar.</p>
            </div>

            <button
              type="button"
              onClick={runTest}
              disabled={testing || !message.trim()}
              className="inline-flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {testing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {testing ? "Ejecutando..." : "Enviar"}
            </button>

            {testError && <p className="text-xs text-[var(--error)]">{testError}</p>}

            {testResult && (
              <div className="space-y-3">
                <div className="rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3">
                  <p className="whitespace-pre-wrap text-sm text-[var(--text-primary)]">
                    {testResult.response_text || "(respuesta vacía)"}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Pill
                    label="tools"
                    value={
                      testResult.tools_used.length ? testResult.tools_used.join(", ") : "ninguna"
                    }
                  />
                  <Pill label="iteraciones" value={testResult.iterations} />
                  <Pill label="tool_calls" value={testResult.total_tool_calls} />
                  <Pill label="duración" value={`${testResult.duration_ms} ms`} />
                  <Pill label="status" value={testResult.status} />
                </div>
                {testResult.rag_hits?.length > 0 && (
                  <div className="rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3">
                    <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
                      Evidencia RAG
                    </p>
                    {testResult.rag_hits.map((hit) => (
                      <p
                        key={`${hit.reference_code}:${hit.location ?? hit.page ?? ""}:${hit.score}`}
                        className="text-xs text-[var(--text-muted)]"
                      >
                        {hit.reference_code} · {hit.title} ·{" "}
                        {hit.location || (hit.page ? `página ${hit.page}` : "sin ubicación")} ·{" "}
                        {Math.round(hit.score * 100)}%
                      </p>
                    ))}
                  </div>
                )}

                {testResult.tool_invocations && testResult.tool_invocations.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-[var(--text-secondary)]">
                      Llamadas a herramientas ({testResult.tool_invocations.length})
                    </p>
                    <div className="space-y-1.5">
                      {testResult.tool_invocations.map((ti) => (
                        <div
                          key={`${ti.tool}:${ti.status ?? ""}:${JSON.stringify(ti.args ?? {})}`}
                          className="rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-2"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs text-[var(--accent)]">
                              {ti.tool}
                            </span>
                            {ti.status && (
                              <span
                                className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                                  ti.status === "success"
                                    ? "bg-[var(--success)]/15 text-[var(--success)]"
                                    : "bg-[var(--warning)]/15 text-[var(--warning)]"
                                }`}
                              >
                                {ti.status}
                              </span>
                            )}
                          </div>
                          {ti.args && Object.keys(ti.args).length > 0 ? (
                            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[10px] text-[var(--text-secondary)]">
                              {JSON.stringify(ti.args, null, 2)}
                            </pre>
                          ) : (
                            <p className="mt-1 text-[10px] text-[var(--text-muted)]">
                              sin parámetros
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Sección inferior — Búsqueda en conversaciones */}
      <section className="rounded border border-[var(--border-color)] bg-[var(--bg-card)]">
        <div className="flex items-center gap-2 border-b border-[var(--border-color)] px-4 py-3">
          <Search className="h-4 w-4 text-[var(--accent)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            Búsqueda en conversaciones
          </h3>
        </div>

        <div className="space-y-3 p-4">
          <p className={HELP}>
            Busca mensajes únicamente dentro del historial neutral del agente seleccionado.
          </p>

          <div className="flex gap-2">
            <label htmlFor="promptlab-conversation-search" className="sr-only">
              Texto a buscar en conversaciones
            </label>
            <input
              id="promptlab-conversation-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") search();
              }}
              placeholder="Texto a buscar (mínimo 2 caracteres)..."
              className="flex-1 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] focus:outline-none"
            />
            <button
              type="button"
              onClick={search}
              disabled={searching}
              className="inline-flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {searching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Buscar
            </button>
          </div>

          {searchError && <p className="text-xs text-[var(--error)]">{searchError}</p>}

          <div className="overflow-x-auto rounded border border-[var(--border-color)]">
            <table className="w-full text-left text-sm">
              <thead className="bg-[var(--bg-secondary)] text-xs uppercase text-[var(--text-secondary)]">
                <tr>
                  <th className="px-3 py-2 font-medium">Identidad y ruta</th>
                  <th className="px-3 py-2 font-medium">Rol</th>
                  <th className="px-3 py-2 font-medium">Contenido</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">Fecha</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-color)]">
                {results.map((r) => (
                  <tr key={r.id} className="transition-colors hover:bg-[var(--bg-hover)]">
                    <td className="px-3 py-2 text-xs text-[var(--text-primary)]">
                      <span className="block font-medium">
                        {r.display_name || "Identidad sin nombre"}
                      </span>
                      <span className="mt-0.5 block text-[var(--text-muted)]">
                        <span className="uppercase">{r.channel}</span> · <code>{r.route_key}</code>
                      </span>
                      <span
                        className="block max-w-48 truncate font-mono text-[10px] text-[var(--text-muted)]"
                        title={r.external_thread_id}
                      >
                        {r.external_thread_id}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--text-secondary)]">{r.role}</td>
                    <td className="px-3 py-2 text-[var(--text-primary)]">
                      <span className="line-clamp-2">{r.content}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--text-muted)] whitespace-nowrap">
                      {new Date(r.created_at).toLocaleString("es-AR")}
                    </td>
                  </tr>
                ))}
                {results.length === 0 && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-3 py-6 text-center text-sm text-[var(--text-muted)]"
                    >
                      {searched ? "Sin resultados." : "Ingresá un término para buscar."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}

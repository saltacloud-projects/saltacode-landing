import { CheckCircle2, CircleAlert, Cpu, LoaderCircle, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { ApiError, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import type { AgentRuntime, ProviderConnection } from "../../runtime/types";

const INPUT =
  "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:opacity-60";

type NumericRuntimeKey =
  | "temperature"
  | "max_output_tokens"
  | "max_iterations"
  | "max_tool_calls"
  | "loop_timeout_seconds"
  | "tool_timeout_seconds"
  | "tool_result_max_chars"
  | "history_message_limit"
  | "history_cache_ttl_seconds"
  | "summary_trigger_messages"
  | "summary_max_chars"
  | "rag_retrieval_top_k"
  | "rag_min_relevance_score"
  | "rag_vector_weight"
  | "rag_lexical_weight";

interface NumberField {
  key: NumericRuntimeKey;
  label: string;
  min: number;
  max: number;
  step?: number;
}

const LIMIT_FIELDS: NumberField[] = [
  { key: "max_iterations", label: "Iteraciones máximas", min: 1, max: 50 },
  { key: "max_tool_calls", label: "Tool calls máximas", min: 0, max: 200 },
  { key: "loop_timeout_seconds", label: "Timeout del loop (s)", min: 1, max: 900 },
  { key: "tool_timeout_seconds", label: "Timeout de herramienta (s)", min: 1, max: 300 },
  {
    key: "tool_result_max_chars",
    label: "Máximo por resultado (caracteres)",
    min: 256,
    max: 100_000,
  },
];

const HISTORY_FIELDS: NumberField[] = [
  { key: "history_message_limit", label: "Mensajes recientes", min: 0, max: 200 },
  { key: "history_cache_ttl_seconds", label: "TTL de historial (s)", min: 0, max: 86_400 },
  { key: "summary_trigger_messages", label: "Resumir desde N mensajes", min: 1, max: 1_000 },
  { key: "summary_max_chars", label: "Máximo del resumen (caracteres)", min: 1_000, max: 500_000 },
];

const RAG_FIELDS: NumberField[] = [
  { key: "rag_retrieval_top_k", label: "Resultados recuperados", min: 1, max: 50 },
  { key: "rag_min_relevance_score", label: "Relevancia mínima", min: 0, max: 1, step: 0.01 },
  { key: "rag_vector_weight", label: "Peso vectorial", min: 0, max: 1, step: 0.01 },
  { key: "rag_lexical_weight", label: "Peso léxico", min: 0, max: 1, step: 0.01 },
];

function NumberFields({
  fields,
  draft,
  disabled,
  onChange,
}: {
  fields: NumberField[];
  draft: AgentRuntime;
  disabled: boolean;
  onChange: (key: NumericRuntimeKey, value: number) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {fields.map((field) => (
        <label key={field.key} className="text-xs">
          {field.label}
          <input
            type="number"
            min={field.min}
            max={field.max}
            step={field.step || 1}
            disabled={disabled}
            className={`${INPUT} mt-1`}
            value={draft[field.key]}
            onChange={(event) => onChange(field.key, Number(event.target.value))}
          />
        </label>
      ))}
    </div>
  );
}

export default function AgentRuntimePage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.RUNTIME_MANAGE);
  const canReadConnections = hasPermission(user, PERMISSIONS.CONNECTIONS_READ);
  const [draft, setDraft] = useState<AgentRuntime | null>(null);
  const [providers, setProviders] = useState<ProviderConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(
    async (agentId: string) => {
      setLoading(true);
      setError("");
      setMissing(false);
      try {
        const runtimeRequest = api<AgentRuntime>(`/profiles/${agentId}/runtime`);
        const providerRequest = canReadConnections
          ? api<ProviderConnection[]>("/provider-connections")
          : Promise.resolve([]);
        const [runtimeRow, providerRows] = await Promise.all([runtimeRequest, providerRequest]);
        setDraft({ ...runtimeRow });
        setProviders(providerRows);
      } catch (value) {
        if (value instanceof ApiError && value.status === 404) {
          setDraft(null);
          setMissing(true);
          if (canReadConnections) {
            try {
              setProviders(await api<ProviderConnection[]>("/provider-connections"));
            } catch {
              setProviders([]);
            }
          }
        } else {
          setError(value instanceof Error ? value.message : "No se pudo cargar el runtime.");
        }
      } finally {
        setLoading(false);
      }
    },
    [canReadConnections],
  );

  useEffect(() => {
    const agentId = selectedAgent?.id;
    if (agentId) void load(agentId);
  }, [selectedAgent?.id, load]);

  if (!selectedAgent) return null;

  const initialize = async () => {
    setSaving(true);
    setError("");
    try {
      await api(`/profiles/${selectedAgent.id}/runtime`, {
        method: "PATCH",
        body: JSON.stringify({}),
      });
      setNotice("Runtime inicializado con los valores predeterminados del servidor.");
      await load(selectedAgent.id);
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo inicializar el runtime.");
    } finally {
      setSaving(false);
    }
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const { id, agent_id, provider_ready, ...body } = draft;
      void id;
      void agent_id;
      void provider_ready;
      const updated = await api<AgentRuntime>(`/profiles/${selectedAgent.id}/runtime`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setDraft({ ...updated });
      setNotice("Configuración de runtime guardada.");
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo guardar el runtime.");
    } finally {
      setSaving(false);
    }
  };

  const updateNumber = (key: NumericRuntimeKey, value: number) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  const activeProviders = providers.filter((provider) => provider.is_active);
  const providerReady = canReadConnections
    ? activeProviders.some(
        (provider) => provider.id === draft?.provider_connection_id && provider.has_credentials,
      )
    : Boolean(draft?.provider_ready);

  return (
    <div className="max-w-5xl space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <Cpu className="text-[var(--accent)]" size={22} />
        <div>
          <h2 className="text-xl font-semibold">Runtime de {selectedAgent.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            Modelo, límites de ejecución, historial, resúmenes y recuperación documental.
          </p>
        </div>
        {canManage && draft && (
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50"
          >
            {saving ? <LoaderCircle className="animate-spin" size={15} /> : <Save size={15} />}{" "}
            Guardar
          </button>
        )}
      </header>
      {error && (
        <p
          className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400"
          role="alert"
        >
          {error}
        </p>
      )}
      {notice && (
        <p
          className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400"
          role="status"
        >
          {notice}
        </p>
      )}
      {loading ? (
        <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status">
          <LoaderCircle className="animate-spin" size={16} /> Cargando runtime…
        </p>
      ) : missing ? (
        <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-5">
          <h3 className="font-semibold">Runtime sin configurar</h3>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Este agente todavía usa únicamente los defaults de infraestructura. Inicializar crea su
            configuración persistida.
          </p>
          {canManage && (
            <button
              type="button"
              onClick={initialize}
              disabled={saving}
              className="mt-4 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50"
            >
              Inicializar runtime
            </button>
          )}
        </section>
      ) : (
        draft && (
          <>
            <section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
              <div>
                <h3 className="font-semibold">Proveedor y modelos</h3>
                <p className="text-xs text-[var(--text-muted)]">
                  La API key se administra en Conexiones de IA, no en el runtime.
                </p>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {canReadConnections ? (
                  <label className="text-xs">
                    Conexión de IA
                    <select
                      disabled={!canManage}
                      className={`${INPUT} mt-1`}
                      value={draft.provider_connection_id || ""}
                      onChange={(event) =>
                        setDraft({ ...draft, provider_connection_id: event.target.value || null })
                      }
                    >
                      <option value="">Sin conexión asignada</option>
                      {activeProviders.map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name}
                          {provider.has_credentials ? "" : " · sin secreto"}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <div className="text-xs">
                    Conexión de IA
                    <code className="mt-1 block rounded border border-[var(--border-color)] p-2">
                      {draft.provider_connection_id || "Sin conexión"}
                    </code>
                  </div>
                )}
                <div className="self-end rounded border border-[var(--border-color)] p-3 text-sm">
                  <p className="text-xs text-[var(--text-muted)]">Preparación del proveedor</p>
                  <p
                    className={`mt-1 flex items-center gap-2 ${providerReady ? "text-emerald-400" : "text-amber-300"}`}
                  >
                    {providerReady ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
                    {providerReady ? "Activo y con credencial" : "No está listo para ejecutar"}
                  </p>
                </div>
                <label className="text-xs">
                  Modelo de chat
                  <input
                    disabled={!canManage}
                    className={`${INPUT} mt-1 font-mono`}
                    value={draft.chat_model}
                    onChange={(event) => setDraft({ ...draft, chat_model: event.target.value })}
                  />
                </label>
                <label className="text-xs">
                  Modelo de transcripción
                  <input
                    disabled={!canManage}
                    className={`${INPUT} mt-1 font-mono`}
                    value={draft.transcription_model}
                    onChange={(event) =>
                      setDraft({ ...draft, transcription_model: event.target.value })
                    }
                  />
                </label>
                <label className="text-xs">
                  Temperatura
                  <input
                    type="number"
                    min={0}
                    max={2}
                    step={0.01}
                    disabled={!canManage}
                    className={`${INPUT} mt-1`}
                    value={draft.temperature}
                    onChange={(event) => updateNumber("temperature", Number(event.target.value))}
                  />
                </label>
                <label className="text-xs">
                  Tokens máximos de salida
                  <input
                    type="number"
                    min={1}
                    max={128000}
                    disabled={!canManage}
                    className={`${INPUT} mt-1`}
                    value={draft.max_output_tokens}
                    onChange={(event) =>
                      updateNumber("max_output_tokens", Number(event.target.value))
                    }
                  />
                </label>
              </div>
            </section>
            <section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
              <div>
                <h3 className="font-semibold">Loop y herramientas</h3>
                <p className="text-xs text-[var(--text-muted)]">
                  Límites duros de ejecución para controlar latencia, costo y abuso.
                </p>
              </div>
              <NumberFields
                fields={LIMIT_FIELDS}
                draft={draft}
                disabled={!canManage}
                onChange={updateNumber}
              />
            </section>
            <section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="font-semibold">Historial y resúmenes</h3>
                  <p className="text-xs text-[var(--text-muted)]">
                    Ventana reciente y compactación de conversaciones extensas.
                  </p>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    disabled={!canManage}
                    checked={draft.summary_enabled}
                    onChange={(event) =>
                      setDraft({ ...draft, summary_enabled: event.target.checked })
                    }
                  />{" "}
                  Resúmenes habilitados
                </label>
              </div>
              <NumberFields
                fields={HISTORY_FIELDS}
                draft={draft}
                disabled={!canManage}
                onChange={updateNumber}
              />
            </section>
            <section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="font-semibold">RAG</h3>
                  <p className="text-xs text-[var(--text-muted)]">
                    Política de recuperación sobre las áreas documentales asignadas.
                  </p>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    disabled={!canManage}
                    checked={draft.rag_enabled}
                    onChange={(event) => setDraft({ ...draft, rag_enabled: event.target.checked })}
                  />{" "}
                  RAG habilitado
                </label>
              </div>
              <NumberFields
                fields={RAG_FIELDS}
                draft={draft}
                disabled={!canManage}
                onChange={updateNumber}
              />
            </section>
          </>
        )
      )}
    </div>
  );
}

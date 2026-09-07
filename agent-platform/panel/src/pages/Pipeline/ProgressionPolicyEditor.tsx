import { LoaderCircle, RefreshCw, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";

interface ProgressionPolicy {
  agent_id: string;
  quote_request_action: "keep_agent" | "handoff";
  version: number;
  is_configured: boolean;
}

export function ProgressionPolicyEditor({
  agentId,
  canManage,
}: {
  agentId: string;
  canManage: boolean;
}) {
  const [policy, setPolicy] = useState<ProgressionPolicy | null>(null);
  const [action, setAction] = useState<ProgressionPolicy["quote_request_action"]>("handoff");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const endpoint = `/agents/${encodeURIComponent(agentId)}/progression-policy`;

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const current = await api<ProgressionPolicy>(endpoint);
      setPolicy(current);
      setAction(current.quote_request_action);
      setConflict(false);
    } catch (value) {
      setPolicy(null);
      setError(
        value instanceof ApiError && value.status === 403
          ? "No tenés permiso para consultar la política de este agente."
          : "No se pudo cargar la política de este agente.",
      );
    } finally {
      setBusy(false);
    }
  }, [endpoint]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!policy || busy || !canManage || conflict) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const current = await api<ProgressionPolicy>(endpoint, {
        method: "PUT",
        body: JSON.stringify({ expected_version: policy.version, quote_request_action: action }),
      });
      setPolicy(current);
      setAction(current.quote_request_action);
      setNotice(
        "Política guardada para este agente. No cambia oportunidades existentes ni reanuda conversaciones manuales.",
      );
    } catch (value) {
      if (value instanceof ApiError && value.status === 409) {
        setConflict(true);
        setError(
          "La política cambió en otra sesión. Recargá su versión actual y revisala antes de guardar.",
        );
      } else
        setError(
          value instanceof ApiError && value.status === 403
            ? "No tenés permiso para modificar esta política."
            : "No se pudo confirmar el cambio. Recargá la política antes de reintentar.",
        );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      aria-labelledby="progression-policy-title"
      className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5"
    >
      <h3 id="progression-policy-title" className="font-semibold">
        Cuando solicita un presupuesto
      </h3>
      {busy && !policy && (
        <p role="status" className="flex items-center gap-2 text-sm">
          <LoaderCircle size={16} className="animate-spin" /> Cargando política…
        </p>
      )}
      {policy && (
        <>
          <p className="text-sm text-[var(--text-muted)]">
            La captura válida de datos y consentimiento crea la oportunidad. Esta regla persistente
            define quién continúa atendiendo; no la decide libremente el modelo.
          </p>
          {!policy.is_configured && (
            <p className="rounded border border-amber-500/30 p-3 text-sm">
              Sin decisión explícita guardada: se conserva el comportamiento anterior, que exige una
              derivación configurada hacia otro agente. Sin esa regla, la captura comercial queda
              bloqueada.
            </p>
          )}
          <fieldset
            disabled={!canManage || busy || conflict}
            className="space-y-3 disabled:opacity-60"
          >
            <legend className="mb-2 text-sm font-medium">Responsable después de la captura</legend>
            <label className="flex min-h-11 items-start gap-3 rounded border border-[var(--border-color)] p-3 text-sm">
              <input
                className="mt-1"
                type="radio"
                name="quote_request_action"
                value="keep_agent"
                checked={action === "keep_agent"}
                onChange={() => setAction("keep_agent")}
              />
              <span>
                <strong>Continuar con el mismo agente</strong>
                <span className="mt-1 block text-[var(--text-muted)]">
                  Crea la oportunidad sin exigir un segundo agente. Mantiene el control humano si la
                  conversación está intervenida.
                </span>
              </span>
            </label>
            <label className="flex min-h-11 items-start gap-3 rounded border border-[var(--border-color)] p-3 text-sm">
              <input
                className="mt-1"
                type="radio"
                name="quote_request_action"
                value="handoff"
                checked={action === "handoff"}
                onChange={() => setAction("handoff")}
              />
              <span>
                <strong>Derivar a un agente especializado</strong>
                <span className="mt-1 block text-[var(--text-muted)]">
                  Requiere una regla activa de solicitud de presupuesto con destino explícito.
                  Configurá esa derivación antes de utilizar el flujo.
                </span>
              </span>
            </label>
          </fieldset>
          <p className="text-xs text-[var(--text-muted)]">
            Versión {policy.version}. Solicitar un presupuesto no equivale a calcularlo, aprobarlo
            ni enviarlo. El presupuesto debe provenir de la integración autoritativa y respetar su
            aprobación.
          </p>
          {canManage && (
            <button
              type="button"
              onClick={save}
              disabled={busy || conflict}
              className="inline-flex min-h-11 items-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}{" "}
              Guardar política
            </button>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-emerald-400">
          {notice}
        </p>
      )}
      {(error || conflict) && (
        <button
          type="button"
          disabled={busy}
          onClick={load}
          className="inline-flex min-h-11 items-center gap-2 rounded border border-[var(--border-color)] px-3 py-2 text-sm"
        >
          <RefreshCw size={16} /> Recargar política
        </button>
      )}
    </section>
  );
}

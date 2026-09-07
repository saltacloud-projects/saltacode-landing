import { LoaderCircle, Power } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import type { AgentProfile } from "../../agents/types";
import { ApiError, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import type { AgentRuntime } from "../../runtime/types";

export function AgentSetupPanel({ agent }: { agent: AgentProfile }) {
  const { user } = useAuth();
  const { refreshProfiles } = useAgentWorkspace();
  const [runtimeStatus, setRuntimeStatus] = useState("Sin verificar");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const canReadRuntime = hasPermission(user, PERMISSIONS.RUNTIME_READ);
  const canActivate = hasPermission(user, PERMISSIONS.ALL);

  useEffect(() => {
    let cancelled = false;
    setError("");
    setRuntimeStatus(canReadRuntime ? "Verificando configuración…" : "Sin permiso de consulta");
    if (canReadRuntime) {
      api<AgentRuntime>(`/profiles/${agent.id}/runtime`)
        .then((runtime) => {
          if (!cancelled)
            setRuntimeStatus(
              runtime.provider_ready
                ? "Modelo y proveedor configurados; falta verificar respuesta real"
                : "Falta configurar proveedor y modelo",
            );
        })
        .catch((value) => {
          if (!cancelled)
            setRuntimeStatus(
              value instanceof ApiError && value.status === 404
                ? "Runtime pendiente de configurar"
                : "No se pudo verificar; revisá permisos o conexión",
            );
        });
    }
    return () => {
      cancelled = true;
    };
  }, [agent.id, canReadRuntime]);

  const activate = async () => {
    setBusy(true);
    setError("");
    try {
      await api(`/profiles/${agent.id}/activate`, { method: "POST" });
      await refreshProfiles();
    } catch (value) {
      setError(
        value instanceof ApiError && value.status === 403
          ? "No tenés permiso para activar este agente."
          : "No se pudo activar el agente. Revisá su estado antes de reintentar.",
      );
    } finally {
      setBusy(false);
    }
  };

  const links = [
    { path: "runtime", label: "Modelo y límites", permission: PERMISSIONS.RUNTIME_READ },
    { path: "knowledge", label: "Conocimiento", permission: PERMISSIONS.KNOWLEDGE_READ },
    { path: "tools", label: "Herramientas", permission: PERMISSIONS.TOOLS_READ },
    { path: "sources", label: "Fuentes", permission: PERMISSIONS.SOURCES_READ },
    { path: "documents", label: "Documentos", permission: PERMISSIONS.DOCUMENTS_READ },
    { path: "channels", label: "Rutas de ingreso", permission: PERMISSIONS.RUNTIME_READ },
    { path: "promptlab", label: "Probar instrucciones", permission: PERMISSIONS.PROMPTLAB_USE },
  ];
  return (
    <section
      aria-labelledby="agent-setup-title"
      className="space-y-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
    >
      <h3 id="agent-setup-title" className="font-semibold">
        Preparación del agente
      </h3>
      <p className="text-sm">
        Estado: <strong>{agent.is_active ? "Habilitado" : "Inactivo"}</strong> · {runtimeStatus}
      </p>
      <p className="text-sm text-[var(--text-muted)]">
        La identidad y la retención se guardan aquí. Su modelo, límites y recursos se configuran por
        separado. Vincular un recurso compartido no lo asigna a otros agentes.
      </p>
      <nav aria-label="Configuración del agente" className="flex flex-wrap gap-2">
        {links
          .filter((link) => hasPermission(user, link.permission))
          .map((link) => (
            <Link
              key={link.path}
              to={`/agents/${agent.id}/${link.path}`}
              className="inline-flex min-h-11 items-center rounded border border-[var(--border-color)] px-3 py-2 text-sm"
            >
              {link.label}
            </Link>
          ))}
      </nav>
      <p className="text-xs text-[var(--text-muted)]">
        Habilitar permite ejecutar este agente, pero no crea rutas, no configura credenciales ni
        verifica disponibilidad. Puede atender por una ruta propia o recibir una derivación del
        pipeline. No desactiva a otros agentes.
      </p>
      {!agent.is_active && canActivate && (
        <button
          type="button"
          disabled={busy}
          onClick={activate}
          className="inline-flex min-h-11 items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50"
        >
          {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Power size={16} />}
          Habilitar agente
        </button>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
    </section>
  );
}

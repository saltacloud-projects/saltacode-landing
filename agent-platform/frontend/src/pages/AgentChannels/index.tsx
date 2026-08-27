import { Globe2, MessageCircle, Network } from "lucide-react";
import { Link } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import UsersPage from "../Users";

export default function AgentChannelsPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canReadWhatsApp = hasPermission(user, PERMISSIONS.USERS_READ);

  if (!selectedAgent) return null;

  return (
    <div className="max-w-6xl space-y-5">
      <header>
        <h2 className="text-xl font-semibold">Canales de {selectedAgent.name}</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">Estado visible del agente y límites de configuración actuales.</p>
      </header>
      <div className="grid gap-3 md:grid-cols-3">
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <Globe2 className="text-[var(--accent)]" size={20} />
          <h3 className="mt-3 font-semibold">Web</h3>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">{selectedAgent.is_public ? "Habilitado para selección pública." : "No disponible para el canal público."}</p>
          <Link className="mt-3 inline-flex text-sm text-[var(--accent)] hover:underline" to={`/agents/${selectedAgent.id}/identity`}>Configurar disponibilidad</Link>
        </article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <MessageCircle className="text-[var(--accent)]" size={20} />
          <h3 className="mt-3 font-semibold">WhatsApp</h3>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">La credencial y el número todavía pertenecen a la plataforma; no existe configuración persistida por agente.</p>
        </article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <Network className="text-[var(--accent)]" size={20} />
          <h3 className="mt-3 font-semibold">API</h3>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">El acceso interno enruta agentes por contrato del servidor. No hay credenciales editables desde esta vista.</p>
        </article>
      </div>
      {canReadWhatsApp && (
        <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
          <p className="mb-4 text-sm text-amber-300">Compatibilidad: la lista siguiente es global para WhatsApp y no está aislada por agente.</p>
          <UsersPage embedded />
        </section>
      )}
    </div>
  );
}

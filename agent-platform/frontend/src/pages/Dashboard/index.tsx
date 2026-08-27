import {
  Brain,
  Cable,
  CheckCircle2,
  CircleOff,
  Files,
  FlaskConical,
  Globe2,
  MessageSquare,
  Settings2,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface WorkspaceLink {
  label: string;
  description: string;
  segment: string;
  icon: LucideIcon;
  permission?: string;
}

const LINKS: WorkspaceLink[] = [
  { label: "Identidad", description: "Prompts, mensajes, exposición y retención.", segment: "identity", icon: Settings2, permission: PERMISSIONS.PROFILES_READ },
  { label: "Conocimiento", description: "Bloques asignados desde la biblioteca.", segment: "knowledge", icon: Brain, permission: PERMISSIONS.KNOWLEDGE_READ },
  { label: "Documentos", description: "Áreas documentales asociadas al agente.", segment: "documents", icon: Files, permission: PERMISSIONS.DOCUMENTS_READ },
  { label: "Fuentes", description: "APIs y secretos write-only asignados.", segment: "sources", icon: Cable, permission: PERMISSIONS.SOURCES_READ },
  { label: "Herramientas", description: "Capacidades HTTP habilitadas para el agente.", segment: "tools", icon: Wrench, permission: PERMISSIONS.TOOLS_READ },
  { label: "Canales", description: "Web y estado de compatibilidad de WhatsApp/API.", segment: "channels", icon: Globe2 },
  { label: "Conversaciones", description: "Historial del agente seleccionado.", segment: "conversations", icon: MessageSquare, permission: PERMISSIONS.CONVERSATIONS_READ },
  { label: "PromptLab", description: "Previsualización y pruebas controladas.", segment: "promptlab", icon: FlaskConical, permission: PERMISSIONS.PROMPTLAB_USE },
];

export default function DashboardPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  if (!selectedAgent) return null;

  const visibleLinks = LINKS.filter((item) => !item.permission || hasPermission(user, item.permission));

  return (
    <div className="max-w-6xl space-y-6">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--accent)]">Agente seleccionado</p>
        <h2 className="mt-1 text-2xl font-bold">{selectedAgent.name}</h2>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-secondary)]">{selectedAgent.description || "Sin descripción."}</p>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Estado del agente">
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"><p className="text-xs text-[var(--text-muted)]">Estado</p><p className="mt-2 flex items-center gap-2 font-medium">{selectedAgent.is_active ? <CheckCircle2 className="text-emerald-400" size={17} /> : <CircleOff className="text-amber-400" size={17} />}{selectedAgent.is_active ? "Activo" : "Inactivo"}</p></article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"><p className="text-xs text-[var(--text-muted)]">Web pública</p><p className="mt-2 font-medium">{selectedAgent.is_public ? "Disponible" : "No disponible"}</p></article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"><p className="text-xs text-[var(--text-muted)]">Retención</p><p className="mt-2 font-medium">{selectedAgent.retention_days} días</p></article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"><p className="text-xs text-[var(--text-muted)]">Identificador</p><code className="mt-2 block truncate text-sm">{selectedAgent.slug}</code></article>
      </section>

      <section>
        <h3 className="text-base font-semibold">Configurar este agente</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visibleLinks.map((item) => {
            const Icon = item.icon;
            return <Link key={item.segment} to={`/agents/${selectedAgent.id}/${item.segment}`} className="group rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 transition-colors hover:border-[var(--accent)]"><Icon className="text-[var(--accent)]" size={19} /><h4 className="mt-3 font-semibold group-hover:text-[var(--accent)]">{item.label}</h4><p className="mt-1 text-sm text-[var(--text-secondary)]">{item.description}</p></Link>;
          })}
        </div>
      </section>

      <aside className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-200">
        Las bibliotecas de fuentes, herramientas, conocimiento y documentos son compartidas. La asignación determina qué recursos pertenecen a este agente; editar un recurso de biblioteca puede afectar a otros agentes que también lo usen.
      </aside>
    </div>
  );
}

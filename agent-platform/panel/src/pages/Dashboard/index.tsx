import {
  ArrowRightLeft,
  Brain,
  Cable,
  CheckCircle2,
  CircleOff,
  ClipboardList,
  Cpu,
  Files,
  FlaskConical,
  Globe2,
  Inbox,
  Library,
  type LucideIcon,
  Send,
  Settings2,
  ShieldCheck,
  Target,
  Wrench,
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

interface WorkspaceSection {
  id: string;
  title: string;
  description: string;
  links: WorkspaceLink[];
}

interface PlatformLink {
  label: string;
  to: string;
  permission: string;
}

const WORKSPACE_SECTIONS: WorkspaceSection[] = [
  {
    id: "operate",
    title: "Operar",
    description: "Gestioná conversaciones, oportunidades y entregas del agente seleccionado.",
    links: [
      {
        label: "Inbox",
        description: "Revisá conversaciones y tomá o devolvé el control humano.",
        segment: "inbox",
        icon: Inbox,
        permission: PERMISSIONS.CONVERSATIONS_READ,
      },
      {
        label: "Oportunidades",
        description: "Calificá y seguí oportunidades vinculadas a este agente.",
        segment: "opportunities",
        icon: Target,
        permission: PERMISSIONS.OPPORTUNITIES_READ,
      },
      {
        label: "Entregas",
        description: "Verificá envíos confirmados, pendientes o inciertos.",
        segment: "deliveries",
        icon: Send,
        permission: PERMISSIONS.DELIVERIES_READ,
      },
      {
        label: "Auditoría",
        description: "Consultá acciones y cambios atribuidos a este agente.",
        segment: "audit",
        icon: ClipboardList,
        permission: PERMISSIONS.AUDIT_READ,
      },
    ],
  },
  {
    id: "automate",
    title: "Automatizar",
    description: "Definí derivaciones y probá el comportamiento antes de habilitarlo.",
    links: [
      {
        label: "Handoffs",
        description: "Configurá reglas explícitas para derivar oportunidades entre agentes.",
        segment: "handoffs",
        icon: ArrowRightLeft,
        permission: PERMISSIONS.OPPORTUNITIES_MANAGE,
      },
      {
        label: "PromptLab",
        description: "Probá prompts sin asumir que el canal ya está disponible.",
        segment: "promptlab",
        icon: FlaskConical,
        permission: PERMISSIONS.PROMPTLAB_USE,
      },
    ],
  },
  {
    id: "configure",
    title: "Configurar agente",
    description: "Ajustá su identidad y vinculá recursos de las bibliotecas globales.",
    links: [
      {
        label: "Identidad",
        description: "Nombre, instrucciones, mensajes y retención.",
        segment: "identity",
        icon: Settings2,
        permission: PERMISSIONS.PROFILES_READ,
      },
      {
        label: "Runtime",
        description: "Conexión de IA, modelos, límites, memoria y RAG.",
        segment: "runtime",
        icon: Cpu,
        permission: PERMISSIONS.RUNTIME_READ,
      },
      {
        label: "Conocimiento",
        description: "Vinculá bloques disponibles en la biblioteca global.",
        segment: "knowledge",
        icon: Brain,
        permission: PERMISSIONS.KNOWLEDGE_READ,
      },
      {
        label: "Documentos",
        description: "Vinculá áreas documentales de la biblioteca global.",
        segment: "documents",
        icon: Files,
        permission: PERMISSIONS.DOCUMENTS_READ,
      },
      {
        label: "Fuentes",
        description: "Vinculá APIs configuradas en la biblioteca global.",
        segment: "sources",
        icon: Cable,
        permission: PERMISSIONS.SOURCES_READ,
      },
      {
        label: "Herramientas",
        description: "Habilitá capacidades disponibles en la biblioteca global.",
        segment: "tools",
        icon: Wrench,
        permission: PERMISSIONS.TOOLS_READ,
      },
      {
        label: "Canales",
        description: "Asigná rutas a conexiones de canal verificadas por separado.",
        segment: "channels",
        icon: Globe2,
        permission: PERMISSIONS.RUNTIME_READ,
      },
      {
        label: "Acceso WhatsApp",
        description: "Administrá identidades y áreas autorizadas en WhatsApp.",
        segment: "access",
        icon: ShieldCheck,
        permission: PERMISSIONS.USERS_READ,
      },
    ],
  },
];

const PLATFORM_LINKS: PlatformLink[] = [
  { label: "Fuentes", to: "/shared/sources", permission: PERMISSIONS.SOURCES_READ },
  {
    label: "Conocimiento",
    to: "/shared/knowledge",
    permission: PERMISSIONS.KNOWLEDGE_READ,
  },
  { label: "Herramientas", to: "/shared/tools", permission: PERMISSIONS.TOOLS_READ },
  { label: "Documentos", to: "/shared/documents", permission: PERMISSIONS.DOCUMENTS_READ },
];

export default function DashboardPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  if (!selectedAgent) return null;

  const visibleSections = WORKSPACE_SECTIONS.map((section) => ({
    ...section,
    links: section.links.filter((item) => !item.permission || hasPermission(user, item.permission)),
  })).filter((section) => section.links.length > 0);
  const visiblePlatformLinks = PLATFORM_LINKS.filter((item) =>
    hasPermission(user, item.permission),
  );

  return (
    <div className="max-w-6xl space-y-8">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--accent)]">
          Agente seleccionado
        </p>
        <h2 className="mt-1 text-2xl font-bold">{selectedAgent.name}</h2>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-secondary)]">
          {selectedAgent.description || "Sin descripción."}
        </p>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Estado del agente">
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <p className="text-xs text-[var(--text-muted)]">Perfil</p>
          <p className="mt-2 flex items-center gap-2 font-medium">
            {selectedAgent.is_active ? (
              <CheckCircle2 className="text-emerald-400" size={17} aria-hidden="true" />
            ) : (
              <CircleOff className="text-amber-400" size={17} aria-hidden="true" />
            )}
            {selectedAgent.is_active ? "Habilitado" : "Deshabilitado"}
          </p>
        </article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <p className="text-xs text-[var(--text-muted)]">Publicación web</p>
          <p className="mt-2 font-medium">
            {selectedAgent.is_public ? "Permitida" : "No permitida"}
          </p>
        </article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <p className="text-xs text-[var(--text-muted)]">Retención</p>
          <p className="mt-2 font-medium">{selectedAgent.retention_days} días</p>
        </article>
        <article className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <p className="text-xs text-[var(--text-muted)]">Identificador</p>
          <code className="mt-2 block truncate text-sm">{selectedAgent.slug}</code>
        </article>
      </section>

      <p
        className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-4 text-sm text-[var(--text-secondary)]"
        role="note"
      >
        Perfil habilitado y publicación permitida no prueban disponibilidad. El proveedor, el
        modelo, la conexión y cada ruta de canal requieren configuración y verificación separadas.
      </p>

      {visibleSections.map((section) => (
        <section key={section.id} aria-labelledby={`dashboard-${section.id}`}>
          <h3 id={`dashboard-${section.id}`} className="text-base font-semibold">
            {section.title}
          </h3>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">{section.description}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {section.links.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.segment}
                  to={`/agents/${selectedAgent.id}/${item.segment}`}
                  className="group rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 transition-colors hover:border-[var(--accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  <Icon className="text-[var(--accent)]" size={19} aria-hidden="true" />
                  <h4 className="mt-3 font-semibold group-hover:text-[var(--accent)]">
                    {item.label}
                  </h4>
                  <p className="mt-1 text-sm text-[var(--text-secondary)]">{item.description}</p>
                </Link>
              );
            })}
          </div>
        </section>
      ))}

      {visiblePlatformLinks.length > 0 && (
        <aside
          className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-4"
          aria-labelledby="platform-library-title"
        >
          <div className="flex gap-3">
            <Library
              className="mt-0.5 shrink-0 text-[var(--accent)]"
              size={19}
              aria-hidden="true"
            />
            <div>
              <h3 id="platform-library-title" className="font-semibold">
                Biblioteca global de la plataforma
              </h3>
              <p className="mt-1 text-sm text-[var(--text-secondary)]">
                Creá y mantené recursos compartidos acá. Después vinculalos desde la configuración
                del agente; editar un recurso global puede afectar a todos los agentes que lo usan.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {visiblePlatformLinks.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    className="rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2 text-sm font-medium text-[var(--text-primary)] hover:border-[var(--accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}

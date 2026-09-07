import {
  ArrowRightLeft,
  Bot,
  Brain,
  Cable,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  CloudCog,
  Cpu,
  Files,
  FlaskConical,
  Gauge,
  Globe2,
  Inbox,
  Library,
  ListChecks,
  LogOut,
  type LucideIcon,
  Menu,
  Send,
  ShieldCheck,
  Target,
  Webhook,
  Wrench,
  X,
} from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAgentWorkspace } from "../agents/AgentWorkspaceContext";
import { useAuth } from "../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../auth/permissions";
import RouteLoading from "./RouteLoading";

interface NavigationItem {
  to: string;
  label: string;
  icon: LucideIcon;
  permission?: string;
  end?: boolean;
}

interface NavigationGroup {
  id: string;
  label: string;
  description?: string;
  items: NavigationItem[];
}

interface WorkspaceNavigationItem extends Omit<NavigationItem, "to"> {
  segment: string;
}

interface WorkspaceNavigationGroup {
  id: string;
  label: string;
  description?: string;
  items: WorkspaceNavigationItem[];
}

const PLATFORM_GROUPS: NavigationGroup[] = [
  {
    id: "crm-operate",
    label: "Operar",
    items: [
      { to: "/inbox", label: "Inbox", icon: Inbox, permission: PERMISSIONS.CONVERSATIONS_READ },
      {
        to: "/opportunities",
        label: "Oportunidades",
        icon: Target,
        permission: PERMISSIONS.OPPORTUNITIES_READ,
      },
      {
        to: "/meetings",
        label: "Reuniones",
        icon: CalendarDays,
        permission: PERMISSIONS.MEETINGS_READ,
      },
      {
        to: "/follow-ups",
        label: "Seguimientos",
        icon: ListChecks,
        permission: PERMISSIONS.FOLLOW_UPS_READ,
      },
      { to: "/deliveries", label: "Entregas", icon: Send, permission: PERMISSIONS.DELIVERIES_READ },
      {
        to: "/inbound-jobs",
        label: "Ingresos externos",
        icon: Webhook,
        permission: PERMISSIONS.INBOUND_READ,
      },
      { to: "/audit", label: "Auditoría", icon: ClipboardList, permission: PERMISSIONS.AUDIT_READ },
    ],
  },
  {
    id: "crm-channels",
    label: "Canales",
    items: [
      {
        to: "/channels",
        label: "Canales y conexiones",
        icon: Globe2,
        permission: PERMISSIONS.CONNECTIONS_READ,
        end: true,
      },
    ],
  },
  {
    id: "crm-agents",
    label: "Agentes",
    items: [
      {
        to: "/agents",
        label: "Administrar agentes",
        icon: Bot,
        permission: PERMISSIONS.PROFILES_READ,
        end: true,
      },
    ],
  },
  {
    id: "crm-automation",
    label: "Automatización",
    items: [
      {
        to: "/pipeline",
        label: "Pipeline comercial",
        icon: ArrowRightLeft,
        permission: PERMISSIONS.RUNTIME_READ,
      },
    ],
  },
  {
    id: "crm-settings",
    label: "Configuración compartida",
    description: "Recursos reutilizables; cada agente autoriza sus vínculos.",
    items: [
      {
        to: "/shared/provider-connections",
        label: "Proveedores de IA",
        icon: CloudCog,
        permission: PERMISSIONS.CONNECTIONS_READ,
      },
      {
        to: "/shared/sources",
        label: "Fuentes API",
        icon: Cable,
        permission: PERMISSIONS.SOURCES_READ,
      },
      {
        to: "/shared/tools",
        label: "Herramientas",
        icon: Wrench,
        permission: PERMISSIONS.TOOLS_READ,
      },
      {
        to: "/shared/knowledge",
        label: "Conocimiento",
        icon: Library,
        permission: PERMISSIONS.KNOWLEDGE_READ,
      },
      {
        to: "/shared/documents",
        label: "Documentos",
        icon: Files,
        permission: PERMISSIONS.DOCUMENTS_READ,
      },
      {
        to: "/panel-users",
        label: "Accesos del panel",
        icon: ShieldCheck,
        permission: PERMISSIONS.PANEL_USERS_MANAGE,
      },
    ],
  },
];

const WORKSPACE_GROUPS: WorkspaceNavigationGroup[] = [
  {
    id: "workspace-configure",
    label: "Configurar agente",
    description: "Vinculá bibliotecas globales y ajustá sólo este agente.",
    items: [
      {
        segment: "overview",
        label: "Resumen",
        icon: Gauge,
        permission: PERMISSIONS.DASHBOARD_READ,
      },
      {
        segment: "promptlab",
        label: "PromptLab",
        icon: FlaskConical,
        permission: PERMISSIONS.PROMPTLAB_USE,
      },
      {
        segment: "identity",
        label: "Identidad",
        icon: Bot,
        permission: PERMISSIONS.PROFILES_READ,
      },
      {
        segment: "runtime",
        label: "Runtime",
        icon: Cpu,
        permission: PERMISSIONS.RUNTIME_READ,
      },
      {
        segment: "knowledge",
        label: "Conocimiento",
        icon: Brain,
        permission: PERMISSIONS.KNOWLEDGE_READ,
      },
      {
        segment: "documents",
        label: "Documentos",
        icon: Files,
        permission: PERMISSIONS.DOCUMENTS_READ,
      },
      {
        segment: "sources",
        label: "Fuentes",
        icon: Cable,
        permission: PERMISSIONS.SOURCES_READ,
      },
      {
        segment: "tools",
        label: "Herramientas",
        icon: Wrench,
        permission: PERMISSIONS.TOOLS_READ,
      },
      {
        segment: "channels",
        label: "Canales",
        icon: Globe2,
        permission: PERMISSIONS.RUNTIME_READ,
      },
      {
        segment: "access",
        label: "Acceso WhatsApp",
        icon: ShieldCheck,
        permission: PERMISSIONS.USERS_READ,
      },
    ],
  },
];

function NavigationLink({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavigationItem;
  collapsed: boolean;
  onNavigate: () => void;
}) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={collapsed ? item.label : undefined}
      onClick={onNavigate}
      className={({ isActive }) =>
        `flex min-h-10 items-center gap-3 border-l-2 px-4 py-2 text-sm transition-colors ${collapsed ? "md:justify-center" : ""} ${isActive ? "border-[var(--accent)] bg-[var(--bg-hover)] text-[var(--text-primary)]" : "border-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"}`
      }
    >
      <Icon size={18} className="shrink-0" />
      <span className={`${collapsed ? "md:hidden" : ""} truncate`}>{item.label}</span>
    </NavLink>
  );
}

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const { profiles, selectedAgent, loading: loadingAgents } = useAgentWorkspace();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const platformGroups = PLATFORM_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.permission || hasPermission(user, item.permission)),
  })).filter((group) => group.items.length > 0);
  const isAgentConfiguration = Boolean(
    selectedAgent &&
      !/^\/agents\/[^/]+\/(inbox|opportunities|meetings|follow-ups|inbound-jobs|deliveries|audit|conversations)(?:\/|$)/.test(
        location.pathname,
      ),
  );
  const workspaceGroups =
    selectedAgent && isAgentConfiguration
      ? WORKSPACE_GROUPS.map((group) => ({
          ...group,
          items: group.items
            .filter((item) => !item.permission || hasPermission(user, item.permission))
            .map((item) => ({
              ...item,
              to: `/agents/${selectedAgent.id}/${item.segment}`,
            })),
        })).filter((group) => group.items.length > 0)
      : [];

  const closeMobileNavigation = (restoreFocus = false) => {
    setMobileOpen(false);
    if (restoreFocus) requestAnimationFrame(() => menuButtonRef.current?.focus());
  };

  useEffect(() => {
    if (!mobileOpen) return;

    closeButtonRef.current?.focus();
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Tab") {
        const controls = Array.from(
          document.querySelectorAll<HTMLElement>(
            "#admin-navigation a[href], #admin-navigation button:not([disabled]), #admin-navigation select:not([disabled])",
          ),
        ).filter((element) => element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
      if (event.key !== "Escape") return;
      setMobileOpen(false);
      requestAnimationFrame(() => menuButtonRef.current?.focus());
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [mobileOpen]);

  const changeAgent = (agentId: string) => {
    if (!agentId) {
      navigate("/agents");
      closeMobileNavigation();
      return;
    }
    const currentSection = location.pathname.match(/^\/agents\/[^/]+\/([^/]+)/)?.[1] || "overview";
    navigate(`/agents/${agentId}/${currentSection}`);
    closeMobileNavigation();
  };

  return (
    <div className="min-h-screen bg-[var(--bg-primary)] md:flex">
      <a
        href="#panel-content"
        className="fixed left-3 top-3 z-[60] -translate-y-20 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white focus:translate-y-0"
      >
        Saltar al contenido
      </a>
      <button
        ref={menuButtonRef}
        type="button"
        onClick={() => setMobileOpen(true)}
        className="fixed left-3 top-3 z-30 rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-2 text-[var(--text-primary)] md:hidden"
        aria-label="Abrir navegación"
        aria-expanded={mobileOpen}
        aria-controls="admin-navigation"
      >
        <Menu size={20} />
      </button>
      {mobileOpen && (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-black/55 md:hidden"
          onClick={() => closeMobileNavigation(true)}
          aria-label="Cerrar navegación"
        />
      )}

      <aside
        id="admin-navigation"
        className={`${collapsed ? "md:w-16" : "md:w-64"} ${mobileOpen ? "visible translate-x-0" : "invisible -translate-x-full"} fixed inset-y-0 left-0 z-40 flex w-[min(18rem,88vw)] flex-col border-r border-[var(--border-color)] bg-[var(--bg-secondary)] transition-[width,transform] duration-200 md:visible md:sticky md:top-0 md:h-screen md:translate-x-0`}
        aria-label="Administración"
      >
        <div className="flex h-14 items-center justify-between gap-2 border-b border-[var(--border-color)] px-4">
          <div className={`${collapsed ? "md:hidden" : ""} min-w-0`}>
            <h1 className="truncate text-base font-bold text-[var(--text-primary)]">
              Agent Platform
            </h1>
            <p className="truncate text-xs text-[var(--text-muted)]">CRM multicanal</p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="p-1.5 md:hidden"
            onClick={() => closeMobileNavigation(true)}
            aria-label="Cerrar navegación"
          >
            <X size={18} />
          </button>
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="hidden rounded p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] md:block"
            aria-label={collapsed ? "Expandir menú" : "Colapsar menú"}
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        {selectedAgent && isAgentConfiguration && (
          <div
            className={`${collapsed ? "md:hidden" : ""} border-b border-[var(--border-color)] p-3`}
          >
            <label
              className="block text-xs font-medium text-[var(--text-muted)]"
              htmlFor="agent-switcher"
            >
              Configurar agente
            </label>
            <select
              id="agent-switcher"
              className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm text-[var(--text-primary)]"
              value={selectedAgent?.id || ""}
              disabled={loadingAgents}
              onChange={(event) => changeAgent(event.target.value)}
            >
              <option value="">Seleccionar agente…</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <nav className="flex-1 overflow-y-auto py-2" aria-label="Navegación del panel">
          {platformGroups.length > 0 && (
            <div
              className={
                workspaceGroups.length ? "mt-3 border-t-2 border-[var(--border-color)] pt-2" : ""
              }
            >
              {platformGroups.map((group, index) => (
                <section
                  key={group.id}
                  aria-labelledby={`${group.id}-title`}
                  className={index > 0 ? "mt-2 border-t border-[var(--border-color)] pt-2" : ""}
                >
                  <h2
                    id={`${group.id}-title`}
                    className={`${collapsed ? "md:sr-only" : ""} px-4 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]`}
                  >
                    {group.label}
                  </h2>
                  {group.description && (
                    <p
                      className={`${collapsed ? "md:hidden" : ""} px-4 pb-2 text-xs leading-4 text-[var(--text-muted)]`}
                    >
                      {group.description}
                    </p>
                  )}
                  {group.items.map((item) => (
                    <NavigationLink
                      key={item.to}
                      item={item}
                      collapsed={collapsed}
                      onNavigate={() => closeMobileNavigation()}
                    />
                  ))}
                </section>
              ))}
            </div>
          )}{" "}
          {workspaceGroups.map((group, index) => (
            <section
              key={group.id}
              aria-labelledby={`${group.id}-title`}
              className={index > 0 ? "mt-2 border-t border-[var(--border-color)] pt-2" : ""}
            >
              <h2
                id={`${group.id}-title`}
                className={`${collapsed ? "md:sr-only" : ""} px-4 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]`}
              >
                {group.id === "workspace-overview" ? selectedAgent?.name : group.label}
              </h2>
              {group.description && (
                <p
                  className={`${collapsed ? "md:hidden" : ""} px-4 pb-2 text-xs leading-4 text-[var(--text-muted)]`}
                >
                  {group.description}
                </p>
              )}
              {group.items.map((item) => (
                <NavigationLink
                  key={item.to}
                  item={item}
                  collapsed={collapsed}
                  onNavigate={() => closeMobileNavigation()}
                />
              ))}
            </section>
          ))}
        </nav>

        <div className="border-t border-[var(--border-color)] p-3">
          <p
            className={`${collapsed ? "md:hidden" : ""} mb-2 truncate text-xs text-[var(--text-secondary)]`}
            title={user?.email}
          >
            {user?.email}
          </p>
          <button
            type="button"
            onClick={logout}
            className={`flex w-full items-center gap-2 rounded px-2 py-2 text-sm text-[var(--error)] hover:bg-[var(--bg-hover)] ${collapsed ? "md:justify-center" : ""}`}
            title="Cerrar sesión"
          >
            <LogOut size={16} className="shrink-0" />
            <span className={collapsed ? "md:hidden" : ""}>Cerrar sesión</span>
          </button>
        </div>
      </aside>

      <main
        id="panel-content"
        className="min-w-0 flex-1 overflow-x-hidden px-4 pb-6 pt-16 text-[var(--text-primary)] md:p-6"
        tabIndex={-1}
      >
        <Suspense fallback={<RouteLoading />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}

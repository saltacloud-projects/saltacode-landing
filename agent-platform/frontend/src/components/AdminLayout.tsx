import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Bot,
  Brain,
  Cable,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Files,
  FlaskConical,
  Gauge,
  Globe2,
  Library,
  LogOut,
  Menu,
  MessageSquare,
  ShieldCheck,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useAgentWorkspace } from "../agents/AgentWorkspaceContext";
import { useAuth } from "../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../auth/permissions";

interface NavigationItem {
  to: string;
  label: string;
  icon: LucideIcon;
  permission?: string;
}

const PLATFORM_ITEMS: NavigationItem[] = [
  { to: "/agents", label: "Agentes", icon: Bot, permission: PERMISSIONS.PROFILES_READ },
  { to: "/shared/sources", label: "Fuentes compartidas", icon: Cable, permission: PERMISSIONS.SOURCES_READ },
  { to: "/shared/knowledge", label: "Conocimiento compartido", icon: Library, permission: PERMISSIONS.KNOWLEDGE_READ },
  { to: "/shared/tools", label: "Herramientas compartidas", icon: Wrench, permission: PERMISSIONS.TOOLS_READ },
  { to: "/shared/documents", label: "Documentos compartidos", icon: Files, permission: PERMISSIONS.DOCUMENTS_READ },
  { to: "/panel-users", label: "Accesos del panel", icon: ShieldCheck, permission: PERMISSIONS.PANEL_USERS_MANAGE },
];

const WORKSPACE_ITEMS: Omit<NavigationItem, "to">[] = [
  { label: "Resumen", icon: Gauge, permission: PERMISSIONS.DASHBOARD_READ },
  { label: "Identidad", icon: Bot, permission: PERMISSIONS.PROFILES_READ },
  { label: "Conocimiento", icon: Brain, permission: PERMISSIONS.KNOWLEDGE_READ },
  { label: "Documentos", icon: Files, permission: PERMISSIONS.DOCUMENTS_READ },
  { label: "Fuentes", icon: Cable, permission: PERMISSIONS.SOURCES_READ },
  { label: "Herramientas", icon: Wrench, permission: PERMISSIONS.TOOLS_READ },
  { label: "Canales", icon: Globe2 },
  { label: "Conversaciones", icon: MessageSquare, permission: PERMISSIONS.CONVERSATIONS_READ },
  { label: "Ejecuciones y auditoría", icon: ClipboardList, permission: PERMISSIONS.AUDIT_READ },
  { label: "PromptLab", icon: FlaskConical, permission: PERMISSIONS.PROMPTLAB_USE },
];

const WORKSPACE_SEGMENTS: Record<string, string> = {
  Resumen: "overview",
  Identidad: "identity",
  Conocimiento: "knowledge",
  Documentos: "documents",
  Fuentes: "sources",
  Herramientas: "tools",
  Canales: "channels",
  Conversaciones: "conversations",
  "Ejecuciones y auditoría": "audit",
  PromptLab: "promptlab",
};

function NavigationLink({ item, collapsed, onNavigate }: { item: NavigationItem; collapsed: boolean; onNavigate: () => void }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      title={collapsed ? item.label : undefined}
      onClick={onNavigate}
      className={({ isActive }) => `flex min-h-10 items-center gap-3 border-l-2 px-4 py-2 text-sm transition-colors ${collapsed ? "md:justify-center" : ""} ${isActive ? "border-[var(--accent)] bg-[var(--bg-hover)] text-[var(--text-primary)]" : "border-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"}`}
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

  const platformItems = PLATFORM_ITEMS.filter((item) => !item.permission || hasPermission(user, item.permission));
  const workspaceItems = selectedAgent
    ? WORKSPACE_ITEMS
      .filter((item) => !item.permission || hasPermission(user, item.permission))
      .map((item) => ({ ...item, to: `/agents/${selectedAgent.id}/${WORKSPACE_SEGMENTS[item.label]}` }))
    : [];

  const changeAgent = (agentId: string) => {
    if (!agentId) return navigate("/agents");
    const currentSection = location.pathname.match(/^\/agents\/[^/]+\/([^/]+)/)?.[1] || "overview";
    navigate(`/agents/${agentId}/${currentSection}`);
    setMobileOpen(false);
  };

  return (
    <div className="min-h-screen bg-[var(--bg-primary)] md:flex">
      <a href="#panel-content" className="fixed left-3 top-3 z-[60] -translate-y-20 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white focus:translate-y-0">Saltar al contenido</a>
      <button onClick={() => setMobileOpen(true)} className="fixed left-3 top-3 z-30 rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-2 text-[var(--text-primary)] md:hidden" aria-label="Abrir navegación" aria-expanded={mobileOpen}><Menu size={20} /></button>
      {mobileOpen && <button className="fixed inset-0 z-30 bg-black/55 md:hidden" onClick={() => setMobileOpen(false)} aria-label="Cerrar navegación" />}

      <aside className={`${collapsed ? "md:w-16" : "md:w-64"} ${mobileOpen ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-40 flex w-[min(18rem,88vw)] flex-col border-r border-[var(--border-color)] bg-[var(--bg-secondary)] transition-[width,transform] duration-200 md:sticky md:top-0 md:h-screen md:translate-x-0`} aria-label="Administración">
        <div className="flex h-14 items-center justify-between gap-2 border-b border-[var(--border-color)] px-4">
          <div className={`${collapsed ? "md:hidden" : ""} min-w-0`}>
            <h1 className="truncate text-base font-bold text-[var(--text-primary)]">Agent Platform</h1>
            <p className="truncate text-xs text-[var(--text-muted)]">Administración por agente</p>
          </div>
          <button className="p-1.5 md:hidden" onClick={() => setMobileOpen(false)} aria-label="Cerrar navegación"><X size={18} /></button>
          <button onClick={() => setCollapsed((value) => !value)} className="hidden rounded p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] md:block" aria-label={collapsed ? "Expandir menú" : "Colapsar menú"}>{collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}</button>
        </div>

        <div className={`${collapsed ? "md:hidden" : ""} border-b border-[var(--border-color)] p-3`}>
          <label className="block text-xs font-medium text-[var(--text-muted)]" htmlFor="agent-switcher">Agente de trabajo</label>
          <select id="agent-switcher" className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm text-[var(--text-primary)]" value={selectedAgent?.id || ""} disabled={loadingAgents} onChange={(event) => changeAgent(event.target.value)}>
            <option value="">Seleccionar agente…</option>
            {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
          </select>
        </div>

        <nav className="flex-1 overflow-y-auto py-2" aria-label="Navegación del panel">
          {workspaceItems.length > 0 && (
            <section aria-labelledby="workspace-nav-title">
              <h2 id="workspace-nav-title" className={`${collapsed ? "md:sr-only" : ""} px-4 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]`}>{selectedAgent?.name}</h2>
              {workspaceItems.map((item) => <NavigationLink key={item.to} item={item} collapsed={collapsed} onNavigate={() => setMobileOpen(false)} />)}
            </section>
          )}
          {platformItems.length > 0 && (
            <section aria-labelledby="platform-nav-title" className={workspaceItems.length ? "mt-3 border-t border-[var(--border-color)] pt-2" : ""}>
              <h2 id="platform-nav-title" className={`${collapsed ? "md:sr-only" : ""} px-4 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]`}>Plataforma</h2>
              {platformItems.map((item) => <NavigationLink key={item.to} item={item} collapsed={collapsed} onNavigate={() => setMobileOpen(false)} />)}
            </section>
          )}
        </nav>

        <div className="border-t border-[var(--border-color)] p-3">
          <p className={`${collapsed ? "md:hidden" : ""} mb-2 truncate text-xs text-[var(--text-secondary)]`} title={user?.email}>{user?.email}</p>
          <button onClick={logout} className={`flex w-full items-center gap-2 rounded px-2 py-2 text-sm text-[var(--error)] hover:bg-[var(--bg-hover)] ${collapsed ? "md:justify-center" : ""}`} title="Cerrar sesión"><LogOut size={16} className="shrink-0" /><span className={collapsed ? "md:hidden" : ""}>Cerrar sesión</span></button>
        </div>
      </aside>

      <main id="panel-content" className="min-w-0 flex-1 overflow-x-hidden px-4 pb-6 pt-16 text-[var(--text-primary)] md:p-6" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}

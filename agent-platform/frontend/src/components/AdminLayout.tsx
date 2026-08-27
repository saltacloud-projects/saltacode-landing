import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Brain,
  Wrench,
  Users,
  MessageSquare,
  ClipboardList,
  FlaskConical,
  Files,
  ShieldCheck,
  Bot,
  Cable,
  Menu,
  X,
  ChevronLeft,
  ChevronRight,
  LogOut,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../auth/permissions";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  permission: string;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Panel", icon: LayoutDashboard, permission: PERMISSIONS.DASHBOARD_READ },
  { to: "/profiles", label: "Agentes", icon: Bot, permission: PERMISSIONS.PROFILES_READ },
  { to: "/knowledge", label: "Bloques de Conocimiento", icon: Brain, permission: PERMISSIONS.KNOWLEDGE_READ },
  { to: "/documents", label: "Documentos", icon: Files, permission: PERMISSIONS.DOCUMENTS_READ },
  { to: "/tools", label: "Herramientas", icon: Wrench, permission: PERMISSIONS.TOOLS_READ },
  { to: "/sources", label: "Fuentes", icon: Cable, permission: PERMISSIONS.SOURCES_READ },
  { to: "/users", label: "Acceso WhatsApp", icon: Users, permission: PERMISSIONS.USERS_READ },
  { to: "/conversations", label: "Conversaciones", icon: MessageSquare, permission: PERMISSIONS.CONVERSATIONS_READ },
  { to: "/audit", label: "Auditoría", icon: ClipboardList, permission: PERMISSIONS.AUDIT_READ },
  { to: "/promptlab", label: "PromptLab", icon: FlaskConical, permission: PERMISSIONS.PROMPTLAB_USE },
  { to: "/panel-users", label: "Accesos del panel", icon: ShieldCheck, permission: PERMISSIONS.PANEL_USERS_MANAGE },
];

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[var(--bg-primary)] md:flex">
      <button onClick={() => setMobileOpen(true)} className="fixed left-3 top-3 z-30 rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-2 text-[var(--text-primary)] md:hidden" aria-label="Abrir navegación"><Menu size={20} /></button>
      {mobileOpen && <button className="fixed inset-0 z-30 bg-black/55 md:hidden" onClick={() => setMobileOpen(false)} aria-label="Cerrar navegación" />}
      {/* Sidebar */}
      <aside
        className={`${collapsed ? "md:w-16" : "md:w-60"} ${mobileOpen ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-[var(--border-color)] bg-[var(--bg-secondary)] transition-all duration-200 md:static md:translate-x-0`}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-2 px-4 h-14 border-b border-[var(--border-color)]">
          {!collapsed && (
            <div className="min-w-0">
              <h1 className="text-[var(--text-primary)] font-bold text-base leading-tight truncate">
                Agent Platform
              </h1>
              <p className="text-xs text-[var(--text-muted)] truncate">
                Administración multicanal
              </p>
            </div>
          )}
          <button className="p-1.5 md:hidden" onClick={() => setMobileOpen(false)} aria-label="Cerrar navegación"><X size={18} /></button>
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="hidden p-1.5 rounded text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors md:block"
            title={collapsed ? "Expandir menú" : "Colapsar menú"}
            aria-label={collapsed ? "Expandir menú" : "Colapsar menú"}
          >
            {collapsed ? (
              <ChevronRight size={18} />
            ) : (
              <ChevronLeft size={18} />
            )}
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-2 overflow-y-auto">
          {NAV_ITEMS.filter((item) => hasPermission(user, item.permission)).map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                title={collapsed ? item.label : undefined}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${collapsed ? "justify-center" : ""
                  } ${isActive
                    ? "bg-[var(--bg-hover)] text-[var(--text-primary)] border-l-2 border-[var(--accent)]"
                    : "text-[var(--text-secondary)] border-l-2 border-transparent hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                  }`
                }
              >
                <Icon size={18} className="shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-[var(--border-color)] p-3">
          {!collapsed && (
            <p
              className="text-xs text-[var(--text-secondary)] truncate mb-2"
              title={user?.email}
            >
              {user?.email}
            </p>
          )}
          <button
            onClick={logout}
            title="Cerrar sesión"
            className={`flex items-center gap-2 w-full px-2 py-2 text-sm rounded text-[var(--error)] hover:bg-[var(--bg-hover)] transition-colors ${collapsed ? "justify-center" : ""
              }`}
          >
            <LogOut size={16} className="shrink-0" />
            {!collapsed && <span>Cerrar sesión</span>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="min-w-0 flex-1 overflow-auto px-4 pb-6 pt-16 text-[var(--text-primary)] md:p-6">
        <Outlet />
      </main>
    </div>
  );
}

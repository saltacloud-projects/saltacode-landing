import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AgentWorkspaceProvider, useAgentWorkspace } from "./agents/AgentWorkspaceContext";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { defaultPanelPath, hasPermission, PERMISSIONS } from "./auth/permissions";
import AdminLayout from "./components/AdminLayout";
import ProfilesPage, { AgentIdentityPage } from "./pages/AgentProfile";
import AgentChannelsPage from "./pages/AgentChannels";
import AuditPage from "./pages/Audit";
import ConversationsPage from "./pages/Conversations";
import DashboardPage from "./pages/Dashboard";
import DocumentsPage from "./pages/Documents";
import KnowledgePage from "./pages/KnowledgeBlocks";
import LoginPage from "./pages/Login";
import PanelUsersPage from "./pages/PanelUsers";
import PromptLabPage from "./pages/PromptLab";
import SourcesPage from "./pages/Sources";
import ToolsPage from "./pages/Tools";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="grid min-h-screen place-items-center text-sm text-gray-500" role="status">Cargando…</div>;
  }

  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to={defaultPanelPath(user)} replace />;
  return <>{children}</>;
}

function PermissionRoute({ permission, children }: { permission: string; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!hasPermission(user, permission)) return <Navigate to={defaultPanelPath(user)} replace />;
  return <>{children}</>;
}

function HomeRoute() {
  const { user } = useAuth();
  const { preferredAgent, loading } = useAgentWorkspace();
  if (loading && hasPermission(user, PERMISSIONS.PROFILES_READ)) {
    return <p className="text-sm text-[var(--text-muted)]" role="status">Cargando agentes…</p>;
  }
  if (preferredAgent && hasPermission(user, PERMISSIONS.DASHBOARD_READ)) {
    return <Navigate to={`/agents/${preferredAgent.id}/overview`} replace />;
  }
  return <Navigate to={defaultPanelPath(user)} replace />;
}

function AgentWorkspaceRoute() {
  const { selectedAgent, loading, error } = useAgentWorkspace();
  if (loading) return <p className="text-sm text-[var(--text-muted)]" role="status">Cargando agente…</p>;
  if (error) return <div className="rounded border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400" role="alert">{error}</div>;
  if (!selectedAgent) {
    return (
      <section className="mx-auto max-w-xl rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-6 text-center">
        <h2 className="text-lg font-semibold">Agente no encontrado</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">El agente de esta URL no existe o no está disponible para tu cuenta.</p>
        <a href="/agents" className="mt-4 inline-flex rounded bg-[var(--accent)] px-4 py-2 text-sm text-white">Volver a agentes</a>
      </section>
    );
  }
  return <Outlet />;
}

function LegacyAgentRedirect({ section, fallback }: { section: string; fallback: string }) {
  const { preferredAgent, loading } = useAgentWorkspace();
  if (loading) return <p className="text-sm text-[var(--text-muted)]" role="status">Cargando…</p>;
  return <Navigate to={preferredAgent ? `/agents/${preferredAgent.id}/${section}` : fallback} replace />;
}

function PanelShell() {
  return (
    <ProtectedRoute>
      <AgentWorkspaceProvider>
        <AdminLayout />
      </AgentWorkspaceProvider>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
          <Route element={<PanelShell />}>
            <Route index element={<HomeRoute />} />

            <Route path="agents" element={<PermissionRoute permission={PERMISSIONS.PROFILES_READ}><ProfilesPage /></PermissionRoute>} />
            <Route path="shared/sources" element={<PermissionRoute permission={PERMISSIONS.SOURCES_READ}><SourcesPage scope="library" /></PermissionRoute>} />
            <Route path="shared/knowledge" element={<PermissionRoute permission={PERMISSIONS.KNOWLEDGE_READ}><KnowledgePage scope="library" /></PermissionRoute>} />
            <Route path="shared/tools" element={<PermissionRoute permission={PERMISSIONS.TOOLS_READ}><ToolsPage scope="library" /></PermissionRoute>} />
            <Route path="shared/documents" element={<PermissionRoute permission={PERMISSIONS.DOCUMENTS_READ}><DocumentsPage scope="library" /></PermissionRoute>} />
            <Route path="panel-users" element={<PermissionRoute permission={PERMISSIONS.PANEL_USERS_MANAGE}><PanelUsersPage /></PermissionRoute>} />

            <Route path="agents/:agentId" element={<AgentWorkspaceRoute />}>
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={<PermissionRoute permission={PERMISSIONS.DASHBOARD_READ}><DashboardPage /></PermissionRoute>} />
              <Route path="identity" element={<PermissionRoute permission={PERMISSIONS.PROFILES_READ}><AgentIdentityPage /></PermissionRoute>} />
              <Route path="knowledge" element={<PermissionRoute permission={PERMISSIONS.KNOWLEDGE_READ}><KnowledgePage scope="agent" /></PermissionRoute>} />
              <Route path="documents" element={<PermissionRoute permission={PERMISSIONS.DOCUMENTS_READ}><DocumentsPage scope="agent" /></PermissionRoute>} />
              <Route path="sources" element={<PermissionRoute permission={PERMISSIONS.SOURCES_READ}><SourcesPage scope="agent" /></PermissionRoute>} />
              <Route path="tools" element={<PermissionRoute permission={PERMISSIONS.TOOLS_READ}><ToolsPage scope="agent" /></PermissionRoute>} />
              <Route path="channels" element={<AgentChannelsPage />} />
              <Route path="conversations" element={<PermissionRoute permission={PERMISSIONS.CONVERSATIONS_READ}><ConversationsPage /></PermissionRoute>} />
              <Route path="audit" element={<PermissionRoute permission={PERMISSIONS.AUDIT_READ}><AuditPage /></PermissionRoute>} />
              <Route path="promptlab" element={<PermissionRoute permission={PERMISSIONS.PROMPTLAB_USE}><PromptLabPage /></PermissionRoute>} />
            </Route>

            <Route path="profiles" element={<Navigate to="/agents" replace />} />
            <Route path="sources" element={<Navigate to="/shared/sources" replace />} />
            <Route path="knowledge" element={<LegacyAgentRedirect section="knowledge" fallback="/shared/knowledge" />} />
            <Route path="tools" element={<LegacyAgentRedirect section="tools" fallback="/shared/tools" />} />
            <Route path="documents" element={<LegacyAgentRedirect section="documents" fallback="/shared/documents" />} />
            <Route path="users" element={<LegacyAgentRedirect section="channels" fallback="/agents" />} />
            <Route path="conversations" element={<LegacyAgentRedirect section="conversations" fallback="/agents" />} />
            <Route path="audit" element={<LegacyAgentRedirect section="audit" fallback="/agents" />} />
            <Route path="promptlab" element={<LegacyAgentRedirect section="promptlab" fallback="/agents" />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

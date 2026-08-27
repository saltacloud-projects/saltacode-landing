import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import AdminLayout from "./components/AdminLayout";
import LoginPage from "./pages/Login";
import DashboardPage from "./pages/Dashboard";
import ProfilesPage from "./pages/AgentProfile";
import KnowledgePage from "./pages/KnowledgeBlocks";
import ToolsPage from "./pages/Tools";
import UsersPage from "./pages/Users";
import ConversationsPage from "./pages/Conversations";
import AuditPage from "./pages/Audit";
import PromptLabPage from "./pages/PromptLab";
import DocumentsPage from "./pages/Documents";
import PanelUsersPage from "./pages/PanelUsers";
import SourcesPage from "./pages/Sources";
import { defaultPanelPath, hasPermission, PERMISSIONS } from "./auth/permissions";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">Cargando...</p>
      </div>
    );
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
  const destination = defaultPanelPath(user);
  if (destination !== "/") return <Navigate to={destination} replace />;
  return <DashboardPage />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicRoute>
                <LoginPage />
              </PublicRoute>
            }
          />
          <Route
            element={
              <ProtectedRoute>
                <AdminLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<HomeRoute />} />
            <Route path="profiles" element={<PermissionRoute permission={PERMISSIONS.PROFILES_READ}><ProfilesPage /></PermissionRoute>} />
            <Route path="sources" element={<PermissionRoute permission={PERMISSIONS.SOURCES_READ}><SourcesPage /></PermissionRoute>} />
            <Route path="knowledge" element={<PermissionRoute permission={PERMISSIONS.KNOWLEDGE_READ}><KnowledgePage /></PermissionRoute>} />
            <Route path="tools" element={<PermissionRoute permission={PERMISSIONS.TOOLS_READ}><ToolsPage /></PermissionRoute>} />
            <Route path="documents" element={<PermissionRoute permission={PERMISSIONS.DOCUMENTS_READ}><DocumentsPage /></PermissionRoute>} />
            <Route path="users" element={<PermissionRoute permission={PERMISSIONS.USERS_READ}><UsersPage /></PermissionRoute>} />
            <Route path="conversations" element={<PermissionRoute permission={PERMISSIONS.CONVERSATIONS_READ}><ConversationsPage /></PermissionRoute>} />
            <Route path="audit" element={<PermissionRoute permission={PERMISSIONS.AUDIT_READ}><AuditPage /></PermissionRoute>} />
            <Route path="promptlab" element={<PermissionRoute permission={PERMISSIONS.PROMPTLAB_USE}><PromptLabPage /></PermissionRoute>} />
            <Route path="panel-users" element={<PermissionRoute permission={PERMISSIONS.PANEL_USERS_MANAGE}><PanelUsersPage /></PermissionRoute>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../auth/permissions";
import type { AgentProfile } from "./types";

const LAST_AGENT_KEY = "agent-platform:last-agent-id";

interface AgentWorkspaceState {
  profiles: AgentProfile[];
  selectedAgent: AgentProfile | null;
  preferredAgent: AgentProfile | null;
  loading: boolean;
  error: string;
  refreshProfiles: () => Promise<void>;
}

const AgentWorkspaceContext = createContext<AgentWorkspaceState | null>(null);

function agentIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/agents\/([^/]+)(?:\/|$)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function storedAgentId(): string | null {
  try {
    return localStorage.getItem(LAST_AGENT_KEY);
  } catch {
    return null;
  }
}

export function AgentWorkspaceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refreshProfiles = useCallback(async () => {
    if (!hasPermission(user, PERMISSIONS.PROFILES_READ)) {
      setProfiles([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setProfiles(await api<AgentProfile[]>("/profiles/"));
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudieron cargar los agentes.");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void refreshProfiles();
  }, [refreshProfiles]);

  const selectedId = agentIdFromPath(location.pathname);
  const selectedAgent = profiles.find((profile) => profile.id === selectedId) ?? null;
  const preferredAgent = useMemo(() => {
    const stored = storedAgentId();
    return profiles.find((profile) => profile.id === stored)
      ?? profiles.find((profile) => profile.is_active)
      ?? profiles[0]
      ?? null;
  }, [profiles]);

  useEffect(() => {
    if (!selectedAgent) return;
    try {
      localStorage.setItem(LAST_AGENT_KEY, selectedAgent.id);
    } catch {
      // URL remains the source of truth when storage is unavailable.
    }
  }, [selectedAgent]);

  const value = useMemo<AgentWorkspaceState>(() => ({
    profiles,
    selectedAgent,
    preferredAgent,
    loading,
    error,
    refreshProfiles,
  }), [profiles, selectedAgent, preferredAgent, loading, error, refreshProfiles]);

  return <AgentWorkspaceContext.Provider value={value}>{children}</AgentWorkspaceContext.Provider>;
}

export function useAgentWorkspace(): AgentWorkspaceState {
  const context = useContext(AgentWorkspaceContext);
  if (!context) throw new Error("useAgentWorkspace must be used within AgentWorkspaceProvider");
  return context;
}

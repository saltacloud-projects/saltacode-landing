import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";

interface ResourceRecord {
  id: string;
}

interface AgentResourceLibrary<T extends ResourceRecord> {
  library: T[];
  assigned: T[];
  available: T[];
  loading: boolean;
  error: string;
  busyId: string | null;
  refresh: () => Promise<void>;
  assign: (resourceId: string) => Promise<void>;
  unassign: (resourceId: string) => Promise<void>;
}

export function useAgentResourceLibrary<T extends ResourceRecord>(
  agentId: string | undefined,
  resource: "sources" | "tools" | "knowledge-blocks" | "document-areas",
  libraryPath: string,
): AgentResourceLibrary<T> {
  const [library, setLibrary] = useState<T[]>([]);
  const [assigned, setAssigned] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [libraryRows, assignedRows] = await Promise.all([
        api<T[]>(libraryPath),
        agentId ? api<T[]>(`/agents/${agentId}/${resource}`) : Promise.resolve([]),
      ]);
      setLibrary(libraryRows);
      setAssigned(assignedRows);
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudieron cargar los recursos.");
    } finally {
      setLoading(false);
    }
  }, [agentId, libraryPath, resource]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const mutateAssignment = async (resourceId: string, method: "PUT" | "DELETE") => {
    if (!agentId) return;
    setBusyId(resourceId);
    setError("");
    try {
      await api(`/agents/${agentId}/${resource}/${resourceId}`, { method });
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "No se pudo actualizar la asignación.");
    } finally {
      setBusyId(null);
    }
  };

  const assignedIds = useMemo(() => new Set(assigned.map((item) => item.id)), [assigned]);
  const available = useMemo(
    () => library.filter((item) => !assignedIds.has(item.id)),
    [assignedIds, library],
  );

  return {
    library,
    assigned,
    available,
    loading,
    error,
    busyId,
    refresh,
    assign: (resourceId) => mutateAssignment(resourceId, "PUT"),
    unassign: (resourceId) => mutateAssignment(resourceId, "DELETE"),
  };
}

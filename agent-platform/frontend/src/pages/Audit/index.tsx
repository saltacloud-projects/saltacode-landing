import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ClipboardList, Search, LoaderCircle, ListFilter } from "lucide-react";

interface ToolCall {
  tool: string;
  args?: Record<string, unknown>;
  status?: string;
}

interface AuditLog {
  id: string; request_id: string; phone_number: string; user_name: string | null;
  channel: string; input_type: string; intent: string | null; source_system: string | null;
  tool_used: string | null; duration_ms: number | null; status: string;
  error_code: string | null; error_message: string | null;
  response_preview: string | null; user_message: string | null;
  tool_calls: ToolCall[]; created_at: string;
}

// Formatea los argumentos de una tool para el tooltip ("con qué parámetros").
function formatArgs(args?: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return "sin parámetros";
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");
}

// Estilos de badge por status
function statusBadge(status: string): string {
  switch (status) {
    case "success":
      return "bg-[var(--success)]/15 text-[var(--success)]";
    case "error":
      return "bg-[var(--error)]/15 text-[var(--error)]";
    case "blocked":
      return "bg-[var(--warning)]/15 text-[var(--warning)]";
    case "timeout":
      return "bg-[var(--warning)]/15 text-[var(--warning)]";
    default:
      return "bg-[var(--bg-secondary)] text-[var(--text-secondary)]";
  }
}

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [phoneFilter, setPhoneFilter] = useState("");

  const load = () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (phoneFilter) params.set("phone", phoneFilter);
    params.set("limit", "100");
    api<AuditLog[]>(`/audit/?${params}`).then(setLogs).finally(() => setLoading(false));
  };

  // Recarga al cambiar el filtro de estado
  useEffect(() => { load(); }, [statusFilter]);

  return (
    <div>
      <div className="mb-6 flex items-start gap-2">
        <ClipboardList size={22} className="text-[var(--accent)]" />
        <div>
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Auditoría global</h2>
          <p className="text-sm text-[var(--text-muted)]">Eventos operativos de toda la plataforma. Esta vista no representa aislamiento por agente.</p>
        </div>
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap gap-3 mb-4 items-center">
        <div className="flex items-center gap-2">
          <ListFilter size={16} className="text-[var(--text-muted)]" />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] transition-colors"
          >
            <option value="">Todos los estados</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="blocked">blocked</option>
            <option value="timeout">timeout</option>
          </select>
        </div>
        <input
          placeholder="Filtrar por teléfono..."
          value={phoneFilter}
          onChange={(e) => setPhoneFilter(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-md px-3 py-2 text-sm w-56 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] transition-colors"
        />
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 text-sm rounded-md bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white transition-colors"
        >
          <Search size={16} /> Buscar
        </button>
      </div>

      {/* Tabla */}
      <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-lg overflow-hidden overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-[var(--bg-secondary)] text-left text-[var(--text-secondary)]">
            <tr>
              <th className="px-3 py-2.5 font-medium whitespace-nowrap">Fecha</th>
              <th className="px-3 py-2.5 font-medium">Usuario</th>
              <th className="px-3 py-2.5 font-medium">Consulta</th>
              <th className="px-3 py-2.5 font-medium">Status</th>
              <th className="px-3 py-2.5 font-medium">Cómo lo resolvió</th>
              <th className="px-3 py-2.5 font-medium">Duración</th>
              <th className="px-3 py-2.5 font-medium">Respuesta</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-color)]">
            {logs.map((l) => (
              <tr key={l.id} className="hover:bg-[var(--bg-hover)] transition-colors align-top">
                <td className="px-3 py-2.5 whitespace-nowrap text-[var(--text-secondary)]">
                  {new Date(l.created_at).toLocaleString("es-AR")}
                </td>
                <td className="px-3 py-2.5">
                  {l.user_name ? (
                    <div>
                      <span className="text-[var(--text-primary)]">{l.user_name}</span>
                      <span className="block font-mono text-[10px] text-[var(--text-muted)]">{l.phone_number}</span>
                    </div>
                  ) : (
                    <span className="font-mono text-[var(--text-primary)]">{l.phone_number}</span>
                  )}
                </td>
                <td className="px-3 py-2.5 max-w-[16rem]">
                  <span className="block truncate text-[var(--text-secondary)]" title={l.user_message || ""}>
                    {l.user_message || "—"}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadge(l.status)}`}>
                    {l.status}
                  </span>
                </td>
                <td className="px-3 py-2.5 max-w-[20rem]">
                  {l.tool_calls && l.tool_calls.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {l.tool_calls.map((tc, i) => (
                        <span
                          key={i}
                          title={formatArgs(tc.args)}
                          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px] cursor-help ${
                            tc.status && tc.status !== "success"
                              ? "bg-[var(--warning)]/15 text-[var(--warning)]"
                              : "bg-[var(--bg-secondary)] text-[var(--text-secondary)]"
                          }`}
                        >
                          {tc.tool}
                          {tc.args && Object.keys(tc.args).length > 0 && (
                            <span className="text-[var(--text-muted)]">({Object.keys(tc.args).length})</span>
                          )}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="font-mono text-[var(--text-muted)]">{l.tool_used || "—"}</span>
                  )}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-[var(--text-secondary)] whitespace-nowrap">
                  {l.duration_ms != null ? `${l.duration_ms}ms` : "—"}
                </td>
                <td className="px-3 py-2.5 max-w-xs">
                  <span
                    className={`block truncate ${l.error_message ? "text-[var(--error)]" : "text-[var(--text-secondary)]"}`}
                    title={l.error_message || l.response_preview || ""}
                  >
                    {l.error_message || l.response_preview || "—"}
                  </span>
                </td>
              </tr>
            ))}
            {!loading && logs.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-[var(--text-muted)] text-sm">
                  Sin logs
                </td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-[var(--text-secondary)] text-sm">
                  <span className="inline-flex items-center gap-2">
                    <LoaderCircle size={16} className="animate-spin" /> Cargando logs...
                  </span>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

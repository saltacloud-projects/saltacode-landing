import {
  ArchiveRestore,
  Download,
  FileText,
  FolderPlus,
  History,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAgentResourceLibrary } from "../../agents/useAgentResourceLibrary";
import { api, download } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface Area {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  is_general: boolean;
  is_active: boolean;
  folder_count: number;
  document_count: number;
}
interface Folder {
  id: string;
  area_id: string;
  parent_id: string | null;
  name: string;
  document_count: number;
}
interface Version {
  id: string;
  version_number: number;
  status: string;
  original_filename: string;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  extraction_method: string | null;
  error_message: string | null;
}
interface Job {
  id: string;
  status: string;
  stage: string;
  progress_percent: number;
  attempts: number;
  error_message: string | null;
}
interface DocumentItem {
  id: string;
  reference_code: string;
  folder_id: string;
  folder_name: string;
  area_id: string;
  area_name: string;
  title: string;
  description: string | null;
  internal_code: string | null;
  responsible: string | null;
  effective_from: string | null;
  effective_to: string | null;
  status: string;
  deleted_at: string | null;
  purge_after: string | null;
  current_version: Version | null;
  current_job: Job | null;
  updated_at: string;
}
interface DocumentList {
  items: DocumentItem[];
  total: number;
  limit: number;
  offset: number;
}
interface Stats {
  documents_total: number;
  published: number;
  processing: number;
  failed: number;
  deleted: number;
  chunks: number;
  storage_bytes: number;
  queue_depth: number;
  worker_last_activity: string | null;
}
interface RagSettings {
  enabled: boolean;
  embedding_model: string;
  embedding_dimensions: number;
  vision_model: string;
  max_file_bytes: number;
  max_batch_bytes: number;
  retention_days: number;
  chunk_tokens: number;
  chunk_overlap_tokens: number;
  retrieval_top_k: number;
  min_relevance_score: number;
  vector_weight: number;
  lexical_weight: number;
  ocr_enabled: boolean;
}
interface SearchHit {
  reference_code: string;
  title: string;
  version_number: number;
  content: string;
  page_number: number | null;
  location_label: string | null;
  section_title: string | null;
  score: number;
}
interface DocumentFilters {
  query: string;
  areaId: string;
  folderId: string;
  statusFilter: string;
  includeDeleted: boolean;
  offset: number;
}
interface UploadAccepted {
  document_id: string;
  reference_code: string;
  version_id: string;
  job_id: string;
  filename: string;
  duplicate_hash: boolean;
}
interface UploadResult {
  accepted: UploadAccepted[];
  rejected: { filename: string; reason: string }[];
}

const INPUT =
  "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none";
const BUTTON =
  "inline-flex items-center justify-center gap-2 rounded px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
const ACCEPT_DOCUMENTS = ".pdf,.docx,.xlsx,.xlsm,.xls,.pptx,.txt,.md,.jpg,.jpeg,.png,.tif,.tiff";
const ACCEPT_UPLOADS = `${ACCEPT_DOCUMENTS},.zip`;

function formatBytes(value: number) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function statusStyle(value: string) {
  if (value === "published" || value === "completed" || value === "ready")
    return "bg-emerald-500/15 text-emerald-400";
  if (value === "failed") return "bg-red-500/15 text-red-400";
  if (value === "deleted") return "bg-slate-500/15 text-slate-400";
  return "bg-amber-500/15 text-amber-400";
}

export default function DocumentsPage({ scope = "agent" }: { scope?: "agent" | "library" }) {
  const { user } = useAuth();
  const { selectedAgent } = useAgentWorkspace();
  const agentId = scope === "agent" ? selectedAgent?.id : undefined;
  const areaResources = useAgentResourceLibrary<Area>(
    agentId,
    "document-areas",
    "/documents/areas",
  );
  const canManage = hasPermission(user, PERMISSIONS.DOCUMENTS_MANAGE);
  const canManageTaxonomy = hasPermission(user, PERMISSIONS.DOCUMENTS_TAXONOMY);
  const canManageSettings = hasPermission(user, PERMISSIONS.DOCUMENTS_SETTINGS);
  const [areas, setAreas] = useState<Area[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [documents, setDocuments] = useState<DocumentList>({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  const [stats, setStats] = useState<Stats | null>(null);
  const [settings, setSettings] = useState<RagSettings | null>(null);
  const [areaId, setAreaId] = useState("");
  const [folderId, setFolderId] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [offset, setOffset] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [searchText, setSearchText] = useState("");
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [editingDocument, setEditingDocument] = useState<DocumentItem | null>(null);
  const [versionDocument, setVersionDocument] = useState<DocumentItem | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [settingsDraft, setSettingsDraft] = useState<RagSettings | null>(null);
  const [rejections, setRejections] = useState<{ filename: string; reason: string }[]>([]);
  const [replaceTarget, setReplaceTarget] = useState<DocumentItem | null>(null);
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const replaceInputRef = useRef<HTMLInputElement>(null);
  const initialLoadComplete = useRef(false);
  const documentFiltersRef = useRef<DocumentFilters>({
    query,
    areaId,
    folderId,
    statusFilter,
    includeDeleted,
    offset,
  });
  documentFiltersRef.current = {
    query,
    areaId,
    folderId,
    statusFilter,
    includeDeleted,
    offset,
  };

  const loadStatic = useCallback(async () => {
    const [areaRows, folderRows, settingRow] = await Promise.all([
      api<Area[]>("/documents/areas"),
      api<Folder[]>("/documents/folders"),
      api<RagSettings>("/documents/settings"),
    ]);
    setAreas(areaRows);
    setFolders(folderRows);
    setSettings(settingRow);
    if (!agentId && areaRows.length) {
      setAreaId(
        (current) => current || areaRows.find((area) => area.is_general)?.id || areaRows[0].id,
      );
    }
  }, [agentId]);

  const loadDocuments = useCallback(
    async (
      requestedOffset = documentFiltersRef.current.offset,
      filters = documentFiltersRef.current,
    ) => {
      const {
        query: requestedQuery,
        areaId: requestedAreaId,
        folderId: requestedFolderId,
        statusFilter: requestedStatus,
        includeDeleted: requestedDeleted,
      } = filters;
      const params = new URLSearchParams({ limit: "50", offset: String(requestedOffset) });
      if (requestedQuery.trim()) params.set("q", requestedQuery.trim());
      if (requestedAreaId) params.set("area_id", requestedAreaId);
      if (requestedFolderId) params.set("folder_id", requestedFolderId);
      if (requestedStatus) params.set("status", requestedStatus);
      if (requestedDeleted) params.set("include_deleted", "true");
      if (agentId && !requestedAreaId) {
        setDocuments({ items: [], total: 0, limit: 50, offset: 0 });
        setStats(null);
        return;
      }
      const [list, summary] = await Promise.all([
        api<DocumentList>(`/documents/?${params}`),
        agentId ? Promise.resolve(null) : api<Stats>("/documents/stats"),
      ]);
      setDocuments(list);
      setStats(summary);
      setOffset(requestedOffset);
    },
    [agentId],
  );

  useEffect(() => {
    let active = true;
    initialLoadComplete.current = false;
    setLoading(true);
    Promise.all([loadStatic(), loadDocuments()])
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (!active) return;
        initialLoadComplete.current = true;
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loadDocuments, loadStatic]);

  useEffect(() => {
    if (!initialLoadComplete.current) return;
    const current = documentFiltersRef.current;
    loadDocuments(0, { ...current, areaId, folderId, statusFilter, includeDeleted }).catch((e) =>
      setError(e.message),
    );
  }, [areaId, folderId, includeDeleted, loadDocuments, statusFilter]);

  const visibleAreas = agentId ? areaResources.assigned : areas;
  useEffect(() => {
    if (!agentId || areaResources.loading) return;
    setAreaId((current) =>
      visibleAreas.some((area) => area.id === current)
        ? current
        : visibleAreas.find((area) => area.is_general)?.id || visibleAreas[0]?.id || "",
    );
    setFolderId((current) =>
      current &&
      folders.some(
        (folder) =>
          folder.id === current && visibleAreas.some((area) => area.id === folder.area_id),
      )
        ? current
        : "",
    );
  }, [agentId, areaResources.loading, folders, visibleAreas]);

  useEffect(() => {
    const timer = window.setInterval(
      () => loadDocuments().catch(() => undefined),
      stats?.queue_depth ? 3000 : 30000,
    );
    return () => window.clearInterval(timer);
  }, [stats?.queue_depth, loadDocuments]);

  const visibleFolders = useMemo(
    () =>
      folders.filter(
        (folder) =>
          (!areaId || folder.area_id === areaId) &&
          (!agentId || visibleAreas.some((area) => area.id === folder.area_id)),
      ),
    [folders, areaId, agentId, visibleAreas],
  );
  const folderPath = useCallback(
    (folder: Folder): string => {
      const parent = folders.find((item) => item.id === folder.parent_id);
      return parent ? `${folderPath(parent)} / ${folder.name}` : folder.name;
    },
    [folders],
  );

  const refresh = async () => {
    setError("");
    try {
      await Promise.all([loadStatic(), loadDocuments()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar");
    }
  };

  const upload = async () => {
    if (!areaId) {
      setError("Seleccioná el área donde deben quedar los documentos.");
      return;
    }
    if (!files.length) {
      setError("Elegí al menos un archivo o una carpeta antes de subir.");
      return;
    }
    if (
      settings &&
      files.reduce((total, file) => total + file.size, 0) > settings.max_batch_bytes
    ) {
      setError(`La selección supera el límite de ${formatBytes(settings.max_batch_bytes)}.`);
      return;
    }
    setUploading(true);
    setError("");
    setNotice("");
    setRejections([]);
    try {
      const maxRequestBytes = 80 * 1024 * 1024;
      const groups: File[][] = [];
      let group: File[] = [];
      let groupBytes = 0;
      for (const file of files) {
        if (group.length && groupBytes + file.size > maxRequestBytes) {
          groups.push(group);
          group = [];
          groupBytes = 0;
        }
        group.push(file);
        groupBytes += file.size;
      }
      if (group.length) groups.push(group);
      let accepted = 0;
      let duplicates = 0;
      const rejected: { filename: string; reason: string }[] = [];
      for (const requestFiles of groups) {
        const body = new FormData();
        body.append("area_id", areaId);
        if (folderId) body.append("folder_id", folderId);
        requestFiles.forEach((file) => {
          body.append("files", file);
          const relative =
            (file as File & { webkitRelativePath?: string }).webkitRelativePath || "";
          body.append(
            "relative_paths",
            relative.includes("/") ? relative.slice(0, relative.lastIndexOf("/")) : "",
          );
        });
        const result = await api<UploadResult>("/documents/upload", { method: "POST", body });
        accepted += result.accepted.length;
        duplicates += result.accepted.filter((item) => item.duplicate_hash).length;
        rejected.push(...result.rejected);
      }
      setNotice(
        `${accepted} archivo(s) encolado(s)${rejected.length ? `; ${rejected.length} rechazado(s)` : ""}${duplicates ? `; ${duplicates} duplicado(s)` : ""}.`,
      );
      setRejections(rejected);
      setFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el lote");
    } finally {
      setUploading(false);
    }
  };

  const selectFiles = (selected: File[]) => {
    setError("");
    setNotice("");
    setRejections([]);
    setFiles(selected);
  };

  const createArea = async () => {
    const name = window.prompt("Nombre del área");
    if (!name) return;
    const slug = name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    try {
      await api("/documents/areas", { method: "POST", body: JSON.stringify({ name, slug }) });
      await loadStatic();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear el área");
    }
  };

  const updateArea = async () => {
    const area = areas.find((item) => item.id === areaId);
    if (!area) return;
    const name = window.prompt("Nuevo nombre del área", area.name);
    if (!name || name === area.name) return;
    try {
      await api(`/documents/areas/${area.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
      await loadStatic();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo editar el área");
    }
  };

  const deleteArea = async () => {
    const area = areas.find((item) => item.id === areaId);
    if (!area || !window.confirm(`¿Eliminar el área ${area.name}? Debe estar vacía.`)) return;
    try {
      await api(`/documents/areas/${area.id}`, { method: "DELETE" });
      setAreaId("");
      setFolderId("");
      await loadStatic();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo eliminar el área");
    }
  };

  const createFolder = async () => {
    if (!areaId) return;
    const name = window.prompt("Nombre de la carpeta");
    if (!name) return;
    try {
      await api("/documents/folders", {
        method: "POST",
        body: JSON.stringify({ area_id: areaId, parent_id: folderId || null, name }),
      });
      await loadStatic();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear la carpeta");
    }
  };

  const updateFolder = async () => {
    const folder = folders.find((item) => item.id === folderId);
    if (!folder) return;
    const name = window.prompt("Nuevo nombre de la carpeta", folder.name);
    if (!name || name === folder.name) return;
    try {
      await api(`/documents/folders/${folder.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      await loadStatic();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo editar la carpeta");
    }
  };

  const deleteFolder = async () => {
    const folder = folders.find((item) => item.id === folderId);
    if (!folder || !window.confirm(`¿Eliminar la carpeta ${folder.name}? Debe estar vacía.`))
      return;
    try {
      await api(`/documents/folders/${folder.id}`, { method: "DELETE" });
      setFolderId("");
      await loadStatic();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo eliminar la carpeta");
    }
  };

  const saveDocument = async () => {
    if (!editingDocument) return;
    try {
      await api(`/documents/${editingDocument.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: editingDocument.title,
          description: editingDocument.description,
          internal_code: editingDocument.internal_code,
          responsible: editingDocument.responsible,
          folder_id: editingDocument.folder_id,
          effective_from: editingDocument.effective_from || null,
          effective_to: editingDocument.effective_to || null,
        }),
      });
      setEditingDocument(null);
      await loadDocuments();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo editar el documento");
    }
  };

  const showVersions = async (document: DocumentItem) => {
    setVersionDocument(document);
    try {
      setVersions(await api<Version[]>(`/documents/${document.id}/versions`));
    } catch (e) {
      setVersionDocument(null);
      setError(e instanceof Error ? e.message : "No se pudo cargar el historial");
    }
  };

  const replace = (document: DocumentItem) => {
    setReplaceTarget(document);
    setError("");
    setNotice("");
    window.requestAnimationFrame(() => replaceInputRef.current?.click());
  };

  const replaceSelected = async () => {
    const file = replaceInputRef.current?.files?.[0];
    const document = replaceTarget;
    if (replaceInputRef.current) replaceInputRef.current.value = "";
    if (!file || !document) return;
    if (settings && file.size > settings.max_file_bytes) {
      setError(`El archivo supera el límite de ${formatBytes(settings.max_file_bytes)}.`);
      return;
    }
    setReplacingId(document.id);
    setError("");
    setNotice("");
    const body = new FormData();
    body.append("file", file);
    try {
      const result = await api<UploadResult>(`/documents/${document.id}/replace`, {
        method: "POST",
        body,
      });
      const queued = result.accepted[0];
      setNotice(
        queued?.duplicate_hash
          ? `Reemplazo encolado como nueva versión. El archivo es idéntico a otro original ya almacenado.`
          : `Reemplazo encolado. La versión actual seguirá activa hasta que termine la nueva.`,
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo reemplazar");
    } finally {
      setReplacingId(null);
      setReplaceTarget(null);
    }
  };

  const mutate = async (path: string, method = "POST", confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setError("");
    try {
      await api(path, { method });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "La operación falló");
    }
  };

  const testSearch = async () => {
    if (!searchText.trim()) return;
    setSearching(true);
    setError("");
    try {
      setHits(
        await api<SearchHit[]>("/documents/search", {
          method: "POST",
          body: JSON.stringify({ query: searchText, area_ids: areaId ? [areaId] : [] }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo probar la búsqueda");
    } finally {
      setSearching(false);
    }
  };

  const toggleEnabled = async () => {
    if (!settings) return;
    if (
      settings.enabled &&
      !window.confirm(
        "¿Desactivar RAG? El agente dejará de consultar documentos hasta que vuelva a activarse.",
      )
    )
      return;
    try {
      setSettings(
        await api<RagSettings>("/documents/settings", {
          method: "PATCH",
          body: JSON.stringify({ enabled: !settings.enabled }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cambiar la configuración");
    }
  };

  const saveSettings = async () => {
    if (!settingsDraft) return;
    try {
      const payload = {
        max_file_bytes: settingsDraft.max_file_bytes,
        max_batch_bytes: settingsDraft.max_batch_bytes,
        retention_days: settingsDraft.retention_days,
        chunk_tokens: settingsDraft.chunk_tokens,
        chunk_overlap_tokens: settingsDraft.chunk_overlap_tokens,
        retrieval_top_k: settingsDraft.retrieval_top_k,
        min_relevance_score: settingsDraft.min_relevance_score,
        vector_weight: settingsDraft.vector_weight,
        lexical_weight: settingsDraft.lexical_weight,
        ocr_enabled: settingsDraft.ocr_enabled,
      };
      const saved = await api<RagSettings>("/documents/settings", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setSettings(saved);
      setSettingsDraft(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar la configuración");
    }
  };

  if (loading)
    return (
      <div className="flex h-48 items-center justify-center">
        <LoaderCircle className="animate-spin text-[var(--accent)]" />
      </div>
    );

  return (
    <div className="space-y-5">
      <input
        ref={replaceInputRef}
        className="hidden"
        type="file"
        accept={ACCEPT_DOCUMENTS}
        onChange={replaceSelected}
        data-testid="replace-file-input"
      />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">
            {agentId ? `Documentos de ${selectedAgent?.name}` : "Biblioteca documental RAG"}
          </h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            {agentId
              ? "Documentos disponibles dentro de las áreas asignadas al agente."
              : "Originales persistentes, versionado e indexación compartida."}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className={`${BUTTON} border border-[var(--border-color)]`}
            onClick={refresh}
          >
            <RefreshCw size={16} />
            Actualizar
          </button>
          {!agentId && canManageSettings && settings && (
            <button
              type="button"
              className={`${BUTTON} ${settings.enabled ? "bg-emerald-600 text-white" : "bg-[var(--bg-secondary)] text-[var(--text-secondary)] border border-[var(--border-color)]"}`}
              onClick={toggleEnabled}
            >
              <Settings2 size={16} />
              RAG {settings.enabled ? "activo" : "inactivo"}
            </button>
          )}
        </div>
      </div>

      {(error || areaResources.error) && (
        <div
          className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400"
          role="alert"
        >
          <XCircle size={16} />
          {error || areaResources.error}
        </div>
      )}
      {notice && (
        <div className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400">
          {notice}
        </div>
      )}

      {agentId && (
        <section className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h3 className="font-semibold">Áreas asignadas</h3>
              <p className="text-xs text-[var(--text-muted)]">
                Los documentos siguen siendo recursos compartidos; la asignación controla qué áreas
                consulta este agente.
              </p>
            </div>
            <span className="text-xs text-[var(--text-muted)]">
              {areaResources.assigned.length} de {areaResources.library.length}
            </span>
          </div>
          {areaResources.loading ? (
            <p className="mt-3 text-sm text-[var(--text-muted)]" role="status">
              Cargando áreas…
            </p>
          ) : (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                  Asignadas
                </h4>
                <div className="flex flex-wrap gap-2">
                  {areaResources.assigned.map((area) => (
                    <span
                      key={area.id}
                      className="inline-flex items-center gap-2 rounded-full border border-[var(--border-color)] px-3 py-1.5 text-sm"
                    >
                      {area.name}
                      {canManageTaxonomy && (
                        <button
                          type="button"
                          aria-label={`Desasignar ${area.name}`}
                          onClick={() => areaResources.unassign(area.id)}
                          disabled={areaResources.busyId === area.id}
                          className="text-amber-300"
                        >
                          <X size={13} />
                        </button>
                      )}
                    </span>
                  ))}
                  {areaResources.assigned.length === 0 && (
                    <span className="text-sm text-[var(--text-muted)]">Sin áreas asignadas.</span>
                  )}
                </div>
              </div>
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                  Disponibles
                </h4>
                <div className="flex flex-wrap gap-2">
                  {areaResources.available.map((area) => (
                    <button
                      type="button"
                      key={area.id}
                      onClick={() => areaResources.assign(area.id)}
                      disabled={!canManageTaxonomy || areaResources.busyId === area.id}
                      className="rounded-full border border-[var(--accent)]/40 px-3 py-1.5 text-sm text-[var(--accent)] disabled:opacity-50"
                    >
                      <Plus size={13} className="mr-1 inline" />
                      {area.name}
                    </button>
                  ))}
                  {areaResources.available.length === 0 && (
                    <span className="text-sm text-[var(--text-muted)]">
                      No quedan áreas disponibles.
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {stats && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          {[
            ["Documentos", stats.documents_total],
            ["Publicados", stats.published],
            ["Procesando", stats.processing],
            ["Fallidos", stats.failed],
            ["Eliminados", stats.deleted],
            ["Chunks", stats.chunks],
            ["Almacenado", formatBytes(stats.storage_bytes)],
          ].map(([label, value]) => (
            <div
              key={label}
              className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
            >
              <p className="text-xs text-[var(--text-muted)]">{label}</p>
              <p className="mt-1 text-lg font-semibold">{value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-48 flex-1 text-xs text-[var(--text-secondary)]">
              Área
              <select
                className={`${INPUT} mt-1`}
                value={areaId}
                onChange={(e) => {
                  setAreaId(e.target.value);
                  setFolderId("");
                }}
              >
                <option value="">{agentId ? "Seleccionar área" : "Todas"}</option>
                {visibleAreas
                  .filter((a) => a.is_active)
                  .map((area) => (
                    <option key={area.id} value={area.id}>
                      {area.name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="min-w-56 flex-1 text-xs text-[var(--text-secondary)]">
              Carpeta
              <select
                className={`${INPUT} mt-1`}
                value={folderId}
                onChange={(e) => setFolderId(e.target.value)}
              >
                <option value="">Todas / raíz del área</option>
                {visibleFolders.map((folder) => (
                  <option key={folder.id} value={folder.id}>
                    {folderPath(folder)}
                  </option>
                ))}
              </select>
            </label>
            {!agentId && canManageTaxonomy && (
              <>
                <button
                  type="button"
                  className={`${BUTTON} border border-[var(--border-color)]`}
                  onClick={createArea}
                >
                  <Plus size={15} />
                  Área
                </button>
                <button
                  type="button"
                  title="Editar área"
                  className={`${BUTTON} border border-[var(--border-color)] px-2`}
                  onClick={updateArea}
                  disabled={!areaId}
                >
                  <Pencil size={15} />
                </button>
                <button
                  type="button"
                  title="Eliminar área"
                  className={`${BUTTON} border border-[var(--border-color)] px-2 text-red-400`}
                  onClick={deleteArea}
                  disabled={!areaId || areas.find((area) => area.id === areaId)?.is_general}
                >
                  <Trash2 size={15} />
                </button>
                <button
                  type="button"
                  className={`${BUTTON} border border-[var(--border-color)]`}
                  onClick={createFolder}
                  disabled={!areaId}
                >
                  <FolderPlus size={15} />
                  Carpeta
                </button>
                <button
                  type="button"
                  title="Editar carpeta"
                  className={`${BUTTON} border border-[var(--border-color)] px-2`}
                  onClick={updateFolder}
                  disabled={!folderId}
                >
                  <Pencil size={15} />
                </button>
                <button
                  type="button"
                  title="Eliminar carpeta"
                  className={`${BUTTON} border border-[var(--border-color)] px-2 text-red-400`}
                  onClick={deleteFolder}
                  disabled={!folderId}
                >
                  <Trash2 size={15} />
                </button>
              </>
            )}
          </div>

          {canManage && (
            <div className="rounded-lg border border-dashed border-[var(--border-color)] p-4">
              <div className="flex flex-wrap items-center gap-3">
                <label className={`${BUTTON} cursor-pointer bg-[var(--accent)] text-white`}>
                  <Upload size={16} />
                  Elegir archivos
                  <input
                    ref={fileInputRef}
                    data-testid="upload-file-input"
                    className="hidden"
                    type="file"
                    multiple
                    accept={ACCEPT_UPLOADS}
                    onClick={(e) => {
                      e.currentTarget.value = "";
                    }}
                    onChange={(e) => selectFiles(Array.from(e.target.files || []))}
                  />
                </label>
                <label className={`${BUTTON} cursor-pointer border border-[var(--border-color)]`}>
                  <FolderPlus size={16} />
                  Elegir carpeta
                  <input
                    ref={folderInputRef}
                    data-testid="upload-folder-input"
                    className="hidden"
                    type="file"
                    multiple
                    {...({
                      webkitdirectory: "",
                      directory: "",
                    } as React.InputHTMLAttributes<HTMLInputElement>)}
                    onClick={(e) => {
                      e.currentTarget.value = "";
                    }}
                    onChange={(e) => selectFiles(Array.from(e.target.files || []))}
                  />
                </label>
                <button
                  type="button"
                  data-testid="upload-submit"
                  className={`${BUTTON} bg-[var(--accent)] text-white`}
                  disabled={uploading}
                  onClick={upload}
                >
                  {uploading ? (
                    <LoaderCircle size={16} className="animate-spin" />
                  ) : (
                    <Upload size={16} />
                  )}
                  {uploading ? "Subiendo..." : `Subir${files.length ? ` ${files.length}` : ""}`}
                </button>
                {!!files.length && (
                  <button
                    type="button"
                    className={`${BUTTON} border border-[var(--border-color)]`}
                    onClick={() => selectFiles([])}
                  >
                    <X size={15} />
                    Quitar selección
                  </button>
                )}
              </div>
              <p className="mt-3 text-xs text-[var(--text-muted)]">
                PDF, Word, Excel, PowerPoint, texto, imágenes y ZIP. Máximo{" "}
                {formatBytes(settings?.max_file_bytes || 104857600)} por archivo y{" "}
                {formatBytes(settings?.max_batch_bytes || 2147483648)} por lote. Las carpetas
                locales conservan su estructura.
              </p>
              {!areaId && (
                <p className="mt-2 text-xs text-amber-400">Antes de subir, seleccioná un área.</p>
              )}
              {!!files.length && (
                <div className="mt-2 rounded border border-[var(--border-color)] bg-[var(--bg-primary)] p-2 text-xs text-[var(--text-secondary)]">
                  <p className="font-medium text-[var(--text-primary)]">
                    {files.length} archivo(s) seleccionado(s) ·{" "}
                    {formatBytes(files.reduce((total, file) => total + file.size, 0))}
                  </p>
                  <p className="mt-1 truncate">
                    {files
                      .slice(0, 4)
                      .map((file) => file.name)
                      .join(", ")}
                    {files.length > 4 ? ` y ${files.length - 4} más` : ""}
                  </p>
                </div>
              )}
              {!!rejections.length && (
                <div className="mt-3 rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300">
                  <p className="font-medium">Archivos rechazados</p>
                  {rejections.slice(0, 20).map((item) => (
                    <p key={`${item.filename}:${item.reason}`} className="mt-1">
                      {item.filename}: {item.reason}
                    </p>
                  ))}
                  {rejections.length > 20 && (
                    <p className="mt-1">Y {rejections.length - 20} más.</p>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-60 flex-1">
              <Search className="absolute left-3 top-2.5 text-[var(--text-muted)]" size={16} />
              <input
                className={`${INPUT} pl-9`}
                placeholder="Buscar título, referencia o código"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && loadDocuments()}
              />
            </div>
            <select
              className={`${INPUT} w-auto`}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">Todos los estados</option>
              <option value="published">Publicados</option>
              <option value="processing">Procesando</option>
              <option value="failed">Fallidos</option>
              <option value="deleted">Eliminados</option>
            </select>
            <button
              type="button"
              className={`${BUTTON} border border-[var(--border-color)]`}
              onClick={() => loadDocuments(0)}
            >
              <Search size={15} />
              Buscar
            </button>
            <label className="flex items-center gap-2 px-2 text-xs text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={includeDeleted}
                onChange={(e) => setIncludeDeleted(e.target.checked)}
              />
              Ver eliminados
            </label>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[var(--border-color)] text-xs text-[var(--text-muted)]">
                <tr>
                  <th className="px-2 py-3">Documento</th>
                  <th className="px-2 py-3">Ubicación</th>
                  <th className="px-2 py-3">Estado</th>
                  <th className="px-2 py-3">Versión</th>
                  <th className="px-2 py-3 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {documents.items.map((document) => (
                  <tr
                    key={document.id}
                    className="border-b border-[var(--border-color)]/60 align-top"
                  >
                    <td className="px-2 py-3">
                      <div className="flex gap-2">
                        <FileText size={17} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                        <div>
                          <p className="font-medium">{document.title}</p>
                          <p className="text-xs text-[var(--text-muted)]">
                            {document.reference_code}
                            {document.current_version
                              ? ` · ${formatBytes(document.current_version.size_bytes)}`
                              : ""}
                          </p>
                          {document.current_job &&
                            ["queued", "processing"].includes(document.current_job.status) && (
                              <div className="mt-2 h-1.5 w-40 rounded bg-[var(--border-color)]">
                                <div
                                  className="h-full rounded bg-[var(--accent)]"
                                  style={{ width: `${document.current_job.progress_percent}%` }}
                                />
                              </div>
                            )}
                        </div>
                      </div>
                    </td>
                    <td className="px-2 py-3 text-xs text-[var(--text-secondary)]">
                      {document.area_name}
                      <br />
                      {document.folder_name}
                    </td>
                    <td className="px-2 py-3">
                      <span className={`rounded px-2 py-1 text-xs ${statusStyle(document.status)}`}>
                        {document.status}
                      </span>
                      {document.current_job?.error_message && (
                        <p
                          className="mt-1 max-w-56 text-xs text-red-400"
                          title={document.current_job.error_message}
                        >
                          {document.current_job.error_message.slice(0, 90)}
                        </p>
                      )}
                    </td>
                    <td className="px-2 py-3 text-xs text-[var(--text-secondary)]">
                      {document.current_version
                        ? `v${document.current_version.version_number} · ${document.current_version.chunk_count} chunks`
                        : "—"}
                    </td>
                    <td className="px-2 py-3">
                      <div className="flex justify-end gap-1">
                        {document.current_version && (
                          <button
                            type="button"
                            title="Descargar"
                            className="rounded p-2 hover:bg-[var(--bg-hover)]"
                            onClick={() =>
                              download(
                                `/documents/${document.id}/download`,
                                document.current_version?.original_filename || document.title,
                              )
                            }
                          >
                            <Download size={15} />
                          </button>
                        )}
                        <button
                          type="button"
                          title="Historial de versiones"
                          className="rounded p-2 hover:bg-[var(--bg-hover)]"
                          onClick={() => showVersions(document)}
                        >
                          <History size={15} />
                        </button>
                        {canManage && !document.deleted_at && (
                          <>
                            <button
                              type="button"
                              title="Editar metadatos"
                              className="rounded p-2 hover:bg-[var(--bg-hover)]"
                              onClick={() => setEditingDocument({ ...document })}
                            >
                              <Pencil size={15} />
                            </button>
                            <button
                              type="button"
                              title="Reemplazar"
                              disabled={replacingId === document.id}
                              className="rounded p-2 hover:bg-[var(--bg-hover)] disabled:opacity-50"
                              onClick={() => replace(document)}
                            >
                              {replacingId === document.id ? (
                                <LoaderCircle className="animate-spin" size={15} />
                              ) : (
                                <Upload size={15} />
                              )}
                            </button>
                            <button
                              type="button"
                              title="Reindexar"
                              className="rounded p-2 hover:bg-[var(--bg-hover)]"
                              onClick={() => mutate(`/documents/${document.id}/reindex`)}
                            >
                              <RefreshCw size={15} />
                            </button>
                            <button
                              type="button"
                              title="Eliminar"
                              className="rounded p-2 text-red-400 hover:bg-red-500/10"
                              onClick={() =>
                                mutate(
                                  `/documents/${document.id}`,
                                  "DELETE",
                                  `¿Eliminar ${document.title}? Se podrá restaurar durante 30 días.`,
                                )
                              }
                            >
                              <Trash2 size={15} />
                            </button>
                          </>
                        )}
                        {canManage && document.deleted_at && (
                          <button
                            type="button"
                            title="Restaurar"
                            className="rounded p-2 text-emerald-400 hover:bg-emerald-500/10"
                            onClick={() => mutate(`/documents/${document.id}/restore`)}
                          >
                            <ArchiveRestore size={15} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!documents.items.length && (
              <p className="py-10 text-center text-sm text-[var(--text-muted)]">
                No hay documentos para estos filtros.
              </p>
            )}
          </div>
          <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
            <span>
              {documents.total
                ? `${documents.offset + 1}-${Math.min(documents.offset + documents.items.length, documents.total)} de ${documents.total}`
                : "0 documentos"}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                className={`${BUTTON} border border-[var(--border-color)] py-1`}
                disabled={documents.offset === 0}
                onClick={() => loadDocuments(Math.max(0, documents.offset - documents.limit))}
              >
                Anterior
              </button>
              <button
                type="button"
                className={`${BUTTON} border border-[var(--border-color)] py-1`}
                disabled={documents.offset + documents.items.length >= documents.total}
                onClick={() => loadDocuments(documents.offset + documents.limit)}
              >
                Siguiente
              </button>
            </div>
          </div>
        </section>

        <aside className="space-y-4">
          <section className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-4">
            <h3 className="font-semibold">Probar recuperación</h3>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Busca con el mismo motor híbrido que usa WhatsApp, limitado al área seleccionada.
            </p>
            <textarea
              className={`${INPUT} mt-3 min-h-24`}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Ej.: ¿Cómo se autoriza una orden de compra?"
            />
            <button
              type="button"
              className={`${BUTTON} mt-2 w-full bg-[var(--accent)] text-white`}
              onClick={testSearch}
              disabled={searching || !searchText.trim()}
            >
              {searching ? (
                <LoaderCircle className="animate-spin" size={16} />
              ) : (
                <Search size={16} />
              )}
              Probar
            </button>
            <div className="mt-4 space-y-3">
              {hits.map((hit) => (
                <article
                  key={`${hit.reference_code}:${hit.version_number}:${hit.page_number ?? ""}:${hit.location_label ?? ""}:${hit.section_title ?? ""}`}
                  className="rounded border border-[var(--border-color)] p-3"
                >
                  <div className="flex justify-between gap-2 text-xs">
                    <span className="font-semibold text-[var(--accent)]">
                      {hit.reference_code} · v{hit.version_number}
                    </span>
                    <span>{Math.round(hit.score * 100)}%</span>
                  </div>
                  <p className="mt-1 text-sm font-medium">{hit.title}</p>
                  <p className="mt-2 line-clamp-5 whitespace-pre-wrap text-xs text-[var(--text-secondary)]">
                    {hit.content}
                  </p>
                  <p className="mt-2 text-xs text-[var(--text-muted)]">
                    {hit.location_label ||
                      (hit.page_number ? `Página ${hit.page_number}` : "Sin ubicación")}
                  </p>
                </article>
              ))}
            </div>
          </section>
          {!agentId && settings && (
            <section className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-4 text-xs text-[var(--text-secondary)]">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                  <Settings2 size={16} />
                  Configuración compartida
                </h3>
                {canManageSettings && (
                  <button
                    type="button"
                    className="text-[var(--accent)] hover:underline"
                    onClick={() => setSettingsDraft({ ...settings })}
                  >
                    Ajustar
                  </button>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-2">
                <dt>Embeddings</dt>
                <dd className="text-right">{settings.embedding_model}</dd>
                <dt>Dimensiones</dt>
                <dd className="text-right">{settings.embedding_dimensions}</dd>
                <dt>OCR / visión</dt>
                <dd className="text-right">
                  {settings.ocr_enabled ? settings.vision_model : "Desactivado"}
                </dd>
                <dt>Top K</dt>
                <dd className="text-right">{settings.retrieval_top_k}</dd>
                <dt>Retención</dt>
                <dd className="text-right">{settings.retention_days} días</dd>
                <dt>Cola</dt>
                <dd className="text-right">{stats?.queue_depth || 0}</dd>
                <dt>Worker</dt>
                <dd
                  className={`text-right ${stats?.worker_last_activity && Date.now() - new Date(stats.worker_last_activity).getTime() < 90000 ? "text-emerald-400" : "text-red-400"}`}
                >
                  {stats?.worker_last_activity &&
                  Date.now() - new Date(stats.worker_last_activity).getTime() < 90000
                    ? "Activo"
                    : "Sin heartbeat"}
                </dd>
              </dl>
            </section>
          )}
        </aside>
      </div>

      {editingDocument && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-xl rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold">Editar {editingDocument.reference_code}</h3>
              <button type="button" onClick={() => setEditingDocument(null)}>
                <X size={18} />
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="text-xs text-[var(--text-secondary)] md:col-span-2">
                Título
                <input
                  className={`${INPUT} mt-1`}
                  value={editingDocument.title}
                  onChange={(e) =>
                    setEditingDocument({ ...editingDocument, title: e.target.value })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)] md:col-span-2">
                Carpeta
                <select
                  className={`${INPUT} mt-1`}
                  value={editingDocument.folder_id}
                  onChange={(e) =>
                    setEditingDocument({ ...editingDocument, folder_id: e.target.value })
                  }
                >
                  {folders
                    .filter(
                      (folder) =>
                        !agentId || visibleAreas.some((area) => area.id === folder.area_id),
                    )
                    .map((folder) => (
                      <option key={folder.id} value={folder.id}>
                        {areas.find((area) => area.id === folder.area_id)?.name} /{" "}
                        {folderPath(folder)}
                      </option>
                    ))}
                </select>
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Código interno
                <input
                  className={`${INPUT} mt-1`}
                  value={editingDocument.internal_code || ""}
                  onChange={(e) =>
                    setEditingDocument({
                      ...editingDocument,
                      internal_code: e.target.value || null,
                    })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Responsable
                <input
                  className={`${INPUT} mt-1`}
                  value={editingDocument.responsible || ""}
                  onChange={(e) =>
                    setEditingDocument({ ...editingDocument, responsible: e.target.value || null })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Vigente desde
                <input
                  type="date"
                  className={`${INPUT} mt-1`}
                  value={editingDocument.effective_from || ""}
                  onChange={(e) =>
                    setEditingDocument({
                      ...editingDocument,
                      effective_from: e.target.value || null,
                    })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Vigente hasta
                <input
                  type="date"
                  className={`${INPUT} mt-1`}
                  value={editingDocument.effective_to || ""}
                  onChange={(e) =>
                    setEditingDocument({ ...editingDocument, effective_to: e.target.value || null })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)] md:col-span-2">
                Descripción
                <textarea
                  className={`${INPUT} mt-1 min-h-20`}
                  value={editingDocument.description || ""}
                  onChange={(e) =>
                    setEditingDocument({ ...editingDocument, description: e.target.value || null })
                  }
                />
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className={`${BUTTON} border border-[var(--border-color)]`}
                onClick={() => setEditingDocument(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={`${BUTTON} bg-[var(--accent)] text-white`}
                onClick={saveDocument}
              >
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}

      {versionDocument && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-2xl rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="font-semibold">Versiones de {versionDocument.title}</h3>
                <p className="text-xs text-[var(--text-muted)]">{versionDocument.reference_code}</p>
              </div>
              <button type="button" onClick={() => setVersionDocument(null)}>
                <X size={18} />
              </button>
            </div>
            <div className="max-h-96 overflow-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-[var(--text-muted)]">
                  <tr>
                    <th className="py-2">Versión</th>
                    <th>Archivo</th>
                    <th>Estado</th>
                    <th>Contenido</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((version) => (
                    <tr key={version.id} className="border-t border-[var(--border-color)]">
                      <td className="py-3">
                        v{version.version_number}
                        {version.id === versionDocument.current_version?.id ? " · vigente" : ""}
                      </td>
                      <td className="max-w-56 truncate" title={version.original_filename}>
                        {version.original_filename}
                      </td>
                      <td>
                        <span
                          className={`rounded px-2 py-1 text-xs ${statusStyle(version.status)}`}
                        >
                          {version.status}
                        </span>
                      </td>
                      <td className="text-xs text-[var(--text-secondary)]">
                        {version.page_count} pág. · {version.chunk_count} chunks
                      </td>
                      <td>
                        <button
                          type="button"
                          title="Descargar versión"
                          className="rounded p-2 hover:bg-[var(--bg-hover)]"
                          onClick={() =>
                            download(
                              `/documents/${versionDocument.id}/download?version_id=${version.id}`,
                              version.original_filename,
                            )
                          }
                        >
                          <Download size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {settingsDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-2xl rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="font-semibold">Configuración RAG</h3>
                <p className="text-xs text-[var(--text-muted)]">
                  Chunking cambia en futuras ingestas o reindexaciones.
                </p>
              </div>
              <button type="button" onClick={() => setSettingsDraft(null)}>
                <X size={18} />
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="text-xs text-[var(--text-secondary)]">
                Máximo por archivo (MB)
                <input
                  type="number"
                  className={`${INPUT} mt-1`}
                  value={Math.round(settingsDraft.max_file_bytes / 1048576)}
                  onChange={(e) =>
                    setSettingsDraft({
                      ...settingsDraft,
                      max_file_bytes: Number(e.target.value) * 1048576,
                    })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Máximo por lote (MB)
                <input
                  type="number"
                  className={`${INPUT} mt-1`}
                  value={Math.round(settingsDraft.max_batch_bytes / 1048576)}
                  onChange={(e) =>
                    setSettingsDraft({
                      ...settingsDraft,
                      max_batch_bytes: Number(e.target.value) * 1048576,
                    })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Retención (días)
                <input
                  type="number"
                  className={`${INPUT} mt-1`}
                  value={settingsDraft.retention_days}
                  onChange={(e) =>
                    setSettingsDraft({ ...settingsDraft, retention_days: Number(e.target.value) })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Resultados Top K
                <input
                  type="number"
                  className={`${INPUT} mt-1`}
                  value={settingsDraft.retrieval_top_k}
                  onChange={(e) =>
                    setSettingsDraft({ ...settingsDraft, retrieval_top_k: Number(e.target.value) })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Tokens por chunk
                <input
                  type="number"
                  className={`${INPUT} mt-1`}
                  value={settingsDraft.chunk_tokens}
                  onChange={(e) =>
                    setSettingsDraft({ ...settingsDraft, chunk_tokens: Number(e.target.value) })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Solapamiento
                <input
                  type="number"
                  className={`${INPUT} mt-1`}
                  value={settingsDraft.chunk_overlap_tokens}
                  onChange={(e) =>
                    setSettingsDraft({
                      ...settingsDraft,
                      chunk_overlap_tokens: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Score mínimo
                <input
                  type="number"
                  step="0.01"
                  className={`${INPUT} mt-1`}
                  value={settingsDraft.min_relevance_score}
                  onChange={(e) =>
                    setSettingsDraft({
                      ...settingsDraft,
                      min_relevance_score: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-secondary)]">
                Peso vectorial
                <input
                  type="number"
                  step="0.05"
                  className={`${INPUT} mt-1`}
                  value={settingsDraft.vector_weight}
                  onChange={(e) =>
                    setSettingsDraft({
                      ...settingsDraft,
                      vector_weight: Number(e.target.value),
                      lexical_weight: Number((1 - Number(e.target.value)).toFixed(2)),
                    })
                  }
                />
              </label>
              <label className="flex items-center gap-2 text-sm md:col-span-2">
                <input
                  type="checkbox"
                  checked={settingsDraft.ocr_enabled}
                  onChange={(e) =>
                    setSettingsDraft({ ...settingsDraft, ocr_enabled: e.target.checked })
                  }
                />
                OCR local y fallback visual
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className={`${BUTTON} border border-[var(--border-color)]`}
                onClick={() => setSettingsDraft(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={`${BUTTON} bg-[var(--accent)] text-white`}
                onClick={saveSettings}
              >
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

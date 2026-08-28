import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, LoaderCircle, Pencil, Plus, Save, ShieldCheck, UserMinus, UserPlus } from "lucide-react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import type { AgentAuthorizedUser, AgentDocumentArea, GlobalAuthorizedIdentity } from "../../access/types";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

const INPUT = "w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:opacity-60";

interface IdentityDraft {
  mode: "create" | "edit";
  id?: string;
  originalPhone?: string;
  phone: string;
  name: string;
  notes: string;
  assignAfterCreate: boolean;
}

interface PolicyDraft {
  userId: string;
  name: string;
  isActive: boolean;
  hasAllAreaAccess: boolean;
  areaIds: string[];
}

export default function AgentAccessPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.ALL);
  const canReadAreas = hasPermission(user, PERMISSIONS.DOCUMENTS_READ);
  const [library, setLibrary] = useState<GlobalAuthorizedIdentity[]>([]);
  const [assigned, setAssigned] = useState<AgentAuthorizedUser[]>([]);
  const [areas, setAreas] = useState<AgentDocumentArea[]>([]);
  const [identityDraft, setIdentityDraft] = useState<IdentityDraft | null>(null);
  const [policyDraft, setPolicyDraft] = useState<PolicyDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const activeAgentId = useRef<string | null>(selectedAgent?.id ?? null);
  activeAgentId.current = selectedAgent?.id ?? null;

  const load = async (agentId = selectedAgent?.id) => {
    if (!agentId) return;
    setLoading(true);
    setError("");
    try {
      const [libraryRows, assignedRows, areaRows] = await Promise.all([
        api<GlobalAuthorizedIdentity[]>("/users/"),
        api<AgentAuthorizedUser[]>(`/agents/${agentId}/authorized-users`),
        canReadAreas ? api<AgentDocumentArea[]>(`/agents/${agentId}/document-areas`) : Promise.resolve([]),
      ]);
      if (activeAgentId.current !== agentId) return;
      setLibrary(libraryRows);
      setAssigned(assignedRows);
      setAreas(areaRows);
    } catch (value) {
      if (activeAgentId.current !== agentId) return;
      setError(value instanceof Error ? value.message : "No se pudo cargar el acceso WhatsApp.");
    } finally {
      if (activeAgentId.current === agentId) setLoading(false);
    }
  };

  useEffect(() => {
    const agentId = selectedAgent?.id;
    setIdentityDraft(null);
    setPolicyDraft(null);
    setNotice("");
    setError("");
    setLibrary([]);
    setAssigned([]);
    setAreas([]);
    setSaving(false);
    setBusyId(null);
    setLoading(Boolean(agentId));
    if (agentId) void load(agentId);
  }, [selectedAgent?.id, canReadAreas]);

  const assignedIds = useMemo(() => new Set(assigned.map((item) => item.id)), [assigned]);
  const available = useMemo(() => library.filter((item) => !assignedIds.has(item.id)), [assignedIds, library]);
  const selectableAreas = areas.filter((area) => area.is_active && !area.is_general);

  if (!selectedAgent) return null;

  const openCreate = () => {
    setPolicyDraft(null);
    setIdentityDraft({ mode: "create", phone: "", name: "", notes: "", assignAfterCreate: true });
    setError("");
  };

  const openIdentity = (identity: GlobalAuthorizedIdentity) => {
    setPolicyDraft(null);
    setIdentityDraft({ mode: "edit", id: identity.id, originalPhone: identity.phone_number, phone: identity.phone_number, name: identity.name || "", notes: identity.notes || "", assignAfterCreate: false });
    setError("");
  };

  const openPolicy = (identity: GlobalAuthorizedIdentity | AgentAuthorizedUser) => {
    const current = assigned.find((item) => item.id === identity.id);
    const generalIds = new Set(areas.filter((area) => area.is_general).map((area) => area.id));
    setIdentityDraft(null);
    setPolicyDraft({
      userId: identity.id,
      name: identity.name || identity.phone_number,
      isActive: current?.is_active ?? true,
      hasAllAreaAccess: current?.has_all_area_access ?? false,
      areaIds: (current?.area_ids || []).filter((id) => !generalIds.has(id)),
    });
    setError("");
  };

  const assignmentBody = (draft: PolicyDraft) => ({
    is_active: draft.isActive,
    has_all_area_access: draft.hasAllAreaAccess,
    area_ids: draft.hasAllAreaAccess ? [] : draft.areaIds,
  });

  const saveIdentity = async () => {
    if (!identityDraft) return;
    const agentId = selectedAgent.id;
    if (!identityDraft.phone.trim()) return setError("El teléfono es obligatorio.");
    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (identityDraft.mode === "create") {
        const created = await api<GlobalAuthorizedIdentity>("/users/", {
          method: "POST",
          body: JSON.stringify({ phone_number: identityDraft.phone.trim(), name: identityDraft.name.trim() || null, notes: identityDraft.notes.trim() || null }),
        });
        if (identityDraft.assignAfterCreate) {
          await api(`/agents/${agentId}/authorized-users/${created.id}`, {
            method: "PUT",
            body: JSON.stringify({ is_active: true, has_all_area_access: false, area_ids: [] }),
          });
        }
        if (activeAgentId.current === agentId) setNotice(identityDraft.assignAfterCreate ? "Identidad creada y asignada al agente con una política inicial." : "Identidad creada en la biblioteca global.");
      } else {
        await api(`/users/${identityDraft.originalPhone}`, {
          method: "PATCH",
          body: JSON.stringify({ name: identityDraft.name.trim() || null, notes: identityDraft.notes.trim() || null }),
        });
        if (activeAgentId.current === agentId) setNotice("Identidad global actualizada. La política del agente no fue modificada.");
      }
      if (activeAgentId.current !== agentId) return;
      setIdentityDraft(null);
      await load(agentId);
    } catch (value) {
      if (activeAgentId.current === agentId) setError(value instanceof Error ? value.message : "No se pudo guardar la identidad.");
    } finally {
      if (activeAgentId.current === agentId) setSaving(false);
    }
  };

  const savePolicy = async () => {
    if (!policyDraft) return;
    const agentId = selectedAgent.id;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(`/agents/${agentId}/authorized-users/${policyDraft.userId}`, { method: "PUT", body: JSON.stringify(assignmentBody(policyDraft)) });
      if (activeAgentId.current !== agentId) return;
      setNotice("Política de acceso guardada para este agente.");
      setPolicyDraft(null);
      await load(agentId);
    } catch (value) {
      if (activeAgentId.current === agentId) setError(value instanceof Error ? value.message : "No se pudo guardar la política.");
    } finally {
      if (activeAgentId.current === agentId) setSaving(false);
    }
  };

  const unassign = async (identity: AgentAuthorizedUser) => {
    if (!window.confirm(`¿Quitar el acceso de ${identity.name || identity.phone_number} a ${selectedAgent.name}?`)) return;
    const agentId = selectedAgent.id;
    setBusyId(identity.id);
    setError("");
    setNotice("");
    try {
      await api(`/agents/${agentId}/authorized-users/${identity.id}`, { method: "DELETE" });
      if (activeAgentId.current !== agentId) return;
      setNotice("Acceso quitado. La identidad global se conserva para otros agentes.");
      await load(agentId);
    } catch (value) {
      if (activeAgentId.current === agentId) setError(value instanceof Error ? value.message : "No se pudo quitar el acceso.");
    } finally {
      if (activeAgentId.current === agentId) setBusyId(null);
    }
  };

  const areaSummary = (identity: AgentAuthorizedUser) => {
    if (identity.has_all_area_access) return "Todas las áreas asignadas al agente";
    const names = identity.area_ids.map((id) => areas.find((area) => area.id === id)?.name).filter(Boolean);
    return names.length ? names.join(", ") : `${identity.area_ids.length} áreas asignadas`;
  };

  return (
    <div className="max-w-6xl space-y-5">
      <header className="flex flex-wrap items-center gap-3"><ShieldCheck className="text-[var(--accent)]" size={22} /><div><h2 className="text-xl font-semibold">Acceso WhatsApp de {selectedAgent.name}</h2><p className="text-sm text-[var(--text-muted)]">Identidades reutilizables con una política independiente para este agente.</p></div>{canManage && !identityDraft && !policyDraft && <button onClick={openCreate} className="ml-auto flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white"><Plus size={16} /> Nueva identidad</button>}</header>
      <aside className="rounded border border-[var(--border-color)] bg-[var(--bg-card)] p-4 text-sm text-[var(--text-secondary)]">Teléfono, nombre y notas pertenecen a la identidad global. Estado y áreas documentales se guardan únicamente en el vínculo con <strong className="text-[var(--text-primary)]">{selectedAgent.name}</strong>.</aside>
      {error && <p className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400" role="alert">{error}</p>}
      {notice && <p className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400" role="status">{notice}</p>}

      {identityDraft && <section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5" aria-labelledby="identity-editor-title"><div className="flex items-center gap-3"><button onClick={() => setIdentityDraft(null)} aria-label="Cerrar editor de identidad" className="rounded p-1 hover:bg-[var(--bg-hover)]"><ArrowLeft size={17} /></button><div><h3 id="identity-editor-title" className="font-semibold">{identityDraft.mode === "create" ? "Nueva identidad global" : "Editar identidad global"}</h3><p className="text-xs text-[var(--text-muted)]">Este formulario no modifica la política de otros agentes.</p></div></div><div className="grid gap-4 md:grid-cols-2"><label className="text-xs">Teléfono<input autoFocus disabled={identityDraft.mode === "edit"} className={`${INPUT} mt-1 font-mono`} value={identityDraft.phone} onChange={(event) => setIdentityDraft({ ...identityDraft, phone: event.target.value })} placeholder="5493875123456" /></label><label className="text-xs">Nombre<input className={`${INPUT} mt-1`} value={identityDraft.name} onChange={(event) => setIdentityDraft({ ...identityDraft, name: event.target.value })} /></label><label className="text-xs md:col-span-2">Notas internas<textarea rows={3} className={`${INPUT} mt-1 resize-y`} value={identityDraft.notes} onChange={(event) => setIdentityDraft({ ...identityDraft, notes: event.target.value })} /></label>{identityDraft.mode === "create" && <label className="flex items-center gap-2 text-sm md:col-span-2"><input type="checkbox" checked={identityDraft.assignAfterCreate} onChange={(event) => setIdentityDraft({ ...identityDraft, assignAfterCreate: event.target.checked })} /> Asignar ahora a {selectedAgent.name} con una política inicial</label>}</div><div className="flex justify-end gap-2"><button onClick={() => setIdentityDraft(null)} className="rounded border border-[var(--border-color)] px-3 py-2 text-sm">Cancelar</button><button onClick={saveIdentity} disabled={saving} className="flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50">{saving ? <LoaderCircle className="animate-spin" size={15} /> : <Save size={15} />} Guardar identidad</button></div></section>}

      {policyDraft && <section className="space-y-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5" aria-labelledby="policy-editor-title"><div className="flex items-center gap-3"><button onClick={() => setPolicyDraft(null)} aria-label="Cerrar editor de acceso" className="rounded p-1 hover:bg-[var(--bg-hover)]"><ArrowLeft size={17} /></button><div><h3 id="policy-editor-title" className="font-semibold">Acceso de {policyDraft.name}</h3><p className="text-xs text-[var(--text-muted)]">Política exclusiva de {selectedAgent.name}. El área General se agrega automáticamente cuando está asignada al agente.</p></div></div><div className="space-y-3"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={policyDraft.isActive} onChange={(event) => setPolicyDraft({ ...policyDraft, isActive: event.target.checked })} /> Acceso activo</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={policyDraft.hasAllAreaAccess} onChange={(event) => setPolicyDraft({ ...policyDraft, hasAllAreaAccess: event.target.checked })} /> Acceso a todas las áreas asignadas al agente</label><fieldset disabled={policyDraft.hasAllAreaAccess || !canReadAreas} className="grid gap-2 rounded border border-[var(--border-color)] p-3 sm:grid-cols-2 disabled:opacity-60"><legend className="px-1 text-xs font-medium">Áreas adicionales</legend>{selectableAreas.map((area) => <label key={area.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={policyDraft.areaIds.includes(area.id)} onChange={(event) => setPolicyDraft({ ...policyDraft, areaIds: event.target.checked ? [...policyDraft.areaIds, area.id] : policyDraft.areaIds.filter((id) => id !== area.id) })} /> {area.name}</label>)}{selectableAreas.length === 0 && <p className="text-xs text-[var(--text-muted)] sm:col-span-2">No hay áreas adicionales asignadas a este agente.</p>}</fieldset>{!canReadAreas && <p className="text-xs text-amber-300">No tenés permiso para leer las áreas documentales; no podés modificar ese alcance.</p>}</div><div className="flex justify-end gap-2"><button onClick={() => setPolicyDraft(null)} className="rounded border border-[var(--border-color)] px-3 py-2 text-sm">Cancelar</button><button onClick={savePolicy} disabled={saving || !canReadAreas} className="flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-50">{saving ? <LoaderCircle className="animate-spin" size={15} /> : <Save size={15} />} Guardar acceso</button></div></section>}

      {loading ? <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status"><LoaderCircle className="animate-spin" size={16} /> Cargando accesos…</p> : <>
        <section><h3 className="mb-3 font-semibold">Con acceso ({assigned.length})</h3><div className="grid gap-3 lg:grid-cols-2">{assigned.map((identity) => <article key={identity.id} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"><div className="flex items-start gap-3"><div className="min-w-0 flex-1"><h4 className="font-semibold">{identity.name || "Sin nombre"}</h4><code className="mt-1 block text-xs text-[var(--text-muted)]">{identity.phone_number}</code></div><span className={`rounded px-2 py-1 text-xs ${identity.is_active ? "bg-emerald-500/10 text-emerald-400" : "bg-amber-500/10 text-amber-300"}`}>{identity.is_active ? "Activo" : "Pausado"}</span></div><p className="mt-3 text-sm text-[var(--text-secondary)]">{areaSummary(identity)}</p>{identity.notes && <p className="mt-2 text-xs text-[var(--text-muted)]">{identity.notes}</p>}{canManage && <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => openPolicy(identity)} className="flex items-center gap-1 rounded bg-[var(--accent)] px-2 py-1.5 text-xs text-white"><ShieldCheck size={14} /> Editar acceso</button><button onClick={() => openIdentity(identity)} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-1.5 text-xs"><Pencil size={14} /> Editar identidad</button><button onClick={() => unassign(identity)} disabled={busyId === identity.id} className="flex items-center gap-1 rounded border border-red-500/40 px-2 py-1.5 text-xs text-red-400"><UserMinus size={14} /> Quitar acceso</button></div>}</article>)}{assigned.length === 0 && <p className="text-sm text-[var(--text-muted)]">Este agente todavía no tiene identidades autorizadas.</p>}</div></section>
        <section><h3 className="mb-3 font-semibold">Disponibles para reutilizar ({available.length})</h3><div className="grid gap-3 lg:grid-cols-2">{available.map((identity) => <article key={identity.id} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"><h4 className="font-semibold">{identity.name || "Sin nombre"}</h4><code className="mt-1 block text-xs text-[var(--text-muted)]">{identity.phone_number}</code>{identity.notes && <p className="mt-2 text-xs text-[var(--text-muted)]">{identity.notes}</p>}{canManage && <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => openPolicy(identity)} className="flex items-center gap-1 rounded bg-[var(--accent)] px-2 py-1.5 text-xs text-white"><UserPlus size={14} /> Asignar</button><button onClick={() => openIdentity(identity)} className="flex items-center gap-1 rounded border border-[var(--border-color)] px-2 py-1.5 text-xs"><Pencil size={14} /> Editar identidad</button></div>}</article>)}{available.length === 0 && <p className="text-sm text-[var(--text-muted)]">No quedan identidades globales disponibles.</p>}</div></section>
      </>}
    </div>
  );
}

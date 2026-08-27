import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Users as UsersIcon, LoaderCircle, Plus, X, Pencil, ArrowLeft, Save } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";

interface User {
  id: string; phone_number: string; name: string | null; is_active: boolean;
  notes: string | null;
  has_all_area_access: boolean; area_ids: string[];
  created_at: string; updated_at: string;
}
interface Area { id: string; name: string; is_active: boolean; is_general: boolean }

function Switch({ checked, onChange, disabled }: { checked: boolean; onChange: () => void; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={onChange}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${checked ? "bg-[var(--accent)]" : "bg-[var(--border-color)]"}`}>
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
    </button>
  );
}

const HELP = "text-xs text-[var(--text-muted)]";

export default function UsersPage() {
  const { user: adminUser } = useAuth();
  const canEdit = hasPermission(adminUser, PERMISSIONS.ALL);
  const [users, setUsers] = useState<User[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newPhone, setNewPhone] = useState("");
  const [newName, setNewName] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [newAreaIds, setNewAreaIds] = useState<string[]>([]);
  const [newAllAreas, setNewAllAreas] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const [editing, setEditing] = useState<User | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const load = () => api<User[]>("/users/").then(setUsers);
  useEffect(() => {
    Promise.all([load(), api<Area[]>("/documents/areas").then(setAreas)]).finally(() => setLoading(false));
  }, []);

  const saveEdit = async () => {
    if (!editing) return;
    setSavingEdit(true);
    try {
      await api(`/users/${editing.phone_number}`, {
        method: "PATCH",
        body: JSON.stringify({ name: editing.name, notes: editing.notes, area_ids: editing.area_ids, has_all_area_access: editing.has_all_area_access }),
      });
      setEditing(null);
      await load();
    } finally { setSavingEdit(false); }
  };

  const toggle = async (phone: string, field: string, current: boolean) => {
    setBusy(`${phone}:${field}`);
    try {
      await api(`/users/${phone}`, { method: "PATCH", body: JSON.stringify({ [field]: !current }) });
      await load();
    } finally { setBusy(null); }
  };

  const createUser = async () => {
    if (!newPhone.trim()) {
      setCreateError("El telefono es obligatorio");
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      await api("/users/", {
        method: "POST",
        body: JSON.stringify({
          phone_number: newPhone.trim(),
          name: newName.trim() || null,
          notes: newNotes.trim() || null,
          area_ids: newAreaIds,
          has_all_area_access: newAllAreas,
        }),
      });
      setShowCreate(false);
      setNewPhone(""); setNewName(""); setNewNotes(""); setNewAreaIds([]); setNewAllAreas(false);
      await load();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Error al crear el usuario");
    } finally { setCreating(false); }
  };

  // ----------------------------- Vista edicion -----------------------------
  if (editing) return (
    <div className="max-w-lg">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => setEditing(null)}
            className="flex items-center gap-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
            <ArrowLeft size={16} /> Volver
          </button>
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">
            Editar usuario: <span className="font-mono text-[var(--accent)]">{editing.phone_number}</span>
          </h2>
        </div>
        <button onClick={saveEdit} disabled={savingEdit}
          className="flex items-center gap-2 px-4 py-2 text-sm rounded-md bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white disabled:opacity-50 transition-colors">
          {savingEdit ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
          {savingEdit ? "Guardando..." : "Guardar"}
        </button>
      </div>
      <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-lg p-5 space-y-4">
        <div>
          <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Telefono</label>
          <input value={editing.phone_number} disabled
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm font-mono text-[var(--text-muted)] cursor-not-allowed" />
          <p className={`mt-1 ${HELP}`}>El telefono no se puede modificar</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Nombre</label>
          <input value={editing.name || ""} onChange={(e) => setEditing({ ...editing, name: e.target.value || null })}
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
          <p className={`mt-1 ${HELP}`}>Nombre para identificar al usuario en el panel</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Notas</label>
          <input value={editing.notes || ""} onChange={(e) => setEditing({ ...editing, notes: e.target.value || null })}
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
          <p className={`mt-1 ${HELP}`}>Notas internas sobre el usuario</p>
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="text-xs font-medium text-[var(--text-secondary)]">Áreas documentales</label>
            <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]"><input type="checkbox" checked={editing.has_all_area_access} onChange={(e) => setEditing({ ...editing, has_all_area_access: e.target.checked })} />Acceso a todas</label>
          </div>
          <div className="grid grid-cols-2 gap-2 rounded border border-[var(--border-color)] p-3">
            {areas.filter((area) => area.is_active).map((area) => <label key={area.id} className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={editing.has_all_area_access} checked={editing.area_ids.includes(area.id)} onChange={(e) => setEditing({ ...editing, area_ids: e.target.checked ? [...editing.area_ids, area.id] : editing.area_ids.filter((id) => id !== area.id) })} />{area.name}</label>)}
          </div>
          <p className={`mt-1 ${HELP}`}>Sin selección se asigna automáticamente el área General.</p>
        </div>
      </div>
    </div>
  );

  // ----------------------------- Vista lista -----------------------------
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <UsersIcon size={22} className="text-[var(--accent)]" />
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Usuarios WhatsApp</h2>
          <span className="text-sm text-[var(--text-muted)]">({users.length})</span>
        </div>
        {canEdit && <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white transition-colors">
          <Plus size={14} /> Nuevo usuario
        </button>}
      </div>
      <p className={`${HELP} mb-4`}>
        Usuarios autorizados a interactuar con el agente por WhatsApp. Solo los usuarios activos pueden enviar mensajes.
      </p>

      {/* Modal crear usuario */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-lg w-full max-w-md">
            <div className="flex items-center justify-between border-b border-[var(--border-color)] px-4 py-3">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Nuevo usuario WhatsApp</h3>
              <button onClick={() => { setShowCreate(false); setCreateError(""); }}
                className="p-1 rounded text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                <X size={16} />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Numero de telefono</label>
                <input value={newPhone} onChange={(e) => setNewPhone(e.target.value)} placeholder="ej: 5493875123456"
                  className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
                <p className={`mt-1 ${HELP}`}>Numero completo con codigo de pais, sin + ni espacios. Ej: 5493875123456</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Nombre (opcional)</label>
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="ej: Juan Perez"
                  className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
                <p className={`mt-1 ${HELP}`}>Nombre para identificar al usuario en el panel</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Notas (opcional)</label>
                <input value={newNotes} onChange={(e) => setNewNotes(e.target.value)} placeholder="ej: Gerente de compras"
                  className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]" />
                <p className={`mt-1 ${HELP}`}>Notas internas sobre el usuario</p>
              </div>
              <div>
                <label className="mb-2 flex items-center justify-between text-xs font-medium text-[var(--text-secondary)]">Áreas documentales <span className="flex items-center gap-2 font-normal"><input type="checkbox" checked={newAllAreas} onChange={(e) => setNewAllAreas(e.target.checked)} />Todas</span></label>
                <div className="grid grid-cols-2 gap-2 rounded border border-[var(--border-color)] p-3">
                  {areas.filter((area) => area.is_active).map((area) => <label key={area.id} className="flex items-center gap-2 text-xs"><input type="checkbox" disabled={newAllAreas} checked={newAreaIds.includes(area.id)} onChange={(e) => setNewAreaIds(e.target.checked ? [...newAreaIds, area.id] : newAreaIds.filter((id) => id !== area.id))} />{area.name}</label>)}
                </div>
              </div>
              {createError && <p className="text-xs text-[var(--error)]">{createError}</p>}
              <div className="flex justify-end gap-2">
                <button onClick={() => { setShowCreate(false); setCreateError(""); }}
                  className="px-3 py-1.5 text-sm rounded bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]">
                  Cancelar
                </button>
                <button onClick={createUser} disabled={creating}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white disabled:opacity-50">
                  {creating ? <LoaderCircle size={14} className="animate-spin" /> : <Plus size={14} />}
                  {creating ? "Creando..." : "Crear usuario"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-[var(--text-secondary)] text-sm">
          <LoaderCircle size={16} className="animate-spin" /> Cargando usuarios...
        </div>
      ) : (
        <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-lg overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[var(--bg-secondary)] text-left text-[var(--text-secondary)]">
              <tr>
                <th className="px-4 py-2.5 font-medium">Telefono</th>
                <th className="px-4 py-2.5 font-medium">Nombre</th>
                <th className="px-4 py-2.5 font-medium">Notas</th>
                <th className="px-4 py-2.5 font-medium">Áreas</th>
                <th className="px-4 py-2.5 font-medium">Activo</th>
                <th className="px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-color)]">
              {users.map((u) => (
                <tr key={u.id} className={`hover:bg-[var(--bg-hover)] transition-colors ${u.is_active ? "" : "opacity-55"}`}>
                  <td className="px-4 py-3 font-mono text-[var(--text-primary)]">{u.phone_number}</td>
                  <td className="px-4 py-3 text-[var(--text-primary)]">{u.name || "—"}</td>
                  <td className="px-4 py-3 text-[var(--text-muted)] text-xs truncate max-w-xs">{u.notes || "—"}</td>
                  <td className="px-4 py-3 text-xs text-[var(--text-secondary)]">{u.has_all_area_access ? "Todas" : (u.area_ids.map((id) => areas.find((area) => area.id === id)?.name).filter(Boolean).join(", ") || "General")}</td>
                  <td className="px-4 py-3">
                    {busy === `${u.phone_number}:is_active` ? (
                      <LoaderCircle size={16} className="animate-spin text-[var(--text-secondary)]" />
                    ) : (
                      <Switch disabled={!canEdit} checked={u.is_active} onChange={() => toggle(u.phone_number, "is_active", u.is_active)} />
                    )}
                  </td>
                <td className="px-4 py-3">
                  {canEdit && <button onClick={() => setEditing(u)}
                    className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors">
                    <Pencil size={12} /> Editar
                  </button>}
                </td>
              </tr>
            ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-[var(--text-muted)] text-sm">
                    No hay usuarios autorizados.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

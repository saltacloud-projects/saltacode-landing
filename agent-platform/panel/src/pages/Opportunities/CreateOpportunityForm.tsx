import { useEffect, useMemo, useState } from "react";
import { contactName } from "./presentation";
import type { OpportunityCandidate } from "./types";

interface Props {
  candidates: OpportunityCandidate[];
  currentAdminId: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: {
    contact_id: string;
    source_conversation_id: string;
    title: string;
    summary?: string;
    assigned_operator_id?: string;
  }) => void;
}

export function CreateOpportunityForm({
  candidates,
  currentAdminId,
  busy,
  onCancel,
  onSubmit,
}: Props) {
  const [candidateId, setCandidateId] = useState(candidates[0]?.conversation_id ?? "");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [assignMe, setAssignMe] = useState(true);
  const candidate = useMemo(
    () => candidates.find((item) => item.conversation_id === candidateId),
    [candidateId, candidates],
  );

  useEffect(() => {
    if (!candidateId && candidates[0]) setCandidateId(candidates[0].conversation_id);
  }, [candidateId, candidates]);

  return (
    <form
      className="mb-4 rounded-lg border border-[var(--accent)]/35 bg-[var(--bg-card)] p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!candidate || !title.trim()) return;
        onSubmit({
          contact_id: candidate.contact.id,
          source_conversation_id: candidate.conversation_id,
          title: title.trim(),
          summary: summary.trim() || undefined,
          assigned_operator_id: assignMe ? currentAdminId : undefined,
        });
      }}
    >
      <h3 className="font-semibold">Nueva oportunidad</h3>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Sólo aparecen contactos probados por una conversación de este agente.
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-xs text-[var(--text-muted)]">
          Contacto y conversación de origen
          <select
            required
            value={candidateId}
            onChange={(event) => setCandidateId(event.target.value)}
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)]"
          >
            <option value="">Seleccionar…</option>
            {candidates.map((item) => (
              <option key={item.conversation_id} value={item.conversation_id}>
                {contactName(item.contact)} · {item.channel}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--text-muted)]">
          Título
          <input
            required
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Necesidad comercial concreta"
            className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)]"
          />
        </label>
      </div>
      <label className="mt-3 block text-xs text-[var(--text-muted)]">
        Contexto
        <textarea
          rows={3}
          maxLength={8_000}
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          placeholder="Alcance conocido, necesidad y próximo paso"
          className="mt-1 w-full resize-y rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)]"
        />
      </label>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={assignMe}
          onChange={(event) => setAssignMe(event.target.checked)}
        />
        Asignarme como responsable
      </label>
      {candidates.length === 0 && (
        <p className="mt-3 text-sm text-[var(--warning)]" role="status">
          No hay contactos con conversación de origen disponibles. Primero capturá el contacto desde
          un canal.
        </p>
      )}
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-[var(--border-color)] px-3 py-2 text-sm"
        >
          Cancelar
        </button>
        <button
          type="submit"
          disabled={busy || !candidate || !title.trim()}
          className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Crear oportunidad
        </button>
      </div>
    </form>
  );
}

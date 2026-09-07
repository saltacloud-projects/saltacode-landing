import { LoaderCircle, Plus, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import type { AgentProfile } from "../../agents/types";
import { ApiError, api } from "../../api/client";

const INPUT =
  "mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm";
const PROMPTS = [
  {
    key: "prompt_identity",
    label: "Identidad y presentación",
    help: "Nombre con el que se presenta, función y tono.",
  },
  {
    key: "prompt_domain",
    label: "Especialización",
    help: "Qué resuelve este agente y cuándo debe derivar.",
  },
  {
    key: "prompt_guardrails",
    label: "Límites de comportamiento",
    help: "Qué no debe hacer. Los permisos y consentimientos también se verifican fuera del prompt.",
  },
] as const;

export function AgentCreateForm() {
  const navigate = useNavigate();
  const { refreshProfiles } = useAgentWorkspace();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const buttonRef = useRef<HTMLButtonElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) nameRef.current?.focus();
  }, [open]);

  const close = () => {
    if (saving) return;
    setOpen(false);
    setError("");
    requestAnimationFrame(() => buttonRef.current?.focus());
  };

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError("");
    const text = (key: string) => String(form.get(key) ?? "").trim();
    try {
      const agent = await api<AgentProfile>("/profiles/", {
        method: "POST",
        body: JSON.stringify({
          name: text("name"),
          slug: text("slug"),
          description: text("description") || null,
          prompt_identity: text("prompt_identity"),
          prompt_domain: text("prompt_domain"),
          prompt_guardrails: text("prompt_guardrails"),
          retention_days: Number(form.get("retention_days")),
          unauthorized_message: text("unauthorized_message"),
          error_message: text("error_message"),
          is_public: false,
        }),
      });
      await refreshProfiles();
      navigate(`/agents/${agent.id}/identity`);
    } catch (value) {
      setError(
        value instanceof ApiError && value.status === 409
          ? "Ese identificador ya está en uso. Elegí uno diferente."
          : value instanceof ApiError && value.status === 403
            ? "No tenés permiso para crear agentes. Pedí acceso a un administrador."
            : value instanceof ApiError && value.status === 422
              ? "Revisá los campos obligatorios y el formato del identificador."
              : "No se pudo confirmar la creación. Revisá la lista de agentes antes de volver a enviar.",
      );
    } finally {
      setSaving(false);
    }
  };

  if (!open)
    return (
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex min-h-11 items-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm text-white"
      >
        <Plus size={16} /> Crear agente
      </button>
    );

  return (
    <section
      aria-labelledby="create-agent-title"
      className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="create-agent-title" className="font-semibold">
            Crear agente independiente
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Se crea inactivo y sin exposición pública. Después configurás su modelo, recursos y
            rutas, sin modificar otros agentes.
          </p>
        </div>
        <button
          type="button"
          onClick={close}
          disabled={saving}
          aria-label="Cancelar creación"
          className="flex min-h-11 min-w-11 items-center justify-center rounded border border-[var(--border-color)]"
        >
          <X size={18} />
        </button>
      </div>
      <form onSubmit={create} className="mt-5 space-y-4">
        <fieldset disabled={saving} className="grid gap-4 sm:grid-cols-2">
          <legend className="sr-only">Configuración inicial del agente</legend>
          <label className="text-sm">
            Nombre
            <input ref={nameRef} name="name" required maxLength={100} className={INPUT} />
          </label>
          <div className="text-sm">
            <label htmlFor="new-agent-slug">Identificador único</label>
            <input
              id="new-agent-slug"
              name="slug"
              required
              maxLength={100}
              pattern="[a-z0-9]+((_|-)[a-z0-9]+)*"
              placeholder="asesor-comercial"
              aria-describedby="agent-slug-help"
              className={INPUT}
            />
            <span id="agent-slug-help" className="mt-1 block text-xs text-[var(--text-muted)]">
              Minúsculas, números, guiones o guiones bajos; sin espacios.
            </span>
          </div>
          <label className="text-sm sm:col-span-2">
            Descripción
            <textarea name="description" rows={2} className={INPUT} />
          </label>
          {PROMPTS.map((field) => (
            <div key={field.key} className="text-sm sm:col-span-2">
              <label htmlFor={`new-${field.key}`}>{field.label}</label>
              <textarea
                id={`new-${field.key}`}
                name={field.key}
                required
                rows={3}
                aria-describedby={`${field.key}-help`}
                className={INPUT}
              />
              <span
                id={`${field.key}-help`}
                className="mt-1 block text-xs text-[var(--text-muted)]"
              >
                {field.help}
              </span>
            </div>
          ))}
          <label className="text-sm">
            Mensaje no autorizado
            <textarea name="unauthorized_message" rows={2} className={INPUT} />
          </label>
          <label className="text-sm">
            Mensaje ante error
            <textarea name="error_message" rows={2} className={INPUT} />
          </label>
          <label className="text-sm">
            Retención del historial (días)
            <input
              name="retention_days"
              type="number"
              min={1}
              max={365}
              required
              defaultValue={30}
              className={INPUT}
            />
          </label>
        </fieldset>
        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <button
            disabled={saving}
            type="submit"
            className="inline-flex min-h-11 items-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {saving && <LoaderCircle size={16} className="animate-spin" />}Crear y configurar
          </button>
          <button
            disabled={saving}
            type="button"
            onClick={close}
            className="min-h-11 rounded border border-[var(--border-color)] px-4 py-2 text-sm"
          >
            Cancelar
          </button>
        </div>
      </form>
    </section>
  );
}

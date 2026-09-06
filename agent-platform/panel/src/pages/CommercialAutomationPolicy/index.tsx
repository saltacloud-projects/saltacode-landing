import { CalendarClock, CircleAlert, LoaderCircle, Save, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { getCommercialAutomationPolicy, updateCommercialAutomationPolicy } from "./api";
import type { CommercialAutomationPolicy, FollowUpKind } from "./types";

const INPUT =
  "mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60";

const FOLLOW_UP_KINDS: Array<{
  value: FollowUpKind;
  label: string;
  description: string;
}> = [
  {
    value: "commercial_follow_up",
    label: "Seguimiento comercial",
    description: "Continuidad de una oportunidad con consentimiento vigente.",
  },
  {
    value: "meeting_coordination",
    label: "Coordinación de reunión",
    description: "Mensajes para acordar una reunión; no confirma agenda externa.",
  },
  {
    value: "proposal_reminder",
    label: "Recordatorio de propuesta",
    description: "Sólo aplica a propuestas emitidas por una fuente autoritativa.",
  },
];

const COMMON_TIMEZONES = [
  "America/Argentina/Salta",
  "America/Argentina/Buenos_Aires",
  "America/Santiago",
  "America/Lima",
  "America/Bogota",
  "America/Mexico_City",
  "America/New_York",
  "Europe/Madrid",
  "UTC",
];

function safePolicyError(cause: unknown): string {
  if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
    return "No se pudo acceder a la política de este agente.";
  }
  return "No se pudo completar la operación. Volvé a intentarlo.";
}

function validTimezone(value: string): boolean {
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

function timeInputValue(value: string | null): string {
  return value?.slice(0, 5) ?? "";
}

export default function CommercialAutomationPolicyPage() {
  const { selectedAgent } = useAgentWorkspace();
  const { user } = useAuth();
  const canManage = hasPermission(user, PERMISSIONS.OPPORTUNITIES_MANAGE);
  const [draft, setDraft] = useState<CommercialAutomationPolicy | null>(null);
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const feedbackRef = useRef<HTMLParagraphElement>(null);

  const load = useCallback(async (agentId: string) => {
    setLoading(true);
    setError("");
    try {
      const policy = await getCommercialAutomationPolicy(agentId);
      setDraft(policy);
      setQuietHoursEnabled(Boolean(policy.quiet_hours_start && policy.quiet_hours_end));
    } catch (cause) {
      setDraft(null);
      setError(safePolicyError(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setDraft(null);
    setNotice("");
    const agentId = selectedAgent?.id;
    if (agentId) void load(agentId);
  }, [selectedAgent?.id, load]);

  useEffect(() => {
    if (error || notice) feedbackRef.current?.focus();
  }, [error, notice]);

  if (!selectedAgent) return null;

  const updateDraft = <Key extends keyof CommercialAutomationPolicy>(
    key: Key,
    value: CommercialAutomationPolicy[Key],
  ) => setDraft((current) => (current ? { ...current, [key]: value } : current));

  const toggleKind = (kind: FollowUpKind, checked: boolean) => {
    setDraft((current) => {
      if (!current) return current;
      const allowed = new Set(current.allowed_kinds);
      if (checked) allowed.add(kind);
      else allowed.delete(kind);
      return { ...current, allowed_kinds: Array.from(allowed) };
    });
  };

  const toggleQuietHours = (checked: boolean) => {
    setQuietHoursEnabled(checked);
    setDraft((current) =>
      current
        ? {
            ...current,
            quiet_hours_start: checked ? current.quiet_hours_start || "22:00" : null,
            quiet_hours_end: checked ? current.quiet_hours_end || "08:00" : null,
          }
        : current,
    );
  };

  const save = async () => {
    if (!draft || !canManage) return;
    setError("");
    setNotice("");
    if (!validTimezone(draft.timezone)) {
      setError("Ingresá una zona horaria IANA válida.");
      return;
    }
    if (
      quietHoursEnabled &&
      (!draft.quiet_hours_start ||
        !draft.quiet_hours_end ||
        draft.quiet_hours_start === draft.quiet_hours_end)
    ) {
      setError("El horario de silencio necesita un inicio y un fin diferentes.");
      return;
    }

    setSaving(true);
    try {
      const updated = await updateCommercialAutomationPolicy(selectedAgent.id, {
        expected_version: draft.version,
        is_enabled: draft.is_enabled,
        allowed_kinds: draft.allowed_kinds,
        timezone: draft.timezone.trim(),
        quiet_hours_start: quietHoursEnabled ? draft.quiet_hours_start : null,
        quiet_hours_end: quietHoursEnabled ? draft.quiet_hours_end : null,
        min_interval_seconds: draft.min_interval_seconds,
        max_attempts: draft.max_attempts,
        max_daily_tasks: draft.max_daily_tasks,
        max_pending_tasks: draft.max_pending_tasks,
      });
      setDraft(updated);
      setQuietHoursEnabled(Boolean(updated.quiet_hours_start && updated.quiet_hours_end));
      setNotice("Política comercial guardada.");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await load(selectedAgent.id);
        setNotice(
          "La política cambió en otra sesión. Recargamos la última versión; revisala antes de volver a guardar.",
        );
      } else {
        setError(safePolicyError(cause));
      }
    } finally {
      setSaving(false);
    }
  };

  const controlsDisabled = loading || saving || !canManage || !draft;

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <CalendarClock className="text-[var(--accent)]" size={23} aria-hidden="true" />
        <div>
          <h2 className="text-xl font-semibold">Política comercial de {selectedAgent.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            Límites persistidos para seguimientos automáticos de este agente.
          </p>
        </div>
        {canManage && draft && (
          <button
            type="submit"
            form="commercial-automation-policy-form"
            disabled={saving}
            className="ml-auto inline-flex min-h-10 items-center justify-center gap-2 rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />}
            {saving ? "Guardando…" : "Guardar política"}
          </button>
        )}
      </header>

      <div
        className="rounded-lg border border-amber-500/35 bg-amber-500/5 p-4 text-sm text-[var(--text-secondary)]"
        role="note"
      >
        <p className="flex items-start gap-2 font-medium text-[var(--text-primary)]">
          <CircleAlert className="mt-0.5 shrink-0 text-amber-400" size={17} aria-hidden="true" />
          Habilitar esta política no prueba que la automatización esté lista.
        </p>
        <p className="mt-2">
          Proveedor, modelo, ruta de canal, identidad y consentimiento se verifican por separado.
          WhatsApp y email externos permanecen bloqueados hasta completar sus integraciones.
        </p>
      </div>

      {!canManage && (
        <p className="rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3 text-sm text-[var(--text-secondary)]">
          Tenés acceso de solo lectura. Para editar se requiere el permiso de gestión de
          oportunidades.
        </p>
      )}
      {error && (
        <p
          ref={feedbackRef}
          tabIndex={-1}
          role="alert"
          className="rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)] outline-none"
        >
          {error}
        </p>
      )}
      {notice && (
        <p
          ref={feedbackRef}
          tabIndex={-1}
          role="status"
          className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400 outline-none"
        >
          {notice}
        </p>
      )}
      {loading && (
        <p className="flex items-center gap-2 text-sm text-[var(--text-muted)]" role="status">
          <LoaderCircle className="animate-spin" size={16} /> Cargando política…
        </p>
      )}

      {draft && (
        <form
          id="commercial-automation-policy-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
          className="space-y-5"
        >
          <section className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 sm:p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="font-semibold">Ejecución automática</h3>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  El estado inicial y cualquier ausencia de configuración son fail-closed.
                </p>
              </div>
              <label className="inline-flex min-h-11 items-center gap-3 rounded border border-[var(--border-color)] px-3 py-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={draft.is_enabled}
                  disabled={controlsDisabled}
                  onChange={(event) => updateDraft("is_enabled", event.target.checked)}
                />
                Automatización habilitada
              </label>
            </div>
            <p className="mt-3 flex items-center gap-2 text-sm" role="status">
              <ShieldCheck
                size={17}
                className={draft.is_enabled ? "text-amber-400" : "text-emerald-400"}
                aria-hidden="true"
              />
              {draft.is_enabled
                ? "Habilitada por política; disponibilidad operativa no verificada."
                : "Deshabilitada: no autoriza ejecuciones automáticas."}
            </p>
          </section>

          <fieldset
            disabled={controlsDisabled}
            className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 sm:p-5"
          >
            <legend className="px-1 font-semibold">Acciones permitidas</legend>
            <p className="mb-4 text-sm text-[var(--text-secondary)]">
              Una acción no seleccionada permanece bloqueada aunque la política esté habilitada.
            </p>
            <div className="grid gap-3 md:grid-cols-3">
              {FOLLOW_UP_KINDS.map((kind) => (
                <label
                  key={kind.value}
                  className="flex min-w-0 items-start gap-3 rounded border border-[var(--border-color)] p-3"
                >
                  <input
                    type="checkbox"
                    className="mt-1 shrink-0"
                    aria-label={`Permitir ${kind.label.toLocaleLowerCase("es")}`}
                    checked={draft.allowed_kinds.includes(kind.value)}
                    onChange={(event) => toggleKind(kind.value, event.target.checked)}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{kind.label}</span>
                    <span className="mt-1 block text-xs text-[var(--text-muted)]">
                      {kind.description}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <section className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 sm:p-5">
            <h3 className="font-semibold">Zona horaria y silencio</h3>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="text-xs text-[var(--text-muted)]">
                Zona horaria IANA
                <input
                  type="text"
                  list="commercial-timezones"
                  value={draft.timezone}
                  disabled={controlsDisabled}
                  maxLength={64}
                  autoComplete="off"
                  required
                  className={INPUT}
                  onChange={(event) => updateDraft("timezone", event.target.value)}
                />
                <datalist id="commercial-timezones">
                  {COMMON_TIMEZONES.map((timezone) => (
                    <option key={timezone} value={timezone} />
                  ))}
                </datalist>
              </label>
              <label className="flex min-h-11 items-center gap-3 self-end rounded border border-[var(--border-color)] px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  checked={quietHoursEnabled}
                  disabled={controlsDisabled}
                  onChange={(event) => toggleQuietHours(event.target.checked)}
                />
                Aplicar horario de silencio
              </label>
              {quietHoursEnabled && (
                <>
                  <label className="text-xs text-[var(--text-muted)]">
                    Inicio del silencio
                    <input
                      type="time"
                      value={timeInputValue(draft.quiet_hours_start)}
                      disabled={controlsDisabled}
                      required
                      className={INPUT}
                      onChange={(event) => updateDraft("quiet_hours_start", event.target.value)}
                    />
                  </label>
                  <label className="text-xs text-[var(--text-muted)]">
                    Fin del silencio
                    <input
                      type="time"
                      value={timeInputValue(draft.quiet_hours_end)}
                      disabled={controlsDisabled}
                      required
                      className={INPUT}
                      onChange={(event) => updateDraft("quiet_hours_end", event.target.value)}
                    />
                  </label>
                </>
              )}
            </div>
          </section>

          <fieldset
            disabled={controlsDisabled}
            className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 sm:p-5"
          >
            <legend className="px-1 font-semibold">Límites de ejecución</legend>
            <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <label className="text-xs text-[var(--text-muted)]">
                Intervalo mínimo (segundos)
                <input
                  type="number"
                  min={0}
                  max={2_678_400}
                  required
                  value={draft.min_interval_seconds}
                  className={INPUT}
                  onChange={(event) =>
                    updateDraft("min_interval_seconds", Number(event.target.value))
                  }
                />
              </label>
              <label className="text-xs text-[var(--text-muted)]">
                Intentos máximos
                <input
                  type="number"
                  min={1}
                  max={20}
                  required
                  value={draft.max_attempts}
                  className={INPUT}
                  onChange={(event) => updateDraft("max_attempts", Number(event.target.value))}
                />
              </label>
              <label className="text-xs text-[var(--text-muted)]">
                Tareas diarias máximas
                <input
                  type="number"
                  min={1}
                  max={10_000}
                  required
                  value={draft.max_daily_tasks}
                  className={INPUT}
                  onChange={(event) => updateDraft("max_daily_tasks", Number(event.target.value))}
                />
              </label>
              <label className="text-xs text-[var(--text-muted)]">
                Tareas pendientes máximas
                <input
                  type="number"
                  min={1}
                  max={100_000}
                  required
                  value={draft.max_pending_tasks}
                  className={INPUT}
                  onChange={(event) => updateDraft("max_pending_tasks", Number(event.target.value))}
                />
              </label>
            </div>
          </fieldset>

          <footer className="flex flex-col gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] p-4 text-sm sm:flex-row sm:items-center sm:justify-between">
            <span className="text-[var(--text-muted)]">Versión de política {draft.version}</span>
            {canManage && (
              <button
                type="submit"
                disabled={saving}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded bg-[var(--accent)] px-4 py-2 font-medium text-white disabled:opacity-50"
              >
                {saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />}
                {saving ? "Guardando…" : "Guardar política"}
              </button>
            )}
          </footer>
        </form>
      )}
    </div>
  );
}

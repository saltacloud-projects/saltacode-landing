import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { lastMessageBounds } from "../../inbox/last-message-range";
import type { InboxFilters, InboxOperator, LastMessagePeriod } from "../../inbox/types";

interface InboxFiltersProps {
  filters: InboxFilters;
  operators: InboxOperator[];
  onChange: (filters: InboxFilters) => void;
}

export function InboxSearch({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const update = useRef(onChange);
  update.current = onChange;
  useEffect(() => {
    if (draft.trim() === value) return;
    const timer = window.setTimeout(() => update.current(draft.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [draft, value]);
  return (
    <div className="relative">
      <label htmlFor="inbox-search" className="sr-only">
        Buscar por nombre o identificador de visitante
      </label>
      <Search
        aria-hidden="true"
        size={17}
        className="pointer-events-none absolute left-3 top-3.5 text-[var(--text-secondary)]"
      />
      <input
        id="inbox-search"
        type="search"
        autoComplete="off"
        maxLength={120}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="Nombre o identificador de visitante"
        aria-describedby="inbox-search-help"
        className="min-h-11 w-full min-w-0 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] py-2 pl-10 pr-10 text-sm outline-none focus:border-[var(--accent)]"
      />
      {draft && (
        <button
          type="button"
          onClick={() => {
            setDraft("");
            update.current("");
          }}
          aria-label="Limpiar búsqueda"
          className="absolute right-0 top-0 grid h-11 w-11 place-items-center rounded-xl text-[var(--text-secondary)]"
        >
          <X size={16} />
        </button>
      )}
      <p id="inbox-search-help" className="sr-only">
        Busca el nombre visible o el identificador del visitante. No busca en mensajes, correos ni
        teléfonos.
      </p>
    </div>
  );
}

export function InboxFiltersForm({ filters, operators, onChange }: InboxFiltersProps) {
  const [period, setPeriod] = useState<LastMessagePeriod>(filters.lastMessagePeriod ?? "all");
  const [from, setFrom] = useState(filters.lastMessageFrom ?? "");
  const [to, setTo] = useState(filters.lastMessageTo ?? "");
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  let dateError = "";
  if (period === "custom") {
    try {
      lastMessageBounds({
        ...filters,
        lastMessagePeriod: "custom",
        lastMessageFrom: from,
        lastMessageTo: to,
      });
    } catch (error) {
      dateError = error instanceof Error ? error.message : "Revisá las fechas.";
    }
  }
  const update = (key: keyof InboxFilters, value: string) => onChange({ ...filters, [key]: value });
  return (
    <section aria-label="Filtros del inbox" className="space-y-3">
      <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <FilterSelect
          label="Canal"
          value={filters.channel}
          onChange={(value) => update("channel", value)}
          options={[
            ["", "Todos"],
            ["web", "Web"],
            ["whatsapp", "WhatsApp"],
            ["instagram", "Instagram"],
            ["facebook", "Facebook"],
            ["email", "Email"],
          ]}
        />
        <FilterSelect
          label="Control"
          value={filters.controlMode}
          onChange={(value) => update("controlMode", value)}
          options={[
            ["", "Todos"],
            ["automated", "Automático"],
            ["paused", "Pausado"],
            ["human", "Manual"],
            ["closed", "Cerrado"],
          ]}
        />
      </div>
      <FilterSelect
        label="Responsable"
        value={filters.owner}
        onChange={(value) => update("owner", value)}
        options={[
          ["", "Todos"],
          ["me", "Asignadas a mí"],
          ["unassigned", "Sin asignar"],
          ...operators.map(
            (operator) => [`operator:${operator.id}`, operator.name] satisfies [string, string],
          ),
        ]}
      />
      <FilterSelect
        label="Último mensaje"
        value={period}
        onChange={(value) => {
          setPeriod(value as LastMessagePeriod);
          if (value !== "custom")
            onChange({
              ...filters,
              lastMessagePeriod: value as LastMessagePeriod,
              lastMessageFrom: "",
              lastMessageTo: "",
            });
        }}
        options={[
          ["all", "Cualquier fecha"],
          ["today", "Hoy"],
          ["7d", "Últimos 7 días"],
          ["30d", "Últimos 30 días"],
          ["custom", "Personalizado"],
        ]}
      />
      {period === "custom" && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!dateError)
              onChange({
                ...filters,
                lastMessagePeriod: "custom",
                lastMessageFrom: from,
                lastMessageTo: to,
              });
          }}
          className="space-y-2"
        >
          <div className="grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <label className="min-w-0 text-xs text-[var(--text-secondary)]">
              Desde
              <input
                type="date"
                required
                value={from}
                onChange={(event) => setFrom(event.target.value)}
                aria-describedby="inbox-date-help inbox-date-error"
                className="mt-1 block min-h-11 w-full min-w-0 max-w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 text-sm text-[var(--text-primary)]"
              />
            </label>
            <label className="min-w-0 text-xs text-[var(--text-secondary)]">
              Hasta
              <input
                type="date"
                required
                value={to}
                onChange={(event) => setTo(event.target.value)}
                aria-describedby="inbox-date-help inbox-date-error"
                className="mt-1 block min-h-11 w-full min-w-0 max-w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 text-sm text-[var(--text-primary)]"
              />
            </label>
          </div>
          <p id="inbox-date-error" className="text-xs text-amber-300" aria-live="polite">
            {dateError || "Ambas fechas incluidas. Confirmá para aplicar el rango."}
          </p>
          <button
            type="submit"
            disabled={Boolean(dateError)}
            className="min-h-11 rounded-lg border border-[var(--accent)] px-3 text-xs text-[var(--accent-hover)] disabled:opacity-40"
          >
            Aplicar fechas
          </button>
        </form>
      )}
      <p id="inbox-date-help" className="text-[11px] leading-relaxed text-[var(--text-secondary)]">
        Zona horaria: {timezone}. Días calendario completos; los últimos 7 y 30 días incluyen hoy.
        Se filtra el último mensaje, no la creación ni los cambios de control.
      </p>
    </section>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <label className="block min-w-0 text-xs text-[var(--text-secondary)]">
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 min-h-11 w-full min-w-0 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 py-2 text-sm text-[var(--text-primary)]"
      >
        {options.map(([optionValue, text]) => (
          <option key={optionValue || "all"} value={optionValue}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

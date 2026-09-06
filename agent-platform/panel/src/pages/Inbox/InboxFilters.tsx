import type { InboxFilters, InboxOperator } from "../../inbox/types";

interface InboxFiltersProps {
  filters: InboxFilters;
  operators: InboxOperator[];
  onChange: (filters: InboxFilters) => void;
}

export function InboxFiltersForm({ filters, operators, onChange }: InboxFiltersProps) {
  const update = (key: keyof InboxFilters, value: string) => {
    onChange({ ...filters, [key]: value });
  };

  return (
    <section
      aria-label="Filtros del inbox"
      className="mb-4 grid gap-2 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3 sm:grid-cols-2 xl:grid-cols-5"
    >
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
        label="Estado"
        value={filters.status}
        onChange={(value) => update("status", value)}
        options={[
          ["", "Todos"],
          ["active", "Activas"],
          ["closed", "Cerradas"],
        ]}
      />
      <FilterSelect
        label="Actividad"
        value={filters.updatedWithinHours}
        onChange={(value) => update("updatedWithinHours", value)}
        options={[
          ["", "Todo el historial"],
          ["24", "Últimas 24 horas"],
          ["168", "Últimos 7 días"],
          ["720", "Últimos 30 días"],
        ]}
      />
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
    <label className="text-xs text-[var(--text-muted)]">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 py-2 text-sm text-[var(--text-primary)]"
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

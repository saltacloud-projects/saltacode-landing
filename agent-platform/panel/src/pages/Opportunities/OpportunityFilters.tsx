import { STAGE_LABELS } from "./presentation";
import type { CommercialOperator, OpportunityFilters } from "./types";

interface Props {
  filters: OpportunityFilters;
  operators: CommercialOperator[];
  onChange: (filters: OpportunityFilters) => void;
}

export function OpportunityFiltersForm({ filters, operators, onChange }: Props) {
  return (
    <section
      aria-label="Filtros de oportunidades"
      className="mb-4 grid gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3 sm:grid-cols-3"
    >
      <label className="text-xs text-[var(--text-muted)]">
        Buscar
        <input
          type="search"
          value={filters.search}
          onChange={(event) => onChange({ ...filters, search: event.target.value })}
          placeholder="Título, contacto o empresa"
          className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)]"
        />
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        Etapa
        <select
          value={filters.stage}
          onChange={(event) => onChange({ ...filters, stage: event.target.value })}
          className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)]"
        >
          <option value="">Todas</option>
          {Object.entries(STAGE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        Responsable
        <select
          value={filters.owner}
          onChange={(event) => onChange({ ...filters, owner: event.target.value })}
          className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)]"
        >
          <option value="">Todos</option>
          <option value="me">Asignadas a mí</option>
          <option value="unassigned">Sin operador</option>
          {operators.map((operator) => (
            <option key={operator.id} value={`operator:${operator.id}`}>
              {operator.name}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

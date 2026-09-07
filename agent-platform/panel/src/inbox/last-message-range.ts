import type { InboxFilters } from "./types";

function localDate(value: string | undefined): Date {
  const parts = value?.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!parts) throw new Error("Completá las fechas desde y hasta.");
  const [, year, month, day] = parts.map(Number);
  const date = new Date(0);
  date.setFullYear(year, month - 1, day);
  date.setHours(0, 0, 0, 0);
  if (
    year < 1 ||
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  )
    throw new Error("La fecha indicada no es válida.");
  return date;
}

/** Inclusive local calendar dates become a half-open UTC interval, including DST transitions. */
export function lastMessageBounds(filters: InboxFilters, now = new Date()) {
  const period = filters.lastMessagePeriod ?? "all";
  if (period === "all") return null;
  const from = period === "custom" ? localDate(filters.lastMessageFrom) : new Date(now);
  const end = period === "custom" ? localDate(filters.lastMessageTo) : new Date(now);
  from.setHours(0, 0, 0, 0);
  end.setHours(0, 0, 0, 0);
  if (period === "7d") from.setDate(from.getDate() - 6);
  if (period === "30d") from.setDate(from.getDate() - 29);
  if (from > end) throw new Error("La fecha desde no puede ser posterior a la fecha hasta.");
  end.setDate(end.getDate() + 1);
  return { from: from.toISOString(), before: end.toISOString() };
}

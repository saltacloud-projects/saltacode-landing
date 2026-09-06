import type { ChannelAdapterCatalogEntry, ChannelKind, ChannelReadiness } from "./types";

export const CHANNEL_LABELS: Record<ChannelKind, string> = {
  web: "Web",
  whatsapp: "WhatsApp",
  email: "Email",
  instagram_dm: "Instagram DM",
  facebook_messenger: "Facebook Messenger",
};

export const READINESS_LABELS: Record<ChannelReadiness, string> = {
  disabled: "Deshabilitada",
  not_implemented: "Integración pendiente",
  configuration_required: "Requiere configuración",
  configured_unverified: "Configurada sin tráfico verificado",
  traffic_observed: "Tráfico verificado",
  degraded: "Atención requerida",
};

const BLOCKING_MESSAGES: Record<string, string> = {
  adapter_not_implemented: "El adaptador todavía no está implementado.",
  blocked_external: "Requiere habilitación y credenciales del proveedor externo.",
  connection_disabled: "La conexión está deshabilitada.",
  credentials_missing: "Faltan credenciales write-only.",
  provider_required: "Todavía falta seleccionar e integrar un proveedor.",
  route_inactive: "Las rutas vinculadas están inactivas.",
  route_inconsistent: "La configuración de rutas es inconsistente y requiere revisión.",
  route_missing: "Todavía no está vinculada a una ruta de agente.",
  settings_invalid: "La configuración visible es incompleta o inválida.",
  traffic_not_observed: "Aún no hay tráfico real que confirme su funcionamiento.",
};

export function channelLabel(channel: ChannelKind): string {
  return CHANNEL_LABELS[channel];
}

export function blockingMessage(code: string): string {
  return BLOCKING_MESSAGES[code] ?? `Bloqueo operativo: ${code}`;
}

export function implementedAdapters(
  adapters: ChannelAdapterCatalogEntry[],
): ChannelAdapterCatalogEntry[] {
  return adapters.filter((adapter) => adapter.adapter_implemented);
}

export function readinessTone(readiness: ChannelReadiness): string {
  switch (readiness) {
    case "traffic_observed":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-400";
    case "configured_unverified":
      return "border-sky-500/30 bg-sky-500/10 text-sky-300";
    case "configuration_required":
    case "degraded":
      return "border-amber-500/30 bg-amber-500/10 text-amber-300";
    case "disabled":
    case "not_implemented":
      return "border-[var(--border-color)] bg-[var(--bg-hover)] text-[var(--text-muted)]";
  }
}

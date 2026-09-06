export type HandoffTrigger = "quote_requested" | "manual_escalation";

export interface HandoffRoute {
  id: string;
  source_agent_id: string;
  target_agent_id: string;
  trigger: HandoffTrigger;
  is_active: boolean;
  version?: number;
  control_version?: number;
  created_at: string;
  updated_at: string;
}

export function routeVersion(route: HandoffRoute): number {
  return route.version ?? route.control_version ?? 0;
}

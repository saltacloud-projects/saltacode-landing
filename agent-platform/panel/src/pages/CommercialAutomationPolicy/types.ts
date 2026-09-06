export type FollowUpKind = "commercial_follow_up" | "meeting_coordination" | "proposal_reminder";

export interface CommercialAutomationPolicy {
  agent_id: string;
  is_enabled: boolean;
  allowed_kinds: FollowUpKind[];
  timezone: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  min_interval_seconds: number;
  max_attempts: number;
  max_daily_tasks: number;
  max_pending_tasks: number;
  version: number;
}

export interface CommercialAutomationPolicyUpdate {
  expected_version: number;
  is_enabled: boolean;
  allowed_kinds: FollowUpKind[];
  timezone: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  min_interval_seconds: number;
  max_attempts: number;
  max_daily_tasks: number;
  max_pending_tasks: number;
}

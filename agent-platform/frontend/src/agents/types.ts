export interface AgentProfile {
  id: string;
  name: string;
  slug: string;
  version: number;
  is_active: boolean;
  is_public: boolean;
  retention_days: number;
  description: string | null;
  prompt_identity: string;
  prompt_domain: string;
  prompt_guardrails: string;
  unauthorized_message: string;
  error_message: string;
  created_at: string;
  updated_at: string;
}

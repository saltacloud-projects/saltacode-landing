export interface ProviderConnection {
  id: string;
  name: string;
  slug: string;
  provider_type: "openai";
  base_url: string | null;
  settings: Record<string, unknown>;
  has_credentials: boolean;
  is_active: boolean;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

export type ChannelKind = "web" | "whatsapp" | "email" | "instagram_dm" | "facebook_messenger";

export type ChannelAdapterKey =
  | "web_builtin"
  | "meta_whatsapp_cloud"
  | "email"
  | "meta_instagram_graph"
  | "meta_messenger_graph";

export type ChannelReadiness =
  | "disabled"
  | "not_implemented"
  | "configuration_required"
  | "configured_unverified"
  | "traffic_observed"
  | "degraded";

export interface ChannelAdapterCatalogEntry {
  adapter_key: ChannelAdapterKey;
  channel: ChannelKind;
  implementation_status: "implemented" | "planned";
  adapter_implemented: boolean;
  capabilities: string[];
  credentials_required: boolean;
  blocking_codes: string[];
}

export interface ChannelConnectionReadiness {
  connection_id: string;
  name: string;
  slug: string;
  channel: ChannelKind;
  adapter_key: ChannelAdapterKey;
  version: number;
  is_active: boolean;
  readiness: ChannelReadiness;
  adapter_implemented: boolean;
  settings_valid: boolean;
  credentials_state: "not_required" | "missing" | "stored_unverified";
  routing_state: "not_configured" | "inactive" | "active" | "inconsistent";
  active_route_count: number;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  blocking_codes: string[];
}

export interface ChannelCatalog {
  adapters: ChannelAdapterCatalogEntry[];
  connections: ChannelConnectionReadiness[];
}

export interface ChannelConnection {
  id: string;
  name: string;
  slug: string;
  channel: ChannelKind;
  adapter_key: ChannelAdapterKey;
  version: number;
  external_account_id: string | null;
  settings: Record<string, unknown>;
  has_credentials: boolean;
  is_active: boolean;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRuntime {
  id: string;
  agent_id: string;
  provider_connection_id: string | null;
  chat_model: string;
  transcription_model: string;
  temperature: number;
  max_output_tokens: number;
  max_iterations: number;
  max_tool_calls: number;
  loop_timeout_seconds: number;
  tool_timeout_seconds: number;
  tool_result_max_chars: number;
  history_message_limit: number;
  history_cache_ttl_seconds: number;
  summary_enabled: boolean;
  summary_trigger_messages: number;
  summary_max_chars: number;
  rag_enabled: boolean;
  rag_retrieval_top_k: number;
  rag_min_relevance_score: number;
  rag_vector_weight: number;
  rag_lexical_weight: number;
  provider_ready: boolean;
}

export interface AgentRoute {
  id: string;
  agent_id: string;
  channel: ChannelKind;
  version: number;
  route_key: string;
  channel_connection_id: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

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

export type ChannelKind = "web" | "whatsapp";

export interface ChannelConnection {
  id: string;
  name: string;
  slug: string;
  channel: ChannelKind;
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
  route_key: string;
  channel_connection_id: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

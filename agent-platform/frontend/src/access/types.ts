export interface GlobalAuthorizedIdentity {
  id: string;
  phone_number: string;
  name: string | null;
  notes: string | null;
  is_active: boolean;
  has_all_area_access: boolean;
  area_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface AgentAuthorizedUser extends GlobalAuthorizedIdentity {
  agent_id: string;
}

export interface AgentDocumentArea {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  is_general: boolean;
  is_active: boolean;
}

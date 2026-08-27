import type { AdminUser } from "./AuthContext";

export const PERMISSIONS = {
  ALL: "*",
  DASHBOARD_READ: "dashboard.read",
  PROFILES_READ: "profiles.read",
  KNOWLEDGE_READ: "knowledge.read",
  TOOLS_READ: "tools.read",
  TOOLS_MANAGE: "tools.manage",
  SOURCES_READ: "sources.read",
  SOURCES_MANAGE: "sources.manage",
  USERS_READ: "users.read",
  CONVERSATIONS_READ: "conversations.read",
  CONVERSATIONS_MANAGE: "conversations.manage",
  AUDIT_READ: "audit.read",
  PROMPTLAB_USE: "promptlab.use",
  DOCUMENTS_READ: "documents.read",
  DOCUMENTS_MANAGE: "documents.manage",
  DOCUMENTS_TAXONOMY: "documents.taxonomy",
  DOCUMENTS_SETTINGS: "documents.settings",
  PANEL_USERS_MANAGE: "panel_users.manage",
} as const;

export function hasPermission(user: AdminUser | null, permission: string): boolean {
  return Boolean(user?.permissions?.includes(PERMISSIONS.ALL) || user?.permissions?.includes(permission));
}

export function defaultPanelPath(user: AdminUser | null): string {
  if (hasPermission(user, PERMISSIONS.DASHBOARD_READ)) return "/";
  if (hasPermission(user, PERMISSIONS.DOCUMENTS_READ)) return "/documents";
  if (hasPermission(user, PERMISSIONS.PROFILES_READ)) return "/profiles";
  if (hasPermission(user, PERMISSIONS.KNOWLEDGE_READ)) return "/knowledge";
  if (hasPermission(user, PERMISSIONS.TOOLS_READ)) return "/tools";
  if (hasPermission(user, PERMISSIONS.SOURCES_READ)) return "/sources";
  if (hasPermission(user, PERMISSIONS.USERS_READ)) return "/users";
  if (hasPermission(user, PERMISSIONS.CONVERSATIONS_READ)) return "/conversations";
  if (hasPermission(user, PERMISSIONS.AUDIT_READ)) return "/audit";
  if (hasPermission(user, PERMISSIONS.PROMPTLAB_USE)) return "/promptlab";
  if (hasPermission(user, PERMISSIONS.PANEL_USERS_MANAGE)) return "/panel-users";
  return "/login";
}

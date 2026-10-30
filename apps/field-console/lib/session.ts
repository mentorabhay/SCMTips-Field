/**
 * The console's field session: the field token from POST /v1/auth/exchange, kept in sessionStorage
 * (cleared when the tab closes) and mirrored in memory. Nothing here is a credential the console owns:
 * the token is issued by field-api and expires with it.
 */
export interface FieldSession {
  accessToken: string;
  /** Epoch ms after which the token is no longer accepted. */
  expiresAt: number;
  principalId: string;
  tenantId: string;
  roles: string[];
  permissions: string[];
  siteIds: string[];
}

export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export const SESSION_KEY = "scmtips-field.console.session";

/** field.* and * grant everything, as field_api.auth.permissions.has_permission does. */
export function hasPermission(perms: readonly string[], required: string): boolean {
  return perms.includes("*") || perms.includes("field.*") || perms.includes(required);
}

export function isExpired(s: FieldSession, nowMs: number): boolean {
  return nowMs >= s.expiresAt;
}

export function parseSession(raw: string | null): FieldSession | null {
  if (!raw) return null;
  try {
    const v: unknown = JSON.parse(raw);
    if (!v || typeof v !== "object") return null;
    const o = v as Record<string, unknown>;
    const strs = (x: unknown) => (Array.isArray(x) && x.every((e) => typeof e === "string") ? (x as string[]) : null);
    const roles = strs(o.roles);
    const permissions = strs(o.permissions);
    const siteIds = strs(o.siteIds);
    if (
      typeof o.accessToken !== "string" || !o.accessToken ||
      typeof o.expiresAt !== "number" ||
      typeof o.principalId !== "string" ||
      typeof o.tenantId !== "string" ||
      !roles || !permissions || !siteIds
    ) {
      return null;
    }
    return {
      accessToken: o.accessToken, expiresAt: o.expiresAt, principalId: o.principalId,
      tenantId: o.tenantId, roles, permissions, siteIds,
    };
  } catch {
    return null;
  }
}

/** A small store with change listeners, so the shell re-renders on sign-in and sign-out. */
export class SessionStore {
  private current: FieldSession | null;
  private listeners = new Set<() => void>();

  constructor(private readonly storage: KeyValueStore | null) {
    this.current = storage ? parseSession(storage.getItem(SESSION_KEY)) : null;
  }

  get(): FieldSession | null {
    return this.current;
  }

  set(s: FieldSession): void {
    this.current = s;
    this.storage?.setItem(SESSION_KEY, JSON.stringify(s));
    this.emit();
  }

  clear(): void {
    this.current = null;
    this.storage?.removeItem(SESSION_KEY);
    this.emit();
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }
}

/** Human labels for the roles the dev sign-in offers and field-api knows (ROLE_PERMISSIONS). */
export const ROLE_LABELS: Record<string, string> = {
  "field.supervisor": "Supervisor",
  "inventory.controller": "Inventory controller",
  "field.admin": "Administrator",
  "field.operator": "Operator",
  "field.technician": "Technician",
  "field.viewer": "Viewer",
  "field.integration": "Integration",
};

export function roleLabel(roles: readonly string[]): string {
  const known = roles.map((r) => ROLE_LABELS[r]).filter((x): x is string => Boolean(x));
  return known.length ? known.join(", ") : roles.join(", ") || "No Field role";
}

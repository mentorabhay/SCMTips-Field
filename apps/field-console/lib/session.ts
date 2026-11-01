/**
 * The console's field session: the field token from POST /v1/auth/exchange, kept in sessionStorage
 * (cleared when the tab closes) and mirrored in memory. Nothing here is a credential the console owns:
 * the token is issued by field-api and expires with it.
 *
 * Core sign-in (M5-J01, `transport: "cookie"`): the token is NOT here. It lives in an httpOnly cookie set by the
 * console's server (app/api/console-auth), and `accessToken` is "". sessionStorage then holds only who is signed
 * in, the roles and permissions, and when the cookie ends.
 */
export interface FieldSession {
  /** The field token (development sign-in); "" for a cookie session. */
  accessToken: string;
  /** Epoch ms after which the token is no longer accepted. */
  expiresAt: number;
  principalId: string;
  tenantId: string;
  roles: string[];
  permissions: string[];
  siteIds: string[];
  /** "cookie": core sign-in, the token is in an httpOnly cookie (M5-J01). Absent: the development sign-in. */
  transport?: "cookie";
  /** The core user's name or e-mail, shown in the shell (core sign-in). */
  displayName?: string;
  /** Epoch ms when the core sign-in ends; the field token is refreshed until then (core sign-in). */
  signInEndsAt?: number;
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
    const cookie = o.transport === "cookie";
    if (
      typeof o.accessToken !== "string" || (!o.accessToken && !cookie) || (cookie && o.accessToken !== "") ||
      typeof o.expiresAt !== "number" ||
      typeof o.principalId !== "string" ||
      typeof o.tenantId !== "string" ||
      !roles || !permissions || !siteIds
    ) {
      return null;
    }
    const base: FieldSession = {
      accessToken: o.accessToken, expiresAt: o.expiresAt, principalId: o.principalId,
      tenantId: o.tenantId, roles, permissions, siteIds,
    };
    if (!cookie) return base;
    return {
      ...base,
      transport: "cookie",
      ...(typeof o.displayName === "string" ? { displayName: o.displayName } : {}),
      ...(typeof o.signInEndsAt === "number" ? { signInEndsAt: o.signInEndsAt } : {}),
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

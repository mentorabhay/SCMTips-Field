/**
 * Development sign-in (T1.075 interim): fake-core issues a core token for a chosen role, field-api
 * exchanges it (POST /v1/auth/exchange) for the field token the console keeps for the tab.
 * Only offered when NEXT_PUBLIC_DEV_SIGNIN=1. The real path (core SSO redirect) is not built.
 */
import { ApiError, MSG, type ApiClient } from "./api";
import type { FieldSession } from "./session";

export type DevRole = "supervisor" | "inventory_controller" | "admin";

export const DEV_ROLES: ReadonlyArray<{ id: DevRole; label: string; roles: string[]; principal: string; hint: string }> = [
  { id: "supervisor", label: "Supervisor", roles: ["field.supervisor"], principal: "dev-supervisor", hint: "Live work, decisions, postings, devices, safety" },
  { id: "inventory_controller", label: "Inventory controller", roles: ["inventory.controller"], principal: "dev-inventory", hint: "Count differences and recounts" },
  { id: "admin", label: "Administrator", roles: ["field.admin"], principal: "dev-admin", hint: "Everything, including revoking devices" },
];

export const TENANT_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const SIGNIN_TTL_S = 8 * 3600;

export interface SignInInput {
  role: DevRole;
  principalId: string;
  tenantId: string;
}

/** Field errors shown next to the inputs; empty when the input is usable. */
export function validateSignIn(i: SignInInput): Partial<Record<"principalId" | "tenantId", string>> {
  const e: Partial<Record<"principalId" | "tenantId", string>> = {};
  if (!i.principalId.trim()) e.principalId = "Enter a name or id for yourself, for example dev-supervisor.";
  else if (!/^[A-Za-z0-9._@-]{1,64}$/.test(i.principalId.trim())) e.principalId = "Use letters, digits, dot, dash, underscore or @ only (up to 64).";
  if (!i.tenantId.trim()) e.tenantId = "Enter the tenant id from var\\dev_stack.json.";
  else if (!TENANT_RE.test(i.tenantId.trim())) e.tenantId = "The tenant id is a UUID, for example 1b4e28ba-2fa1-41d2-883f-0016d3cca427.";
  return e;
}

export async function devSignIn(api: ApiClient, input: SignInInput, nowMs: number): Promise<FieldSession> {
  const role = DEV_ROLES.find((r) => r.id === input.role);
  if (!role) throw new ApiError("validation", null, null, "Choose a role.", null);
  let core: { access_token: string };
  try {
    core = await api.issueDevCoreToken({
      principal_id: input.principalId.trim(),
      tenant_id: input.tenantId.trim().toLowerCase(),
      roles: role.roles,
      ttl_seconds: SIGNIN_TTL_S,
    });
  } catch (e) {
    if (e instanceof ApiError && (e.kind === "network" || e.kind === "server")) {
      throw new ApiError(e.kind, e.status, e.code, MSG.signInUnreachable, e.detail);
    }
    throw e;
  }
  let ex;
  try {
    ex = await api.exchange(core.access_token);
  } catch (e) {
    if (e instanceof ApiError && e.kind === "unauthorized") throw new ApiError("unauthorized", 401, e.code, MSG.exchangeRejected, null);
    throw e;
  }
  return {
    accessToken: ex.access_token,
    expiresAt: nowMs + ex.expires_in * 1000,
    principalId: input.principalId.trim(),
    tenantId: ex.tenant_id,
    roles: ex.roles,
    permissions: ex.permissions,
    siteIds: ex.site_ids,
  };
}

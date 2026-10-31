/**
 * Typed field-api client for the console (contract docs/design/M2_JOBS_CONTRACT.md §1, §5, §7).
 *
 * Every call the console makes goes through createApiClient. fetch is injected so tests run with no
 * network. Writes carry an Idempotency-Key (UUIDv7). Errors become ApiError with a plain-English
 * message (problem+json `title`, or the spec's MSG copy for auth failures).
 *
 * Response types follow packages/field-contract/openapi.json where the route exists, and the M2
 * contract where it is new (approval-requests list, recount). Fields the contract does not promise are
 * optional, and the view mappers treat them as possibly missing.
 */
import { uuid7 } from "./uuid7";

// ------------------------------------------------------------------ response types

export type TaskType = "receive" | "putaway" | "pick" | "count" | "audit" | "swap";
export type TaskStatus = "open" | "in_progress" | "awaiting_posting" | "awaiting_approval" | "done" | "failed";

export interface TaskLine {
  id: string;
  line_no: number;
  material?: string | null;
  description?: string | null;
  uom?: string | null;
  bin?: string | null;
  /** Never present on count tasks (blind count, FR3.029). */
  expected_qty?: number | null;
  counted_qty?: number | null;
  position?: string | null;
  expected_serial?: string | null;
  status: string;
  version?: number;
}

export interface Task {
  id: string;
  type: string;
  status: string;
  title?: string | null;
  subtitle?: string | null;
  ref_doc_no?: string | null;
  /** Pre-M2 name of ref_doc_no in GET /v1/tasks. */
  erp_ref?: string | null;
  reason?: string | null;
  due?: string | null;
  site_id: string;
  version?: number;
  lines: TaskLine[];
  /** Not in the M2 contract; used for "Done today" when the API sends it. */
  updated_at?: string | null;
  completed_at?: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

/** GET /v1/approval-requests?status=pending (new in M2; shape beyond id/status is not fixed yet). */
export interface ApprovalRequest {
  id: string;
  status: string;
  approval_type?: string | null;
  task_id?: string | null;
  site_id?: string | null;
  title?: string | null;
  material?: string | null;
  description?: string | null;
  bin?: string | null;
  uom?: string | null;
  book_qty?: number | string | null;
  counted_qty?: number | string | null;
  difference_qty?: number | string | null;
  value_abs?: number | string | null;
  currency?: string | null;
  band?: string | null;
  requested_by?: string | null;
  counted_by?: string[] | string | null;
  excluded_principals?: string[] | null;
  /** Separation-of-duties note written by the API for the caller ("You did not count this bin…"). */
  sod_note?: string | null;
  can_decide?: boolean | null;
  recount_count?: number | null;
  created_at?: string | null;
}

/** GET /v1/mismatches item (field_api.audit.mismatch_api.list_mismatches). */
export interface Mismatch {
  id: string;
  site_id: string;
  site_code?: string | null;
  class: string;
  expected_serial?: string | null;
  found_serial?: string | null;
  status: string;
  reason?: string | null;
  verify_status?: string | null;
  crop_url?: string | null;
  raw_ocr_text?: string | null;
  confidence?: number | null;
  material?: string | null;
  equipment_class?: string | null;
  age_h?: number | null;
  created_at?: string | null;
  /** Not returned today; when present it is sent as capturing_technician_id for the SoD check. */
  captured_by?: string | null;
}

export interface MismatchDecisionResult {
  finding_id: string;
  decision: string;
  status: string;
  requires_approval?: boolean;
  approval_id?: string | null;
}

/** GET /v1/safety/active-visits (field_api.safety.api). */
export interface ActiveVisit {
  visit_id: string;
  site_id: string;
  site_code?: string | null;
  site_name?: string | null;
  user_id: string;
  status: string;
  tower_fl?: string | null;
  last_altitude_m?: number | null;
  timer_interval_min?: number | null;
  timer_remaining_s?: number | null;
  last_heartbeat_at?: string | null;
  is_escalated?: boolean;
  is_acknowledged?: boolean;
  escalation_message?: string | null;
}

export interface ActiveVisits {
  visits: ActiveVisit[];
  total_active?: number;
  has_escalation?: boolean;
}

/** GET /v1/audits/{task_id}/progress (field_api.audit.progress). */
export interface AuditSector {
  code: string;
  value: number;
  expected_count: number;
  captured_count: number;
  empty_scope?: boolean;
}

export interface AuditTower {
  code: string;
  value: number;
  empty_scope?: boolean;
  sectors: AuditSector[];
}

export interface AuditProgress {
  site: number;
  site_id?: string | null;
  empty_scope?: boolean;
  towers: AuditTower[];
}

/** SiteRecord (openapi). `mode` is new in M3 (docs/design/M3_CONTRACT.md §2); absent on an older field-api. */
export type SiteMode = "production" | "sandbox";

export interface Site {
  id: string;
  code: string;
  name: string;
  kind: string;
  status?: string;
  erp_plant?: string | null;
  mode?: SiteMode | string | null;
}

// ------------------------------------------------------------------ Field Assistant records (M3 contract §4)

/** GET /v1/assistant/sessions item. */
export interface AssistantSession {
  id: string;
  site_id: string;
  principal_id: string;
  mode?: string | null;
  started_at: string;
  ended_at?: string | null;
  turns: number;
  documents?: string[] | null;
  cost_usd?: number | string | null;
}

/** One turn of GET /v1/assistant/sessions/{id} (field.assistant_turn). Heard/said/photos are purged after 30 days. */
export interface AssistantTurnRecord {
  id: string;
  session_id?: string;
  at: string;
  event: string;
  heard?: string | null;
  said?: string | null;
  actions?: unknown;
  tool_calls?: unknown;
  code?: string | null;
  photo_ref?: string | null;
  ai?: string | null;
  cost_usd?: number | string | null;
  latency_ms?: number | null;
}

/** GET /v1/assistant/sessions/{id}: the session fields plus `turns[]`. */
export type AssistantSessionWithTurns = Omit<AssistantSession, "turns"> & {
  device_id?: string | null;
  turns: AssistantTurnRecord[];
};

/** QueueSummary (openapi). */
export interface QueueSummary {
  queue_key: string;
  pending_count: number;
  running_count: number;
  failed_count: number;
  completed_count: number;
  cancelled_count: number;
  is_blocked: boolean;
  min_seq?: number | null;
  max_seq?: number | null;
  oldest_pending_at?: string | null;
}

/** PostingJobRecord (openapi) plus optional error text the worker does not store yet. */
export interface PostingJob {
  id: string;
  queue_key: string;
  seq: number;
  ref_doc_no?: string | null;
  status: string;
  attempts: number;
  max_attempts: number;
  next_attempt_at?: string | null;
  payload?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  last_error?: string | null;
  sap_message?: string | null;
}

/** DeviceRecord (openapi). */
export interface Device {
  id: string;
  kind: string;
  serial_no: string;
  model: string;
  status: string;
  app_version?: string | null;
  firmware_version?: string | null;
  paired_with?: string | null;
  battery_pct?: number | null;
  queue_depth?: number | null;
  glasses_state?: string | null;
  last_seen_at?: string | null;
  revoked_at?: string | null;
  is_stale?: boolean;
  version?: number;
}

/** SystemStatusResponse (openapi). */
export interface SystemCheck {
  name: string;
  ok: boolean;
  probe_ms?: number | null;
  detail?: string;
}

export interface SystemStatus {
  ready: boolean;
  compat: Record<string, string>;
  erp: { system: string; reachable: boolean; probe_ms?: number | null; p95_ms?: number | null };
  checks: SystemCheck[];
}

/** GET /v1/system/ai-usage (A-02 budget guard). */
export interface AiUsage {
  providers: Record<string, { spent_usd: string; cap_usd: string | null }>;
  today_usd?: string;
  daily_cap_usd?: string | null;
  cloud_enabled?: boolean;
}

/** ExchangeResponse (openapi). */
export interface ExchangeResponse {
  access_token: string;
  token_type?: string;
  expires_in: number;
  roles: string[];
  permissions: string[];
  tenant_id: string;
  site_ids: string[];
  device_id?: string | null;
}

export interface CoreTokenRequest {
  principal_id: string;
  tenant_id: string;
  roles: string[];
  ttl_seconds: number;
}

// ------------------------------------------------------------------ errors

export type ApiErrorKind =
  | "network"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "validation"
  | "server"
  | "unexpected";

export const MSG = {
  /** MSG1.10 */
  permission: "You do not have permission for this action. Ask a Field administrator for access.",
  /** MSG1.11 */
  noRole: "You have no Field role yet. Ask a Field administrator to assign one.",
  /** MSG1.13 (console wording for the dev sign-in service) */
  signInUnreachable: "We could not reach SCMTIPS sign-in. Check your connection and try again.",
  /** MSG1.14 */
  exchangeRejected: "Sign-in did not complete. Close this tab, sign in to SCMTIPS again, then reopen Field.",
  /** MSG1.15 */
  addonDisabled: "SCMTIPS Field is not enabled for your organisation. Ask your SCMTIPS administrator to request it.",
  expired: "Your sign-in has expired. Sign in again.",
  network: "We could not reach field-api. Check that the dev stack is running on this PC, then try again.",
} as const;

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
    readonly code: string | null,
    readonly title: string,
    readonly detail: string | null,
  ) {
    super(title);
    this.name = "ApiError";
  }
}

const CODE_PREFIX = /^FIELD-[A-Z0-9-]+:\s*/;

/** Reads problem+json, FastAPI {detail: {error_code, message}} and {detail: "..."} bodies. */
export function parseErrorBody(status: number, body: unknown): { code: string | null; title: string | null; detail: string | null } {
  if (!body || typeof body !== "object") return { code: null, title: null, detail: null };
  const o = body as Record<string, unknown>;
  if (typeof o.code === "string" || typeof o.title === "string") {
    return {
      code: typeof o.code === "string" ? o.code : null,
      title: typeof o.title === "string" ? o.title : null,
      detail: typeof o.detail === "string" ? o.detail : null,
    };
  }
  const d = o.detail;
  if (typeof d === "string") {
    const m = /^(FIELD-[A-Z0-9-]+)/.exec(d);
    return { code: m ? m[1] : null, title: d.replace(CODE_PREFIX, ""), detail: null };
  }
  if (d && typeof d === "object" && !Array.isArray(d)) {
    const dd = d as Record<string, unknown>;
    const code = typeof dd.error_code === "string" ? dd.error_code : typeof dd.code === "string" ? dd.code : null;
    const msg = typeof dd.message === "string" ? dd.message.replace(CODE_PREFIX, "") : null;
    return { code, title: msg, detail: null };
  }
  if (Array.isArray(d) && status === 422) {
    const first = d[0] as Record<string, unknown> | undefined;
    const msg = first && typeof first.msg === "string" ? first.msg : null;
    return { code: "FIELD-HTTP-422-VALIDATION", title: msg ? `The request was not valid: ${msg}` : null, detail: null };
  }
  return { code: null, title: null, detail: null };
}

export function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409 || status === 412) return "conflict";
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server";
  return "unexpected";
}

/** Plain-English title for an HTTP error, preferring the spec's MSG copy for auth failures. */
export function errorFromResponse(status: number, body: unknown): ApiError {
  const p = parseErrorBody(status, body);
  const kind = kindForStatus(status);
  let title = p.title;
  if (kind === "unauthorized") title = MSG.expired;
  else if (p.code === "FIELD-FLAG-403-DISABLED") title = MSG.addonDisabled;
  else if (p.code === "FIELD-AUTH-403-NO-ROLE") title = MSG.noRole;
  else if (kind === "forbidden" && (!p.code || p.code === "FIELD-AUTH-403-FORBIDDEN" || p.code === "FIELD-AUTH-403-PERMISSION" || title === "Forbidden")) {
    title = MSG.permission;
  }
  if (!title) title = kind === "server" ? `field-api had a problem (HTTP ${status}). Try again in a moment.` : `The request failed (HTTP ${status}).`;
  return new ApiError(kind, status, p.code, title, p.detail);
}

// ------------------------------------------------------------------ client

export interface ClientDeps {
  fetch: (input: string, init?: RequestInit) => Promise<Response>;
  /** field-api origin; "" means same origin (the Next rewrite proxy). */
  baseUrl: string;
  /** fake-core origin for the development sign-in; "/dev-core" is the Next rewrite. */
  coreBaseUrl: string;
  getToken: () => string | null;
  idempotencyKey?: () => string;
  /** Called on any 401, so the shell can drop the session. */
  onUnauthorized?: () => void;
}

export interface TaskQuery {
  site_id?: string;
  status?: string[];
  type?: string[];
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** Upper bound on pages followed for one list (200 per page). */
export const MAX_PAGES = 10;

export function createApiClient(deps: ClientDeps) {
  const idem = deps.idempotencyKey ?? (() => uuid7());

  async function request<T>(method: string, url: string, opts: { body?: unknown; auth?: boolean; write?: boolean } = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.auth !== false) {
      const token = deps.getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
    }
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (opts.write) headers["Idempotency-Key"] = idem();
    let res: Response;
    try {
      res = await deps.fetch(url, {
        method,
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        cache: "no-store",
      });
    } catch (e) {
      throw new ApiError("network", null, null, MSG.network, e instanceof Error ? e.message : null);
    }
    const text = await res.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    if (!res.ok) {
      const err = errorFromResponse(res.status, body);
      if (err.kind === "unauthorized") deps.onUnauthorized?.();
      throw err;
    }
    if (text && body === null) {
      throw new ApiError("unexpected", res.status, null, "field-api answered with something that is not JSON.", null);
    }
    return body as T;
  }

  /** Non-JSON downloads (CSV export, photos) with the same auth and error handling as [request]. */
  async function download(path: string): Promise<Blob> {
    const headers: Record<string, string> = {};
    const token = deps.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await deps.fetch(`${deps.baseUrl}${path}`, { method: "GET", headers, cache: "no-store" });
    } catch (e) {
      throw new ApiError("network", null, null, MSG.network, e instanceof Error ? e.message : null);
    }
    if (!res.ok) {
      let body: unknown = null;
      try {
        body = JSON.parse(await res.text());
      } catch {
        body = null;
      }
      const err = errorFromResponse(res.status, body);
      if (err.kind === "unauthorized") deps.onUnauthorized?.();
      throw err;
    }
    return res.blob();
  }

  const api = (path: string) => `${deps.baseUrl}${path}`;
  const enc = encodeURIComponent;
  const get = <T>(path: string) => request<T>("GET", api(path));
  const post = <T>(path: string, body?: unknown) => request<T>("POST", api(path), { body: body ?? {}, write: true });

  async function allPages<T>(first: string, sep: "?" | "&"): Promise<T[]> {
    const out: T[] = [];
    let cursor: string | null | undefined = undefined;
    for (let i = 0; i < MAX_PAGES; i++) {
      const page: Page<T> = await get<Page<T>>(cursor ? `${first}${sep}cursor=${enc(cursor)}` : first);
      if (!page || !Array.isArray(page.items)) {
        throw new ApiError("unexpected", 200, null, "field-api sent a list in an unexpected shape.", null);
      }
      out.push(...page.items);
      cursor = page.next_cursor;
      if (!cursor) break;
    }
    return out;
  }

  return {
    // --- auth
    issueDevCoreToken: (req: CoreTokenRequest) =>
      request<{ access_token: string; expires_in: number }>("POST", `${deps.coreBaseUrl}/api/v1/auth/token`, { body: req, auth: false }),
    exchange: (coreToken: string) =>
      request<ExchangeResponse>("POST", api("/v1/auth/exchange"), { body: { device_token: coreToken, client_id: "field-console" }, auth: false }),

    // --- work
    listTasks: (q: TaskQuery = {}) => {
      const p = new URLSearchParams();
      if (q.site_id) p.set("site_id", q.site_id);
      if (q.status?.length) p.set("status", q.status.join(","));
      if (q.type?.length) p.set("type", q.type.join(","));
      p.set("limit", "200");
      return allPages<Task>(`/v1/tasks?${p.toString()}`, "&");
    },
    requestRecount: (taskId: string, reason: string) => post<Record<string, unknown>>(`/v1/tasks/${enc(taskId)}/recount`, { reason }),

    // --- decisions
    listPendingApprovals: async () => {
      const body = await get<Page<ApprovalRequest> | ApprovalRequest[]>("/v1/approval-requests?status=pending");
      const items = Array.isArray(body) ? body : body?.items;
      if (!Array.isArray(items)) throw new ApiError("unexpected", 200, null, "field-api sent approval requests in an unexpected shape.", null);
      return items;
    },
    decideApproval: (id: string, decision: "approve" | "reject", reason: string) =>
      post<{ id: string; status: string; erp_document_id?: string | null }>(`/v1/approval-requests/${enc(id)}/decide`, { decision, reason }),
    listMismatches: () => allPages<Mismatch>("/v1/mismatches?limit=200", "&"),
    decideMismatch: (id: string, decision: string, note: string, capturingTechnicianId?: string | null) =>
      post<MismatchDecisionResult>(`/v1/mismatches/${enc(id)}/decision`, {
        decision,
        note,
        ...(capturingTechnicianId ? { capturing_technician_id: capturingTechnicianId } : {}),
      }),

    // --- sites, audits, safety
    listSites: () => allPages<Site>("/v1/sites?limit=200", "&"),
    getAuditProgress: (taskId: string) => get<AuditProgress>(`/v1/audits/${enc(taskId)}/progress`),
    listActiveVisits: async () => {
      const body = await get<ActiveVisits>("/v1/safety/active-visits");
      if (!body || !Array.isArray(body.visits)) throw new ApiError("unexpected", 200, null, "field-api sent active visits in an unexpected shape.", null);
      return body;
    },
    acknowledgeVisit: (visitId: string, notes: string | null) =>
      post<Record<string, unknown>>(`/v1/safety/visits/${enc(visitId)}/ack`, { notes }),

    // --- postings
    listPostingQueues: () => get<QueueSummary[]>("/v1/posting-queues"),
    listQueueJobs: (queueKey: string) => get<PostingJob[]>(`/v1/posting-queues/${enc(queueKey)}/jobs`),
    retryPostingJob: (jobId: string) => post<Record<string, unknown>>(`/v1/posting-jobs/${enc(jobId)}/retry`),

    // --- devices
    listDevices: () => get<Device[]>("/v1/devices?limit=200"),
    revokeDevice: (id: string, reason: string) => post<Device>(`/v1/devices/${enc(id)}/revoke`, { reason }),

    // --- Field Assistant records (supervisor reads, M3 contract §4)
    listAssistantSessions: async (q: { site_id?: string; limit?: number } = {}) => {
      const p = new URLSearchParams();
      if (q.site_id) p.set("site_id", q.site_id);
      p.set("limit", String(q.limit ?? 100));
      const body = await get<Page<AssistantSession> | AssistantSession[]>(`/v1/assistant/sessions?${p.toString()}`);
      const items = Array.isArray(body) ? body : body?.items;
      if (!Array.isArray(items)) throw new ApiError("unexpected", 200, null, "field-api sent assistant sessions in an unexpected shape.", null);
      return items;
    },
    getAssistantSession: async (id: string) => {
      const body = await get<AssistantSessionWithTurns>(`/v1/assistant/sessions/${enc(id)}`);
      if (!body || !Array.isArray(body.turns)) throw new ApiError("unexpected", 200, null, "field-api sent the session in an unexpected shape.", null);
      return body;
    },
    /** CSV of one session (needs the bearer token, so it is fetched, not linked). */
    exportAssistantSessionCsv: (id: string) => download(`/v1/assistant/sessions/${enc(id)}/export.csv`),
    /** A turn's photo when its photo_ref is a field-api path (e.g. /v1/assistant/photos/...). */
    downloadPath: (path: string) => download(path),

    // --- system
    getSystemStatus: () => get<SystemStatus>("/v1/system/status"),
    getAiUsage: () => get<AiUsage>("/v1/system/ai-usage"),
  };
}

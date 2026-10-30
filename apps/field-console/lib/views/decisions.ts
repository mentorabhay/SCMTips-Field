/**
 * Decisions (T3.057 / T3.060 / T4.067): pending count differences (GET /v1/approval-requests?status=pending)
 * and open tower findings (GET /v1/mismatches) as one list of cases.
 *
 * Each case carries a rule-based suggestion. These are fixed rules written here, not an AI: the AI
 * agent that drafts proposals with sources is phase 6. The person always decides; the console only
 * calls the decide endpoints when a button is pressed.
 */
import type { ApprovalRequest, Mismatch } from "../api";
import { parseTime, plural, qty, toNumber } from "./format";

export type Severity = "High" | "Medium" | "Low";

export interface Fact {
  k: string;
  v: string;
}

export type ApprovalAction = "approve" | "recount" | "reject";

export interface Suggestion {
  headline: string;
  why: string;
  basis: string;
  /** approval: which button the rule favours; mismatch: the decision value to send. */
  action: string;
}

export interface Sod {
  text: string;
  /** null when the API did not say; the server still enforces it on decide. */
  mayDecide: boolean | null;
}

interface CaseBase {
  key: string;
  id: string;
  kind: string;
  title: string;
  sub: string;
  severity: Severity;
  waiting: string;
  createdMs: number | null;
  facts: Fact[];
  suggestion: Suggestion;
  sod: Sod;
}

export interface ApprovalCase extends CaseBase {
  source: "approval";
  taskId: string | null;
}

export interface MismatchCase extends CaseBase {
  source: "mismatch";
  capturedBy: string | null;
  /** Decisions offered, suggested one first. */
  decisions: string[];
}

export type DecisionCase = ApprovalCase | MismatchCase;

/** SCR4.10 decision buttons; values are field_api.audit.decisions.ALLOWED_DECISIONS. */
export const MISMATCH_DECISION_LABEL: Record<string, string> = {
  re_capture: "Re-capture",
  accept_erp: "Accept ERP",
  update_erp: "Update ERP",
  record_move: "Record move",
  waived: "Waive",
};

export const MISMATCH_CLASS_LABEL: Record<string, string> = {
  serial_mismatch: "Serial mismatch",
  tower_only: "Found on the tower, not in SAP",
  erp_only: "In SAP, not found on the tower",
  misplaced: "Unit in a different position",
};

const VERIFY_LABEL: Record<string, string> = {
  verified: "Verified",
  mismatch: "Disagrees with the device read",
  failed: "Check failed",
  pending: "Not checked yet",
  unverified: "Not verified",
};

export function waitingText(createdMs: number | null, nowMs: number): string {
  if (createdMs === null) return "Waiting time not reported";
  const h = Math.floor(Math.max(0, nowMs - createdMs) / 3600000);
  if (h < 1) return "Waiting less than an hour";
  if (h < 48) return `Waiting ${plural(h, "hour")}`;
  return `Waiting ${plural(Math.floor(h / 24), "day")}`;
}

// ------------------------------------------------------------------ count differences

export function countDifference(a: ApprovalRequest): number | null {
  const d = toNumber(a.difference_qty);
  if (d !== null) return d;
  const book = toNumber(a.book_qty);
  const counted = toNumber(a.counted_qty);
  return book !== null && counted !== null ? counted - book : null;
}

export function approvalSeverity(a: ApprovalRequest): Severity {
  if (a.band === "B3") return "High";
  if (a.band === "B2") return "Medium";
  if (a.band === "B1") return "Low";
  return "Medium";
}

/** Rule: recount first; once a recount has been done and still differs, approve the difference. */
export function suggestForCount(a: ApprovalRequest): Suggestion {
  const basis = "Fixed rule using the counted and book quantities, value band and recount history from field-api.";
  const highBand = a.band === "B3" ? " The value is in the highest approval band." : "";
  if (typeof a.recount_count === "number" && a.recount_count >= 1) {
    return {
      headline: "Approve the difference",
      why: `It was counted again (${plural(a.recount_count, "recount")}) and still differs from the books.${highBand}`,
      basis,
      action: "approve",
    };
  }
  if (typeof a.recount_count === "number") {
    return {
      headline: "Ask for a recount before posting a difference",
      why: `Nobody has recounted this yet. A second blind count by someone else settles most differences cheaply.${highBand}`,
      basis,
      action: "recount",
    };
  }
  return {
    headline: "Ask for a recount before posting a difference",
    why: `field-api did not say whether this was recounted. A recount is the cheap check before stock is written off or added.${highBand}`,
    basis,
    action: "recount",
  };
}

export function sodForApproval(a: ApprovalRequest, principalId: string): Sod {
  const excluded = Array.isArray(a.excluded_principals) ? a.excluded_principals : null;
  const blocked = excluded ? excluded.includes(principalId) || a.requested_by === principalId : a.requested_by === principalId ? true : null;
  if (a.sod_note) {
    return { text: a.sod_note, mayDecide: typeof a.can_decide === "boolean" ? a.can_decide : blocked === null ? null : !blocked };
  }
  if (typeof a.can_decide === "boolean") {
    return a.can_decide
      ? { text: "You did not count this bin and did not ask for the posting, so you may decide.", mayDecide: true }
      : { text: "You counted this bin or asked for the posting, so someone else must decide.", mayDecide: false };
  }
  if (blocked === true) return { text: "You counted this bin or asked for the posting, so someone else must decide.", mayDecide: false };
  if (blocked === false) return { text: "You did not count this bin and did not ask for the posting, so you may decide.", mayDecide: true };
  return {
    text: "field-api checks separation of duties when you decide: whoever counted or asked for the posting cannot approve it.",
    mayDecide: null,
  };
}

export function approvalCase(a: ApprovalRequest, principalId: string, nowMs: number): ApprovalCase {
  const diff = countDifference(a);
  const uom = a.uom ? ` ${a.uom}` : "";
  const where = a.bin ? `Bin ${a.bin}` : a.material ? a.material : "Count";
  const diffText = diff === null ? "" : diff === 0 ? " · no difference" : ` · ${qty(Math.abs(diff))} ${diff < 0 ? "fewer" : "more"} than the books`;
  const facts: Fact[] = [];
  const book = toNumber(a.book_qty);
  const counted = toNumber(a.counted_qty);
  if (book !== null) facts.push({ k: "Books say", v: `${qty(book)}${uom}` });
  if (counted !== null) facts.push({ k: "Counted", v: `${qty(counted)}${uom}` });
  if (diff !== null) facts.push({ k: "Difference", v: `${diff > 0 ? "+" : ""}${qty(diff)}${uom}` });
  const value = toNumber(a.value_abs);
  if (value !== null) facts.push({ k: "Value", v: `${value.toFixed(2)}${a.currency ? ` ${a.currency}` : ""}` });
  if (a.band) facts.push({ k: "Approval band", v: a.band });
  if (typeof a.recount_count === "number") facts.push({ k: "Recounts", v: String(a.recount_count) });
  const createdMs = parseTime(a.created_at);
  return {
    source: "approval",
    key: `approval:${a.id}`,
    id: a.id,
    kind: "Count difference",
    title: a.title || `${where}${diffText}`,
    sub: [a.material, a.description].filter(Boolean).join(" · ") || (a.approval_type ? a.approval_type.replace(/_/g, " ") : "Approval request"),
    severity: approvalSeverity(a),
    waiting: waitingText(createdMs, nowMs),
    createdMs,
    facts,
    suggestion: suggestForCount(a),
    sod: sodForApproval(a, principalId),
    taskId: a.task_id ?? null,
  };
}

// ------------------------------------------------------------------ tower findings

/** Rule per finding class and photo check; the first decision in the list is the suggestion. */
export function suggestForMismatch(m: Mismatch): Suggestion {
  const basis = "Fixed rule using the finding class and the photo check result from field-api.";
  const verified = m.verify_status === "verified";
  switch (m.class) {
    case "serial_mismatch":
      return verified
        ? { headline: "Update SAP to the serial found on the tower", why: "The photo check verified the captured serial, so SAP is probably out of date.", basis, action: "update_erp" }
        : { headline: "Re-capture before changing SAP", why: "The photo check did not verify the captured serial. A clearer capture settles it.", basis, action: "re_capture" };
    case "tower_only":
      return verified
        ? { headline: "Add the unit found on the tower to SAP", why: "A verified unit is installed that SAP does not know about.", basis, action: "update_erp" }
        : { headline: "Re-capture the unknown unit", why: "The unit was not verified. Confirm the serial before adding it to SAP.", basis, action: "re_capture" };
    case "erp_only":
      return { headline: "Look again before changing SAP", why: "Not finding a unit once is weak evidence: it may be hidden or in another sector.", basis, action: "re_capture" };
    case "misplaced":
      return { headline: "Record the move to where it was found", why: "The serial matches SAP; only its position differs.", basis, action: "record_move" };
    default:
      return { headline: "Re-capture", why: "This finding type has no rule yet, so the safe step is a new capture.", basis, action: "re_capture" };
  }
}

export function mismatchSeverity(m: Mismatch): Severity {
  if (typeof m.age_h === "number" && m.age_h >= 24) return "High";
  if (m.class === "serial_mismatch" || m.class === "erp_only") return "Medium";
  return "Low";
}

export function sodForMismatch(m: Mismatch, principalId: string): Sod {
  if (m.captured_by && m.captured_by === principalId) return { text: "You captured this unit, so someone else must decide.", mayDecide: false };
  if (m.captured_by) return { text: `Captured by ${m.captured_by}; you may decide.`, mayDecide: true };
  return { text: "field-api did not say who captured this unit. If it was you, the decision is refused.", mayDecide: null };
}

export function mismatchCase(m: Mismatch, principalId: string, nowMs: number): MismatchCase {
  const s = suggestForMismatch(m);
  const facts: Fact[] = [
    { k: "SAP expects", v: m.expected_serial || "Nothing at this position" },
    { k: "Found on the tower", v: m.found_serial || "Nothing found" },
  ];
  const eq = m.equipment_class || m.material;
  if (eq) facts.push({ k: "Equipment", v: eq });
  if (m.verify_status) facts.push({ k: "Photo check", v: VERIFY_LABEL[m.verify_status] ?? m.verify_status });
  if (typeof m.confidence === "number") facts.push({ k: "Read confidence", v: `${Math.round(m.confidence * 100)}%` });
  if (m.raw_ocr_text) facts.push({ k: "Text read", v: m.raw_ocr_text });
  const createdMs = parseTime(m.created_at) ?? (typeof m.age_h === "number" ? nowMs - m.age_h * 3600000 : null);
  const order = ["re_capture", "accept_erp", "update_erp", "record_move", "waived"];
  return {
    source: "mismatch",
    key: `mismatch:${m.id}`,
    id: m.id,
    kind: MISMATCH_CLASS_LABEL[m.class] ?? m.class.replace(/_/g, " "),
    title: `${m.site_code || "Site"} · ${m.expected_serial || m.found_serial || "unit"}`,
    sub: m.status === "awaiting_approval" ? "Awaiting approval" : m.reason || "Found during a tower audit",
    severity: mismatchSeverity(m),
    waiting: waitingText(createdMs, nowMs),
    createdMs,
    facts,
    suggestion: s,
    sod: sodForMismatch(m, principalId),
    capturedBy: m.captured_by ?? null,
    decisions: [s.action, ...order.filter((d) => d !== s.action)],
  };
}

// ------------------------------------------------------------------ list

const SEV_RANK: Record<Severity, number> = { High: 0, Medium: 1, Low: 2 };

/** High first, then oldest first; unknown age last. Pending approvals only. */
export function buildCases(
  approvals: readonly ApprovalRequest[],
  mismatches: readonly Mismatch[],
  principalId: string,
  nowMs: number,
): DecisionCase[] {
  const cases: DecisionCase[] = [
    ...approvals.filter((a) => a.status === "pending").map((a) => approvalCase(a, principalId, nowMs)),
    ...mismatches.filter((m) => m.status !== "resolved").map((m) => mismatchCase(m, principalId, nowMs)),
  ];
  return cases.sort(
    (a, b) =>
      SEV_RANK[a.severity] - SEV_RANK[b.severity] ||
      (a.createdMs ?? Number.POSITIVE_INFINITY) - (b.createdMs ?? Number.POSITIVE_INFINITY) ||
      a.key.localeCompare(b.key),
  );
}

/** What the person sees after a decide call succeeded. */
export function approvalOutcome(action: ApprovalAction, result: { status?: string; erp_document_id?: string | null } | null): string {
  if (action === "recount") return "Recount requested. It appears as a count job on the operator's phone.";
  if (action === "reject") return "Rejected. Nothing is posted to SAP.";
  return result?.erp_document_id
    ? "Approved. The difference is queued for posting to SAP; follow it in Postings to SAP."
    : "Approved.";
}

export function mismatchOutcome(decision: string, result: { requires_approval?: boolean; status?: string } | null): string {
  const label = MISMATCH_DECISION_LABEL[decision] ?? decision;
  if (result?.requires_approval) return `${label} recorded. It now waits for a second approval.`;
  return `${label} recorded. The finding is closed.`;
}

/**
 * System status (T1.076 / SCR1.05): GET /v1/system/status (+ GET /v1/system/ai-usage) -> check cards.
 * Copy from SCR1.05: "All checks passed", "{n} checks need attention", "ERP simulator reachable",
 * "ERP simulator not reachable. Postings will wait in the queue."
 */
import type { AiUsage, SystemStatus } from "../api";
import { toNumber } from "./format";

export type CheckTone = "ok" | "warn" | "bad" | "unknown";

export interface CheckCard {
  name: string;
  state: string;
  tone: CheckTone;
}

const TONE_WORD: Record<CheckTone, string> = { ok: "OK", warn: "Attention", bad: "Problem", unknown: "Unknown" };

export function toneWord(t: CheckTone): string {
  return TONE_WORD[t];
}

function ms(v: number | null | undefined): string {
  return typeof v === "number" ? ` · ${Math.round(v)} ms` : "";
}

export function statusChecks(s: SystemStatus): CheckCard[] {
  const out: CheckCard[] = [];
  for (const c of s.checks) {
    if (c.name === "postgres") {
      out.push({ name: "Database", state: c.ok ? `Connected${ms(c.probe_ms)}` : `Not reachable${c.detail ? ` · ${c.detail}` : ""}`, tone: c.ok ? "ok" : "bad" });
    } else if (c.name === "field-worker") {
      out.push({ name: "Background worker", state: `${c.ok ? "Running" : "Not running"}${c.detail ? ` · ${c.detail}` : ""}`, tone: c.ok ? "ok" : "bad" });
    } else if (c.name === "erp") {
      continue; // shown from s.erp below, which carries the system name
    } else {
      out.push({ name: c.name, state: `${c.ok ? "OK" : "Failing"}${c.detail ? ` · ${c.detail}` : ""}${ms(c.probe_ms)}`, tone: c.ok ? "ok" : "bad" });
    }
  }
  const sim = s.erp.system === "erp-sim";
  out.push({
    name: sim ? "SAP (ERP simulator)" : `SAP (${s.erp.system})`,
    state: s.erp.reachable
      ? `${sim ? "ERP simulator reachable" : "Reachable"}${ms(s.erp.probe_ms)}`
      : `${sim ? "ERP simulator" : "SAP"} not reachable. Postings will wait in the queue.`,
    tone: s.erp.reachable ? "ok" : "bad",
  });
  for (const [core, result] of Object.entries(s.compat).sort(([a], [b]) => a.localeCompare(b))) {
    const name = `${core.replace(/^core-p/i, "Core P")} compatibility`;
    const r = result.toUpperCase();
    out.push(
      r === "PASS"
        ? { name, state: "Tested and passing", tone: "ok" }
        : r === "UNVERIFIED"
          ? { name, state: "Not tested yet", tone: "unknown" }
          : { name, state: `Test result: ${result}`, tone: "bad" },
    );
  }
  return out;
}

/** One card per provider: lifetime spend against its cap (BudgetGuard); warn at 80% of the cap. */
export function aiChecks(u: AiUsage): CheckCard[] {
  if (u.cloud_enabled === false) return [{ name: "AI budget", state: "Cloud AI is switched off", tone: "unknown" }];
  const out: CheckCard[] = [];
  for (const [p, v] of Object.entries(u.providers).sort(([a], [b]) => a.localeCompare(b))) {
    const spent = toNumber(v.spent_usd) ?? 0;
    const cap = toNumber(v.cap_usd);
    if (cap === null) {
      out.push({ name: `AI budget · ${p}`, state: `$${spent.toFixed(2)} spent · no cap set, so paid calls are refused`, tone: "warn" });
    } else {
      out.push({
        name: `AI budget · ${p}`,
        state: `$${spent.toFixed(2)} of $${cap.toFixed(2)} cap used so far`,
        tone: spent >= cap ? "bad" : spent >= 0.8 * cap ? "warn" : "ok",
      });
    }
  }
  return out.length ? out : [{ name: "AI budget", state: "No AI providers configured", tone: "unknown" }];
}

export function summaryLine(cards: readonly CheckCard[]): string {
  const n = cards.filter((c) => c.tone === "bad" || c.tone === "warn").length;
  return n === 0 ? "All checks passed" : `${n} ${n === 1 ? "check needs" : "checks need"} attention`;
}

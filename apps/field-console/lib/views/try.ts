/**
 * "Try a look" (M5-W01): the page logic, pure and testable. A signed-in user picks a test case (C1 grocery, C2
 * pharmacy), a bundled SAMPLE photo or an upload (JPEG/PNG, <= 5 MB, scaled in the browser to <= 1600 px), and
 * field-api runs the real look (POST /v1/try/looks). The page draws numbered outlines (green good, red damaged; blue
 * while the labels are being read), lists counts, label reads, pack-size and expiry findings and the proposal, and
 * speaks the answer with the browser's speechSynthesis: the first answer, then — when the look turns final, polled
 * every 1 s for up to 60 s as the phone does — `say_next`. Nothing is posted; photos are kept 24 hours.
 */
import type { LookInstance, TryCase, TryLook, TryLookRequest } from "../api";

// ------------------------------------------------------------------ cases and samples

export interface TryCaseInfo {
  id: TryCase;
  title: string;
  where: string;
  noun: string;
  defaultUnits: number;
  defaultPieces?: number;
  defaultWindowDays?: number;
}

export const TRY_CASES: Record<TryCase, TryCaseInfo> = {
  grocery: { id: "grocery", title: "C1 Grocery delivery", where: "packs on a table or a shop's back room", noun: "packs", defaultUnits: 8, defaultPieces: 6 },
  pharmacy: { id: "pharmacy", title: "C2 Pharmacy receipt", where: "medicine boxes from a cabinet or a pharmacy", noun: "boxes", defaultUnits: 5, defaultWindowDays: 90 },
};

export interface TrySample {
  id: string;
  case: TryCase;
  src: string;
  fileName: string;
  title: string;
  note: string;
}

/** Synthetic photos drawn by tools/samples/try_photos.py (no brands, faces or logos). */
export const TRY_SAMPLES: TrySample[] = [
  { id: "c1", case: "grocery", src: "/samples/c1-grocery.jpg", fileName: "c1-grocery.jpg", title: "8 biscuit packs", note: "One torn; one says pack of 4." },
  { id: "c2", case: "pharmacy", src: "/samples/c2-pharmacy.jpg", fileName: "c2-pharmacy.jpg", title: "5 tablet boxes", note: "One dented; one batch expires 2026-12." },
];

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
export const LONG_SIDE = 1600;
export const POLL_INTERVAL_MS = 1000;
export const POLL_TIMEOUT_MS = 60000;

/** Why a chosen file cannot be sent, or null (field-api checks the same again: 413 / 415). */
export function checkFile(f: { type: string; size: number }): string | null {
  if (f.type !== "image/jpeg" && f.type !== "image/png") return "Choose a JPEG or PNG photo.";
  if (f.size > MAX_UPLOAD_BYTES) return "The photo is larger than 5 MB. Choose a smaller one.";
  if (f.size === 0) return "The file is empty.";
  return null;
}

/** The size a photo is scaled to before upload: at most `max` on its long side, aspect kept, never scaled up. */
export function fitWithin(width: number, height: number, max = LONG_SIDE): { width: number; height: number; scale: number } {
  const longest = Math.max(width, height);
  if (longest <= max || longest <= 0) return { width, height, scale: 1 };
  const scale = max / longest;
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)), scale };
}

/** The request for the chosen case and the user's numbers, or the first problem with them. */
export function tryRequest(
  c: TryCase,
  units: number,
  extra: { pieces?: number | null; windowDays?: number | null },
): { ok: true; request: TryLookRequest } | { ok: false; error: string } {
  const whole = (n: number | null | undefined) => n !== null && n !== undefined && Number.isInteger(n);
  if (!whole(units) || units < 1 || units > 200) return { ok: false, error: "Expected units must be a whole number from 1 to 200." };
  if (c === "grocery") {
    const p = extra.pieces;
    if (!whole(p) || (p as number) < 1 || (p as number) > 1000) return { ok: false, error: "Pieces per pack must be a whole number from 1 to 1000." };
    return { ok: true, request: { case: c, expected_units: units, pieces_per_unit: p as number } };
  }
  const w = extra.windowDays;
  if (!whole(w) || (w as number) < 0 || (w as number) > 3650) return { ok: false, error: "The expiry window must be a whole number of days from 0 to 3650." };
  return { ok: true, request: { case: c, expected_units: units, window_days: w as number } };
}

// ------------------------------------------------------------------ outlines

export type OutlineTone = "good" | "damaged" | "pending";

export interface Outline {
  n: number;
  /** SVG points in pixels of the stored photo (the look's own coordinates). */
  points: Array<[number, number]>;
  tone: OutlineTone;
  /** Where the number badge goes (top-left corner of the box). */
  label: { x: number; y: number };
}

export const TONE_COLOR: Record<OutlineTone, string> = { good: "#16a34a", damaged: "#dc2626", pending: "#2563eb" };

function boxPoints(b: LookInstance["box"]): Array<[number, number]> {
  const [x0, y0, x1, y1] = b;
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
}

/** One outline per instance: its polygon when it has one (3+ points), else its box; colour by damage once final. */
export function outlines(look: Pick<TryLook, "instances" | "final">): Outline[] {
  const final = look.final !== false;
  return look.instances.map((i) => ({
    n: i.n,
    points: i.polygon && i.polygon.length >= 3 ? i.polygon.map(([x, y]) => [x, y] as [number, number]) : boxPoints(i.box),
    tone: !final ? "pending" : i.damaged ? "damaged" : "good",
    label: { x: i.box[0], y: i.box[1] },
  }));
}

export function svgPoints(points: Array<[number, number]>): string {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

/** Badge and stroke sizes that read the same at any photo size (the SVG scales with the photo). */
export function strokeFor(width: number | null | undefined): { stroke: number; badge: number; font: number } {
  const w = width && width > 0 ? width : 1280;
  const stroke = Math.max(2, Math.round(w / 320));
  return { stroke, badge: stroke * 7, font: stroke * 5 };
}

// ------------------------------------------------------------------ what the look found

export interface ItemRow {
  n: number;
  condition: string;
  damaged: boolean;
  label: string;
  flags: string[];
}

function labelText(i: LookInstance, final: boolean): string {
  if (!final) return "Reading…";
  if (!i.label.read) return "Label not read";
  const parts: string[] = [];
  if (i.label.pieces_per_unit != null) parts.push(`${i.label.pieces_per_unit} per pack`);
  if (i.label.batch) parts.push(`batch ${i.label.batch}`);
  if (i.label.expiry) parts.push(`expires ${i.label.expiry}`);
  return parts.length ? parts.join(" · ") : "Label read, no pack size, batch or expiry on it";
}

export function itemRows(look: TryLook): ItemRow[] {
  const final = look.final !== false;
  const packOff = new Map((look.pack?.mismatches ?? []).map((m) => [m.n, m.pieces_per_unit]));
  const flagged = new Map((look.expiry?.flagged ?? []).map((f) => [f.n, f]));
  return look.instances.map((i) => {
    const flags: string[] = [];
    if (packOff.has(i.n) && look.pack) flags.push(`holds ${packOff.get(i.n)}, not ${look.pack.expected_pieces_per_unit}`);
    const f = flagged.get(i.n);
    if (f) flags.push(f.reason === "expired" ? `expired (${f.expiry})` : f.reason === "near" ? `expires within ${look.expiry?.window_days} days (${f.expiry})` : `${f.reason} (${f.expiry})`);
    return {
      n: i.n,
      condition: !final ? "Checking…" : i.damaged ? `Damaged${i.damage_note ? `: ${i.damage_note}` : ""}` : "Good",
      damaged: final && i.damaged,
      label: labelText(i, final),
      flags,
    };
  });
}

/** "pack" -> "packs", "box" -> "boxes" (the look's object noun). */
export function plural(noun: string, n: number): string {
  if (n === 1) return noun;
  return /(s|x|z|ch|sh)$/.test(noun) ? `${noun}es` : `${noun}s`;
}

/** The findings in plain words, in the order the glasses say them. */
export function findings(look: TryLook): string[] {
  const out: string[] = [];
  const c = look.counts;
  if (c.seen == null) out.push("Not counted: say the count instead (rules mode).");
  else out.push(c.expected != null ? `${c.seen} of ${c.expected} ${plural(look.object, c.expected)} seen.` : `${c.seen} ${plural(look.object, c.seen)} seen.`);
  if (look.final === false) {
    out.push("Reading the labels…");
    return out;
  }
  if (c.damaged) out.push(`${c.damaged} damaged.`);
  // Statements about labels need at least one label read (hosted 1 Nov: 0 seen still said "on every label read").
  const read = look.instances.filter((i) => i.label.read).length;
  if (look.pack) {
    const d = look.pack.pieces_difference;
    if (look.pack.mismatches.length) {
      out.push(`${look.pack.mismatches.length} ${plural(look.object, look.pack.mismatches.length)} not ${look.pack.expected_pieces_per_unit} per pack` +
        (d ? `: ${Math.abs(d)} pieces ${d < 0 ? "short" : "over"}.` : "."));
    } else if (read > 0) out.push(`Pack size ${look.pack.expected_pieces_per_unit} on every label read.`);
  }
  if (look.expiry) {
    const near = look.expiry.flagged.filter((f) => f.reason === "near").length;
    const expired = look.expiry.flagged.filter((f) => f.reason === "expired").length;
    if (expired) out.push(`${expired} expired.`);
    if (near) out.push(`${near} expire${near === 1 ? "s" : ""} within ${look.expiry.window_days} days.`);
    if (!near && !expired && read > 0) out.push(`Nothing expires within ${look.expiry.window_days} days.`);
    if (look.expiry.batches.length > 1) out.push(`${look.expiry.batches.length} batches: ${look.expiry.batches.join(", ")}.`);
  }
  const unread = look.instances.filter((i) => !i.label.read).length;
  if (unread && c.seen != null) out.push(`${unread} label${unread === 1 ? "" : "s"} not read.`);
  return out;
}

export function proposalText(look: TryLook): string {
  const p = look.proposal;
  if (p.receive == null || p.flag == null) return look.final === false ? "The proposal comes with the labels." : "No proposal: say your numbers.";
  return `Receive ${p.receive}, flag ${p.flag}${p.reasons.length ? ` (${p.reasons.join("; ")})` : ""}. SAMPLE: nothing is posted.`;
}

// ------------------------------------------------------------------ rules mode, in plain words

const REASON_WORDS: Array<[RegExp, string]> = [
  [/AI_CLOUD_DISABLED/, "cloud AI is switched off on this server"],
  [/AI_TRY_DAILY_CAP/, "today's budget for try looks is used up (it resets at midnight UTC)"],
  [/AI_DAILY_CAP/, "the server's daily AI budget is used up"],
  [/AI_BUDGET_EXHAUSTED/, "the server's AI budget is used up"],
  [/AI_CAP_UNSET|AI_CAP_INVALID/, "the server has no AI budget set"],
  [/AI_PRICE_UNCONFIRMED|AI_PRICE_UNKNOWN/, "the model's price is not confirmed, so the budget guard refused the call"],
  [/AI_NO_KEY/, "the server has no model key"],
  [/AI_TIMEOUT|AI_DEADLINE/, "the model did not answer in time"],
  [/AI_MODEL_PROHIBITED/, "the model is not allowed"],
  [/:no_model$/, "no model is configured"],
  [/AI_HTTP_|AI_TRANSPORT|AI_BAD_RESPONSE/, "the model answered with an error"],
  [/^labels:not_finished$/, "the label read did not finish"],
  [/^image:/, "the photo could not be read"],
];

export function reasonWords(reasons: readonly string[]): string[] {
  const out: string[] = [];
  for (const r of reasons) {
    const hit = REASON_WORDS.find(([re]) => re.test(r));
    const words = hit ? hit[1] : null;
    if (words && !out.includes(words)) out.push(words);
  }
  return out;
}

export interface ModeNotice {
  tone: "warn" | "info";
  title: string;
  body: string;
}

/** What to tell the user when the models did not (fully) answer; null for a full model answer or one in progress. */
export function modeNotice(look: TryLook): ModeNotice | null {
  const why = reasonWords(look.reasons);
  const because = why.length ? `Because ${why.join("; ")}.` : "";
  if (look.source === "rules") {
    return { tone: "warn", title: "Rules mode: no model answered", body: `${because} The look could not count, so it asks for a spoken count. This is what the glasses do without AI.`.trim() };
  }
  if (look.source === "partial" && look.final !== false) {
    return { tone: "info", title: "Counted, but not every label was read", body: `${because} Unread labels are never guessed; the deterministic check uses only what was read.`.trim() };
  }
  return null;
}

// ------------------------------------------------------------------ polling (as the phone does)

export interface PollDeps {
  get: (id: string) => Promise<TryLook>;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
  onUpdate?: (look: TryLook) => void;
  /** Stop early (the user started another look or left the page). */
  cancelled?: () => boolean;
}

/** GET every 1 s until the look is final, for up to 60 s. Returns the last body and whether it is final. */
export async function pollUntilFinal(first: TryLook, deps: PollDeps, intervalMs = POLL_INTERVAL_MS, timeoutMs = POLL_TIMEOUT_MS): Promise<{ look: TryLook; final: boolean }> {
  let look = first;
  if (look.final !== false) return { look, final: true };
  const start = deps.now();
  while (deps.now() - start < timeoutMs) {
    await deps.sleep(intervalMs);
    if (deps.cancelled?.()) return { look, final: false };
    try {
      look = await deps.get(first.look_id);
    } catch {
      continue; // a failed poll is retried on the next tick, within the 60 s
    }
    deps.onUpdate?.(look);
    if (look.final !== false) return { look, final: true };
  }
  return { look, final: false };
}

// ------------------------------------------------------------------ speech (browser speechSynthesis)

/** What the page needs from speechSynthesis: speak one text, resolve when it has been spoken (or failed). */
export interface Voice {
  speak: (text: string) => Promise<void>;
  cancel: () => void;
}

/** Speaks texts one after the other: a text never starts before the previous one ended. */
export function createSpeaker(voice: Voice) {
  let chain: Promise<void> = Promise.resolve();
  const spoken: string[] = [];
  return {
    say(text: string | null | undefined): Promise<void> {
      const t = (text ?? "").trim();
      if (!t) return chain;
      chain = chain.then(() => voice.speak(t).catch(() => undefined)).then(() => {
        spoken.push(t);
      });
      return chain;
    },
    stop() {
      voice.cancel();
      chain = Promise.resolve();
    },
    spoken,
  };
}

/** The second thing to say once the look is final: `say_next` (what follows the count already heard), else `say`. */
export function secondSay(first: TryLook, final: TryLook): string | null {
  if (first.final !== false) return null; // one step: everything was in the first answer
  const next = final.say_next ?? final.say;
  return next && next !== first.say ? next : null;
}

/**
 * The spoken sequence of one look: the first answer at once; then, when the look turns final, `say_next`. If the
 * look is not final within the poll window, nothing more is said (the page shows "still reading").
 */
export async function speakLook(
  first: TryLook,
  waitFinal: () => Promise<{ look: TryLook; final: boolean }>,
  speaker: ReturnType<typeof createSpeaker>,
): Promise<{ look: TryLook; final: boolean }> {
  const firstDone = speaker.say(first.say);
  const result = await waitFinal();
  await firstDone;
  if (result.final) await speaker.say(secondSay(first, result.look));
  return result;
}

/** The longest a text may take to speak before the page moves on: some browsers never fire `onend` (no voice
 * installed, a long utterance cut off), and the next sentence must not wait for ever. About 11 characters a second. */
export function speechBudgetMs(text: string): number {
  return Math.min(30000, 2000 + text.length * 90);
}

/** speechSynthesis as a Voice (browser only; absent in some browsers: the page then shows the text only). */
export function browserVoice(
  synth: SpeechSynthesis | undefined,
  make: (t: string) => SpeechSynthesisUtterance,
  timer: (fn: () => void, ms: number) => unknown = (fn, ms) => setTimeout(fn, ms),
): Voice | null {
  if (!synth) return null;
  return {
    speak: (text) =>
      new Promise<void>((resolve) => {
        let done = false;
        const end = () => {
          if (!done) {
            done = true;
            resolve();
          }
        };
        const u = make(text);
        u.lang = "en-GB";
        u.onend = end;
        u.onerror = end;
        timer(end, speechBudgetMs(text));
        synth.speak(u);
      }),
    cancel: () => synth.cancel(),
  };
}

export function costText(models: TryLook["models"]): string {
  const total = models.reduce((s, m) => s + (Number.isFinite(m.cost_usd) ? m.cost_usd : 0), 0);
  return `$${total.toFixed(4)}`;
}

/** The Look button's words: while the request runs, while labels are read, while the answer is spoken (hosted 1 Nov:
 * it kept saying "Reading the labels…" after the final answer, during the speech). */
export function lookButtonLabel(busy: boolean, look: TryLook | null): string {
  if (!busy) return "Look";
  if (!look) return "Looking…";
  return look.final === false ? "Reading the labels…" : "Speaking the answer…";
}

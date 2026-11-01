/**
 * M5-W01 "Try a look": outlines from a look body, polling as the phone does (1 s, up to 60 s), the spoken sequence
 * (the first answer, then say_next once final), rules-mode wording, the request and file checks, and the client's
 * multipart POST /v1/try/looks. No network, no browser: fetch, clock and speech are injected.
 */
import { describe, expect, test } from "vitest";
import type { TryLook } from "../lib/api";
import { createApiClient } from "../lib/api";
import {
  checkFile,
  createSpeaker,
  findings,
  fitWithin,
  itemRows,
  glassesLines,
  lookButtonLabel,
  modeNotice,
  outlines,
  plural,
  pollUntilFinal,
  proposalText,
  reasonWords,
  browserVoice,
  secondSay,
  speechBudgetMs,
  speakLook,
  strokeFor,
  svgPoints,
  TRY_SAMPLES,
  tryRequest,
  type Voice,
} from "../lib/views/try";
import { scriptedFetch } from "./helpers";

const inst = (n: number, p: Partial<TryLook["instances"][number]> = {}): TryLook["instances"][number] => ({
  n,
  box: [n * 100, 10, n * 100 + 80, 110],
  polygon: null,
  score: 0.9,
  damaged: false,
  damage_note: null,
  label: { read: false },
  ...p,
});

const first = (p: Partial<TryLook> = {}): TryLook => ({
  look_id: "L1",
  source: "partial",
  final: false,
  say: "8 of 8 packs. Reading the labels.",
  say_next: null,
  image: { capture_id: null, width: 1280, height: 960, faces_blurred: 0 },
  instances: [1, 2, 3].map((n) => inst(n)),
  counts: { expected: 8, seen: 8, damaged: null, good: null },
  pack: null,
  expiry: null,
  proposal: { receive: null, flag: null, reasons: [] },
  models: [{ model: "sam-3.1", purpose: "instances", latency_ms: 5000, cost_usd: 0.005, outcome: "ok" }],
  reasons: [],
  case: "grocery",
  object: "pack",
  created_at: "2026-11-01T10:00:00Z",
  kind: "try",
  try: { sample: true, posts: false, photo_url: "/v1/try/looks/L1/photo", photo_expires_at: "2026-11-02T10:00:00Z", photo_kept_hours: 24 },
  ...p,
});

const final = (p: Partial<TryLook> = {}): TryLook =>
  first({
    source: "model",
    final: true,
    say: "8 of 8 packs. 1 damaged. 1 pack holds 4, not 6: 2 pieces short. Receive 7, flag 1?",
    say_next: "1 damaged. 1 pack holds 4, not 6: 2 pieces short. Receive 7, flag 1?",
    instances: [
      inst(1, { label: { read: true, pieces_per_unit: 6 } }),
      inst(2, { damaged: true, damage_note: "torn wrapper", label: { read: true, pieces_per_unit: 6 } }),
      inst(3, { label: { read: true, pieces_per_unit: 4 }, polygon: [[300, 10], [380, 12], [378, 110], [301, 108]] }),
    ],
    counts: { expected: 8, seen: 8, damaged: 1, good: 7 },
    pack: { expected_pieces_per_unit: 6, mismatches: [{ n: 3, pieces_per_unit: 4 }], pieces_difference: -2 },
    proposal: { receive: 7, flag: 1, reasons: ["1 damaged", "1 pack holds 4, not 6: 2 pieces short"] },
    ...p,
  });

describe("outlines from the look body", () => {
  test("a box becomes a rectangle, a polygon is used as it is; blue while reading, then green good / red damaged", () => {
    const pending = outlines(first());
    expect(pending.map((o) => o.tone)).toEqual(["pending", "pending", "pending"]);
    expect(pending[0].points).toEqual([[100, 10], [180, 10], [180, 110], [100, 110]]);
    expect(pending[0].label).toEqual({ x: 100, y: 10 });
    const done = outlines(final());
    expect(done.map((o) => [o.n, o.tone])).toEqual([[1, "good"], [2, "damaged"], [3, "good"]]);
    expect(done[2].points).toEqual([[300, 10], [380, 12], [378, 110], [301, 108]]);
    expect(svgPoints(done[2].points)).toBe("300,10 380,12 378,110 301,108");
  });

  test("a polygon with fewer than 3 points falls back to the box; a body without `final` is final", () => {
    const body = final({ instances: [inst(1, { polygon: [[1, 1], [2, 2]], damaged: true })] });
    delete body.final;
    const [o] = outlines(body);
    expect(o.points).toHaveLength(4);
    expect(o.tone).toBe("damaged");
  });

  test("strokes and badges scale with the photo width", () => {
    expect(strokeFor(1280)).toEqual({ stroke: 4, badge: 28, font: 20 });
    expect(strokeFor(320).stroke).toBe(2);
    expect(strokeFor(null)).toEqual(strokeFor(1280));
  });
});

describe("findings, item rows and the proposal", () => {
  test("the first answer has the count only; the final one damage, pack size, the proposal", () => {
    expect(findings(first())).toEqual(["8 of 8 packs seen.", "Reading the labels…"]);
    expect(proposalText(first())).toBe("The proposal comes with the labels.");
    expect(findings(final())).toEqual(["8 of 8 packs seen.", "1 damaged.", "1 pack not 6 per pack: 2 pieces short."]);
    expect(proposalText(final())).toBe("Receive 7, flag 1 (1 damaged; 1 pack holds 4, not 6: 2 pieces short). SAMPLE: nothing is posted.");
    const rows = itemRows(final());
    expect(rows[1]).toEqual({ n: 2, condition: "Damaged: torn wrapper", damaged: true, label: "6 per pack", flags: [] });
    expect(rows[2].flags).toEqual(["holds 4, not 6"]);
    expect(itemRows(first())[0]).toMatchObject({ condition: "Checking…", label: "Reading…", damaged: false });
  });

  test("pharmacy: batches, expiry window, unread labels; box -> boxes", () => {
    const body = final({
      case: "pharmacy",
      object: "box",
      counts: { expected: 5, seen: 5, damaged: 0, good: 5 },
      pack: null,
      expiry: { window_days: 90, flagged: [{ n: 2, expiry: "2026-12", reason: "near" }], batches: ["B1", "B2"] },
      instances: [inst(1, { label: { read: true, batch: "B1", expiry: "2027-09" } }), inst(2, { label: { read: true, batch: "B2", expiry: "2026-12" } }), inst(3)],
    });
    expect(findings(body)).toEqual(["5 of 5 boxes seen.", "1 expires within 90 days.", "2 batches: B1, B2.", "1 label not read."]);
    expect(itemRows(body)[1].flags).toEqual(["expires within 90 days (2026-12)"]);
    expect(itemRows(body)[0].label).toBe("batch B1 · expires 2027-09");
    expect(itemRows(body)[2].label).toBe("Label not read");
    expect([plural("box", 2), plural("pack", 2), plural("pack", 1)]).toEqual(["boxes", "packs", "pack"]);
  });
});

describe("hosted look of 1 Nov: nothing seen, and the button after the answer", () => {
  test("no label read means no claim about every label or about expiry", () => {
    const none = final({ counts: { expected: 8, seen: 0, damaged: 0, good: 0 }, instances: [], pack: { ...final().pack!, mismatches: [], pieces_difference: 0 } });
    expect(findings(none)).toEqual(["0 of 8 packs seen."]);
    const pharmacyNone = final({ case: "pharmacy", object: "box", counts: { expected: 5, seen: 0, damaged: 0, good: 0 }, pack: null,
      expiry: { window_days: 90, flagged: [], batches: [] }, instances: [] });
    expect(findings(pharmacyNone)).toEqual(["0 of 5 boxes seen."]);
  });

  test("the Look button says what is happening, never reading labels after the final answer", () => {
    expect(lookButtonLabel(false, null)).toBe("Look");
    expect(lookButtonLabel(true, null)).toBe("Looking…");
    expect(lookButtonLabel(true, first())).toBe("Reading the labels…");
    expect(lookButtonLabel(true, final())).toBe("Speaking the answer…");
  });
});

describe("the glasses-say box follows the look, not the speech", () => {
  test("first answer, then the final answer at once even if nothing more was spoken yet", () => {
    expect(glassesLines(first(), [])).toEqual([first().say]);
    const fin = final({ say_next: "1 damaged. Receive 7, flag 1?" });
    expect(glassesLines(fin, [first().say])).toEqual([first().say, "1 damaged. Receive 7, flag 1?"]);
    expect(glassesLines(fin, [])).toEqual([fin.say]);
    expect(glassesLines(final({ say_next: null }), [])).toEqual([final({ say_next: null }).say]);
  });
});

describe("rules mode in plain words", () => {
  test("the server's reasons become a notice: budget, model off, try cap", () => {
    const rules = final({ source: "rules", instances: [], counts: { expected: 8, seen: null, damaged: null, good: null },
      reasons: ["instances:sam-3.1:AI_TRY_DAILY_CAP"], say: "I couldn't count them this time. Say the count, for example: receive, then the number." });
    const n = modeNotice(rules);
    expect(n?.tone).toBe("warn");
    expect(n?.title).toBe("Rules mode: no model answered");
    expect(n?.body).toContain("today's budget for try looks is used up");
    expect(findings(rules)[0]).toBe("Not counted: say the count instead (rules mode).");
    expect(reasonWords(["instances:sam-3.1:AI_CLOUD_DISABLED"])).toEqual(["cloud AI is switched off on this server"]);
    expect(reasonWords(["labels:muse-spark-1.3:AI_PRICE_UNCONFIRMED", "labels:x:AI_PRICE_UNCONFIRMED"])).toHaveLength(1);
    expect(reasonWords(["instances:no_model"])).toEqual(["no model is configured"]);
    expect(modeNotice(final())).toBeNull();
    expect(modeNotice(first())).toBeNull(); // partial while reading is not a notice
    expect(modeNotice(final({ source: "partial", reasons: ["labels:muse-spark-1.3:AI_TIMEOUT"] }))?.title).toBe("Counted, but not every label was read");
  });
});

describe("request and file checks", () => {
  test("C1 needs pieces per pack, C2 an expiry window; whole numbers in range", () => {
    expect(tryRequest("grocery", 8, { pieces: 6 })).toEqual({ ok: true, request: { case: "grocery", expected_units: 8, pieces_per_unit: 6 } });
    expect(tryRequest("pharmacy", 5, { windowDays: 90 })).toEqual({ ok: true, request: { case: "pharmacy", expected_units: 5, window_days: 90 } });
    expect(tryRequest("grocery", 0, { pieces: 6 }).ok).toBe(false);
    expect(tryRequest("grocery", 8.5, { pieces: 6 }).ok).toBe(false);
    expect(tryRequest("grocery", 8, { pieces: null }).ok).toBe(false);
    expect(tryRequest("pharmacy", 5, { windowDays: -1 }).ok).toBe(false);
    expect(tryRequest("pharmacy", 5, { windowDays: Number.NaN }).ok).toBe(false);
  });

  test("JPEG or PNG up to 5 MB; scaled to 1600 px on the long side, never up", () => {
    expect(checkFile({ type: "image/jpeg", size: 1000 })).toBeNull();
    expect(checkFile({ type: "image/png", size: 5 * 1024 * 1024 })).toBeNull();
    expect(checkFile({ type: "image/png", size: 5 * 1024 * 1024 + 1 })).toMatch(/5 MB/);
    expect(checkFile({ type: "image/gif", size: 10 })).toMatch(/JPEG or PNG/);
    expect(checkFile({ type: "image/heic", size: 10 })).toMatch(/JPEG or PNG/);
    expect(fitWithin(4000, 3000)).toEqual({ width: 1600, height: 1200, scale: 0.4 });
    expect(fitWithin(1200, 3200)).toEqual({ width: 600, height: 1600, scale: 0.5 });
    expect(fitWithin(1280, 960)).toEqual({ width: 1280, height: 960, scale: 1 });
    expect(TRY_SAMPLES.map((s) => [s.case, s.src])).toEqual([["grocery", "/samples/c1-grocery.jpg"], ["pharmacy", "/samples/c2-pharmacy.jpg"]]);
  });
});

/** A fake clock: sleep advances it, no real waiting. */
function clock() {
  let t = 0;
  return { now: () => t, sleep: async (ms: number) => { t += ms; } };
}

describe("polling as the phone does", () => {
  test("GET every 1 s until final; updates on the way", async () => {
    const c = clock();
    const answers = [first(), first(), final()];
    const seen: Array<boolean | undefined> = [];
    const calls: number[] = [];
    const r = await pollUntilFinal(first(), {
      get: async () => { calls.push(c.now()); return answers.shift()!; },
      ...c,
      onUpdate: (l) => seen.push(l.final),
    });
    expect(r.final).toBe(true);
    expect(r.look.say_next).toMatch(/^1 damaged/);
    expect(calls).toEqual([1000, 2000, 3000]);
    expect(seen).toEqual([false, false, true]);
  });

  test("gives up after 60 s, retries a failed GET, stops when cancelled, and does not poll a final look", async () => {
    const c = clock();
    let n = 0;
    const r = await pollUntilFinal(first(), { get: async () => { n++; if (n === 3) throw new Error("net"); return first(); }, ...c });
    expect(r.final).toBe(false);
    expect(n).toBe(60);
    expect(c.now()).toBe(60000);
    let asked = 0;
    const cancelled = await pollUntilFinal(first(), { get: async () => { asked++; return first(); }, ...clock(), cancelled: () => true });
    expect(cancelled.final).toBe(false);
    expect(asked).toBe(0);
    const once = await pollUntilFinal(final(), { get: async () => { throw new Error("must not be called"); }, ...clock() });
    expect(once.final).toBe(true);
  });
});

/** A fake voice: records start/end order; each text "speaks" until released. */
function fakeVoice() {
  const log: string[] = [];
  const pending: Array<() => void> = [];
  const voice: Voice = {
    speak: (t) => new Promise<void>((resolve) => { log.push(`start:${t}`); pending.push(() => { log.push(`end:${t}`); resolve(); }); }),
    cancel: () => log.push("cancel"),
  };
  const finishNext = async () => { await Promise.resolve(); pending.shift()?.(); await new Promise((r) => setTimeout(r, 0)); };
  return { voice, log, finishNext };
}

describe("speech sequencing", () => {
  test("the first answer at once, say_next only after the first ended and the look is final", async () => {
    const { voice, log, finishNext } = fakeVoice();
    const speaker = createSpeaker(voice);
    let release: (v: { look: TryLook; final: boolean }) => void = () => undefined;
    const waiting = new Promise<{ look: TryLook; final: boolean }>((r) => { release = r; });
    const done = speakLook(first(), () => waiting, speaker);
    await new Promise((r) => setTimeout(r, 0));
    expect(log).toEqual(["start:8 of 8 packs. Reading the labels."]);
    release({ look: final(), final: true }); // final before the first sentence ended: the second still waits
    await new Promise((r) => setTimeout(r, 0));
    expect(log).toHaveLength(1);
    await finishNext();
    expect(log[2]).toBe("start:1 damaged. 1 pack holds 4, not 6: 2 pieces short. Receive 7, flag 1?");
    await finishNext();
    await done;
    expect(speaker.spoken).toEqual(["8 of 8 packs. Reading the labels.", "1 damaged. 1 pack holds 4, not 6: 2 pieces short. Receive 7, flag 1?"]);
  });

  test("one-step look: spoken once; not final within 60 s: nothing more; say_next missing: the final say", async () => {
    expect(secondSay(final(), final())).toBeNull();
    expect(secondSay(first(), final({ say_next: null }))).toBe(final().say);
    expect(secondSay(first(), final({ say_next: null, say: first().say }))).toBeNull();
    const { voice, finishNext } = fakeVoice();
    const speaker = createSpeaker(voice);
    const p = speakLook(first(), async () => ({ look: first(), final: false }), speaker);
    await finishNext();
    await p;
    expect(speaker.spoken).toEqual(["8 of 8 packs. Reading the labels."]);
  });

  test("a voice that fails does not block the next text; empty texts are skipped", async () => {
    const said: string[] = [];
    const speaker = createSpeaker({ speak: async (t) => { said.push(t); if (t === "a") throw new Error("no voice"); }, cancel: () => undefined });
    await speaker.say("a");
    await speaker.say("  ");
    await speaker.say(null);
    await speaker.say("b");
    expect(said).toEqual(["a", "b"]);
    expect(speaker.spoken).toEqual(["a", "b"]);
  });
});

describe("the browser voice", () => {
  test("resolves on onend, on onerror, or after the time budget when the browser never ends the utterance", async () => {
    const timers: Array<{ fn: () => void; ms: number }> = [];
    const spoken: Array<{ text: string; lang: string; onend: (() => void) | null; onerror: (() => void) | null }> = [];
    const synth = { speak: (u: (typeof spoken)[number]) => spoken.push(u), cancel: () => undefined } as unknown as SpeechSynthesis;
    const make = (text: string) => ({ text, lang: "", onend: null, onerror: null }) as unknown as SpeechSynthesisUtterance;
    const voice = browserVoice(synth, make, (fn, ms) => timers.push({ fn, ms }))!;
    let a = false;
    const pa = voice.speak("8 of 8 packs.").then(() => { a = true; });
    expect(spoken[0].lang).toBe("en-GB");
    spoken[0].onend?.();
    await pa;
    expect(a).toBe(true);
    let b = false;
    const pb = voice.speak("Receive 7, flag 1?").then(() => { b = true; });
    await Promise.resolve();
    expect(b).toBe(false); // the browser never fires onend
    expect(timers[1].ms).toBe(speechBudgetMs("Receive 7, flag 1?"));
    timers[1].fn();
    await pb;
    expect(b).toBe(true);
    timers[0].fn(); // a late timer after onend changes nothing
    expect(browserVoice(undefined, make)).toBeNull();
    expect(speechBudgetMs("x".repeat(1000))).toBe(30000);
  });
});

describe("the client", () => {
  test("POST /v1/try/looks is multipart (photo + look JSON) with an Idempotency-Key and no JSON content type", async () => {
    const { fetchImpl } = scriptedFetch([{ status: 200, body: first() }, { status: 200, body: final() }]);
    const raw: Array<{ url: string; init?: RequestInit }> = [];
    const api = createApiClient({
      fetch: (url, init) => { raw.push({ url, init }); return fetchImpl(url, { ...init, body: undefined }); },
      baseUrl: "",
      coreBaseUrl: "/dev-core",
      getToken: () => "tok",
      idempotencyKey: () => "key-1",
    });
    const body = await api.createTryLook(new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" }), { case: "grocery", expected_units: 8, pieces_per_unit: 6 }, "c1.jpg");
    expect(body.look_id).toBe("L1");
    const sent = raw[0];
    expect(sent.url).toBe("/v1/try/looks");
    const headers = sent.init?.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBe("key-1");
    expect(headers.Authorization).toBe("Bearer tok");
    expect(headers["Content-Type"]).toBeUndefined();
    const form = sent.init?.body as FormData;
    expect(JSON.parse(String(form.get("look")))).toEqual({ case: "grocery", expected_units: 8, pieces_per_unit: 6 });
    expect((form.get("photo") as File).name).toBe("c1.jpg");
    expect((await api.getTryLook("L1")).final).toBe(true);
    expect(raw[1].url).toBe("/v1/try/looks/L1");
  });

  test("429 keeps the server's words (Retry-After seconds are in the detail); 415 / 413 are plain errors", async () => {
    const { fetchImpl } = scriptedFetch([
      { status: 429, body: { code: "FIELD-TRY-429-RATE", title: "Too many try looks", detail: "10 try looks per hour; try again in 1200 seconds." } },
      { status: 415, body: { code: "FIELD-TRY-415-TYPE", title: "The photo must be a JPEG or PNG image" } },
    ]);
    const api = createApiClient({ fetch: (u, i) => fetchImpl(u, { ...i, body: undefined }), baseUrl: "", coreBaseUrl: "", getToken: () => null });
    const blob = new Blob([new Uint8Array([1])]);
    await expect(api.createTryLook(blob, { case: "pharmacy", expected_units: 5, window_days: 90 })).rejects.toMatchObject({
      status: 429, code: "FIELD-TRY-429-RATE", title: "Too many try looks", detail: "10 try looks per hour; try again in 1200 seconds.",
    });
    await expect(api.createTryLook(blob, { case: "pharmacy", expected_units: 5, window_days: 90 })).rejects.toMatchObject({ status: 415, title: "The photo must be a JPEG or PNG image" });
  });
});

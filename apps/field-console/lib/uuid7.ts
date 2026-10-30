/**
 * UUIDv7 (RFC 9562) for Idempotency-Key headers (contract §1: every write carries a UUIDv7).
 * 48-bit Unix milliseconds, version 7, variant 10, 74 random bits.
 */
export type RandomFill = (bytes: Uint8Array) => Uint8Array;

const defaultRandom: RandomFill = (bytes) => globalThis.crypto.getRandomValues(bytes);

export function uuid7(nowMs: number = Date.now(), random: RandomFill = defaultRandom): string {
  const b = random(new Uint8Array(16));
  let ms = Math.max(0, Math.floor(nowMs));
  for (let i = 5; i >= 0; i--) {
    b[i] = ms % 256;
    ms = Math.floor(ms / 256);
  }
  b[6] = (b[6] & 0x0f) | 0x70;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export const UUID7_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

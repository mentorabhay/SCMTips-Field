/**
 * A small QR Code Model 2 encoder (ISO/IEC 18004) for the console's "Sign in your phone" page (M5-L03).
 * Byte mode (UTF-8), error correction level M, versions 1 to 10 (up to 213 bytes; the pairing App Link is about
 * 45). Written here because the lockfile has no QR library and the contract allows no new dependency.
 *
 * Steps: data bits (mode 0100, count, bytes, terminator, pad bytes 0xEC 0x11) -> blocks with Reed-Solomon error
 * correction over GF(256) (polynomial 0x11D) -> interleaved codewords -> zigzag placement around the function
 * patterns -> each of the 8 masks scored by the four penalty rules, the lowest kept -> format bits (BCH 0x537, XOR
 * 0x5412) and, from version 7, version bits (BCH 0x1F25).
 *
 * `modules[y][x]` is true for a dark module. The quiet zone (4 light modules) is added only when drawing.
 */

export const QR_MIN_VERSION = 1;
export const QR_MAX_VERSION = 10;
export const QR_QUIET_ZONE = 4;

/** Error correction codewords per block, level M, index = version. */
const EC_PER_BLOCK_M = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26] as const;
/** Error correction blocks, level M, index = version. */
const BLOCKS_M = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5] as const;
/** Format-bit value of level M (L = 01, M = 00, Q = 11, H = 10). */
const ECL_M_BITS = 0b00;

export interface QrMatrix {
  version: number;
  mask: number;
  size: number;
  modules: boolean[][];
}

export class QrTooLongError extends Error {
  constructor(readonly bytes: number) {
    super(`The text is ${bytes} bytes; a version ${QR_MAX_VERSION} QR code at level M holds at most ${byteCapacity(QR_MAX_VERSION)}.`);
  }
}

// ------------------------------------------------------------------ sizes

export function sizeOf(version: number): number {
  return version * 4 + 17;
}

/** Modules left for data and error correction once the function patterns are drawn. */
function rawDataModules(version: number): number {
  let n = (16 * version + 128) * version + 64;
  if (version >= 2) {
    const align = Math.floor(version / 7) + 2;
    n -= (25 * align - 10) * align - 55;
    if (version >= 7) n -= 36;
  }
  return n;
}

export function totalCodewords(version: number): number {
  return Math.floor(rawDataModules(version) / 8);
}

export function dataCodewords(version: number): number {
  return totalCodewords(version) - EC_PER_BLOCK_M[version]! * BLOCKS_M[version]!;
}

function countBits(version: number): number {
  return version <= 9 ? 8 : 16;
}

/** The most bytes a version holds in byte mode at level M. */
export function byteCapacity(version: number): number {
  return Math.floor((dataCodewords(version) * 8 - 4 - countBits(version)) / 8);
}

/** Alignment pattern centres (one axis) for a version; empty for version 1. */
export function alignmentPositions(version: number): number[] {
  if (version === 1) return [];
  const n = Math.floor(version / 7) + 2;
  const step = Math.ceil((version * 4 + 4) / (n * 2 - 2)) * 2;
  const out = [6];
  for (let pos = sizeOf(version) - 7; out.length < n; pos -= step) out.splice(1, 0, pos);
  return out;
}

// ------------------------------------------------------------------ Reed-Solomon over GF(256)

function gfMul(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

/** Coefficients (highest first, leading 1 dropped) of prod_{i<degree} (x - alpha^i). */
export function rsGenerator(degree: number): number[] {
  const g = new Array<number>(degree).fill(0);
  g[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      g[j] = gfMul(g[j]!, root);
      if (j + 1 < degree) g[j] ^= g[j + 1]!;
    }
    root = gfMul(root, 0x02);
  }
  return g;
}

/** The error correction codewords of one block. */
export function rsRemainder(data: readonly number[], generator: readonly number[]): number[] {
  const r = new Array<number>(generator.length).fill(0);
  for (const b of data) {
    const factor = b ^ r.shift()!;
    r.push(0);
    for (let i = 0; i < generator.length; i++) r[i] ^= gfMul(generator[i]!, factor);
  }
  return r;
}

/** Evaluates a codeword polynomial (highest first) at x; a valid block is 0 at alpha^0..alpha^(ec-1). */
export function gfEval(poly: readonly number[], x: number): number {
  let y = 0;
  for (const c of poly) y = gfMul(y, x) ^ c;
  return y;
}

export function gfPow2(n: number): number {
  let v = 1;
  for (let i = 0; i < n; i++) v = gfMul(v, 0x02);
  return v;
}

// ------------------------------------------------------------------ data codewords

/** Mode, count, bytes, terminator and padding: exactly dataCodewords(version) bytes. */
export function dataBytes(bytes: Uint8Array, version: number): number[] {
  const bits: number[] = [];
  const put = (value: number, len: number) => {
    for (let i = len - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  put(0b0100, 4);
  put(bytes.length, countBits(version));
  for (const b of bytes) put(b, 8);
  const capacity = dataCodewords(version) * 8;
  put(0, Math.min(4, capacity - bits.length));
  put(0, (8 - (bits.length % 8)) % 8);
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) put(pad, 8);
  const out: number[] = [];
  for (let i = 0; i < bits.length; i += 8) out.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  return out;
}

/** The data split into blocks (short ones first), each followed by its error correction; then interleaved. */
export function blocksOf(data: readonly number[], version: number): { data: number[]; ec: number[] }[] {
  const nBlocks = BLOCKS_M[version]!;
  const ecLen = EC_PER_BLOCK_M[version]!;
  const total = totalCodewords(version);
  const shortLen = Math.floor(total / nBlocks) - ecLen;
  const nShort = nBlocks - (total % nBlocks);
  const gen = rsGenerator(ecLen);
  const out: { data: number[]; ec: number[] }[] = [];
  for (let i = 0, k = 0; i < nBlocks; i++) {
    const len = shortLen + (i < nShort ? 0 : 1);
    const d = data.slice(k, k + len);
    k += len;
    out.push({ data: d, ec: rsRemainder(d, gen) });
  }
  return out;
}

export function interleave(blocks: readonly { data: number[]; ec: number[] }[]): number[] {
  const out: number[] = [];
  const maxData = Math.max(...blocks.map((b) => b.data.length));
  for (let i = 0; i < maxData; i++) for (const b of blocks) if (i < b.data.length) out.push(b.data[i]!);
  const ecLen = blocks[0]!.ec.length;
  for (let i = 0; i < ecLen; i++) for (const b of blocks) out.push(b.ec[i]!);
  return out;
}

// ------------------------------------------------------------------ format and version bits

/** 15 format bits for level M and a mask. */
export function formatBits(mask: number): number {
  const data = (ECL_M_BITS << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | rem) ^ 0x5412;
}

/** 18 version bits (versions 7 and above). */
export function versionBits(version: number): number {
  let rem = version;
  for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
  return (version << 12) | rem;
}

// ------------------------------------------------------------------ the grid

class Grid {
  readonly size: number;
  readonly dark: boolean[][];
  readonly fn: boolean[][];

  constructor(readonly version: number) {
    this.size = sizeOf(version);
    this.dark = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
    this.fn = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
  }

  setFn(x: number, y: number, dark: boolean) {
    this.dark[y]![x] = dark;
    this.fn[y]![x] = true;
  }

  drawFunctionPatterns() {
    const s = this.size;
    for (let i = 0; i < s; i++) {
      this.setFn(6, i, i % 2 === 0);
      this.setFn(i, 6, i % 2 === 0);
    }
    this.finder(3, 3);
    this.finder(s - 4, 3);
    this.finder(3, s - 4);
    const pos = alignmentPositions(this.version);
    const last = pos.length - 1;
    for (let i = 0; i < pos.length; i++) {
      for (let j = 0; j < pos.length; j++) {
        if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) continue;
        this.alignment(pos[i]!, pos[j]!);
      }
    }
    this.drawFormat(0); // reserves the format areas; redrawn with the chosen mask
    this.drawVersion();
  }

  private finder(cx: number, cy: number) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const d = Math.max(Math.abs(dx), Math.abs(dy));
        const x = cx + dx;
        const y = cy + dy;
        if (x >= 0 && x < this.size && y >= 0 && y < this.size) this.setFn(x, y, d !== 2 && d !== 4);
      }
    }
  }

  private alignment(cx: number, cy: number) {
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) this.setFn(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }

  drawFormat(mask: number) {
    const bits = formatBits(mask);
    const bit = (i: number) => ((bits >>> i) & 1) === 1;
    const s = this.size;
    for (let i = 0; i <= 5; i++) this.setFn(8, i, bit(i));
    this.setFn(8, 7, bit(6));
    this.setFn(8, 8, bit(7));
    this.setFn(7, 8, bit(8));
    for (let i = 9; i < 15; i++) this.setFn(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) this.setFn(s - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) this.setFn(8, s - 15 + i, bit(i));
    this.setFn(8, s - 8, true); // the dark module
  }

  private drawVersion() {
    if (this.version < 7) return;
    const bits = versionBits(this.version);
    for (let i = 0; i < 18; i++) {
      const dark = ((bits >>> i) & 1) === 1;
      const a = this.size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      this.setFn(a, b, dark);
      this.setFn(b, a, dark);
    }
  }

  drawCodewords(codewords: readonly number[]) {
    const s = this.size;
    let i = 0;
    for (let right = s - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      const upward = ((right + 1) & 2) === 0;
      for (let v = 0; v < s; v++) {
        const y = upward ? s - 1 - v : v;
        for (let j = 0; j < 2; j++) {
          const x = right - j;
          if (this.fn[y]![x]) continue;
          if (i < codewords.length * 8) {
            this.dark[y]![x] = ((codewords[i >>> 3]! >>> (7 - (i & 7))) & 1) === 1;
            i++;
          }
        }
      }
    }
  }

  applyMask(mask: number) {
    for (let y = 0; y < this.size; y++) {
      for (let x = 0; x < this.size; x++) {
        if (!this.fn[y]![x] && maskBit(mask, x, y)) this.dark[y]![x] = !this.dark[y]![x];
      }
    }
  }
}

/** True where mask `mask` flips the module at column x, row y. */
export function maskBit(mask: number, x: number, y: number): boolean {
  switch (mask) {
    case 0: return (x + y) % 2 === 0;
    case 1: return y % 2 === 0;
    case 2: return x % 3 === 0;
    case 3: return (x + y) % 3 === 0;
    case 4: return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
    case 5: return ((x * y) % 2) + ((x * y) % 3) === 0;
    case 6: return (((x * y) % 2) + ((x * y) % 3)) % 2 === 0;
    case 7: return (((x + y) % 2) + ((x * y) % 3)) % 2 === 0;
    default: throw new RangeError(`mask ${mask}`);
  }
}

// ------------------------------------------------------------------ penalty (mask choice)

const FINDER_LIKE = [true, false, true, true, true, false, true];

/** The four penalty rules of ISO/IEC 18004 §7.8.3 (N1 = 3, N2 = 3, N3 = 40, N4 = 10); outside the grid is light. */
export function penalty(m: readonly (readonly boolean[])[]): number {
  const s = m.length;
  const at = (x: number, y: number) => (x >= 0 && y >= 0 && x < s && y < s ? m[y]![x]! : false);
  let score = 0;
  for (const horizontal of [true, false]) {
    for (let a = 0; a < s; a++) {
      const get = (b: number) => (horizontal ? at(b, a) : at(a, b));
      let run = 1;
      for (let b = 1; b <= s; b++) {
        if (b < s && get(b) === get(b - 1)) run++;
        else {
          if (run >= 5) score += 3 + (run - 5);
          run = 1;
        }
      }
      for (let b = -4; b < s; b++) {
        if (!FINDER_LIKE.every((v, k) => get(b + k) === v)) continue;
        const lightBefore = [1, 2, 3, 4].every((k) => !get(b - k));
        const lightAfter = [7, 8, 9, 10].every((k) => !get(b + k));
        if (lightBefore) score += 40;
        if (lightAfter) score += 40;
      }
    }
  }
  for (let y = 0; y + 1 < s; y++) {
    for (let x = 0; x + 1 < s; x++) {
      const c = at(x, y);
      if (at(x + 1, y) === c && at(x, y + 1) === c && at(x + 1, y + 1) === c) score += 3;
    }
  }
  let dark = 0;
  for (const row of m) for (const v of row) if (v) dark++;
  const total = s * s;
  score += Math.floor(Math.abs(dark * 20 - total * 10) / total) * 10;
  return score;
}

// ------------------------------------------------------------------ encode

export interface EncodeOptions {
  /** Force a mask (0..7); default: the lowest penalty. */
  mask?: number;
  /** The smallest version to use (1..10); default 1. */
  minVersion?: number;
}

export function utf8(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

/** The smallest version (from minVersion) that holds `bytes`, or null when even version 10 is too small. */
export function versionFor(length: number, minVersion = QR_MIN_VERSION): number | null {
  for (let v = Math.max(QR_MIN_VERSION, minVersion); v <= QR_MAX_VERSION; v++) if (byteCapacity(v) >= length) return v;
  return null;
}

/** The QR code of a text in byte mode, level M. Throws QrTooLongError above version 10's capacity. */
export function encodeQr(text: string, options: EncodeOptions = {}): QrMatrix {
  const bytes = utf8(text);
  const version = versionFor(bytes.length, options.minVersion);
  if (version === null) throw new QrTooLongError(bytes.length);
  if (options.mask !== undefined && !(Number.isInteger(options.mask) && options.mask >= 0 && options.mask <= 7)) {
    throw new RangeError(`mask ${options.mask}`);
  }
  const codewords = interleave(blocksOf(dataBytes(bytes, version), version));
  const grid = new Grid(version);
  grid.drawFunctionPatterns();
  grid.drawCodewords(codewords);

  let mask = options.mask ?? -1;
  if (mask < 0) {
    let best = Infinity;
    for (let k = 0; k < 8; k++) {
      grid.applyMask(k);
      grid.drawFormat(k);
      const p = penalty(grid.dark);
      if (p < best) {
        best = p;
        mask = k;
      }
      grid.applyMask(k); // XOR again: undone
    }
  }
  grid.applyMask(mask);
  grid.drawFormat(mask);
  return { version, mask, size: grid.size, modules: grid.dark };
}

/** One SVG path (`M x y h1 v1 h-1 z` per dark module, merged along rows) with the quiet zone as offset. */
export function qrSvgPath(qr: QrMatrix, quiet = QR_QUIET_ZONE): string {
  const parts: string[] = [];
  qr.modules.forEach((row, y) => {
    for (let x = 0; x < qr.size; x++) {
      if (!row[x]) continue;
      let w = 1;
      while (x + w < qr.size && row[x + w]) w++;
      parts.push(`M${x + quiet} ${y + quiet}h${w}v1h-${w}z`);
      x += w - 1;
    }
  });
  return parts.join("");
}

/** Rows as strings of '1' (dark) and '0' (light), for tests and debugging. */
export function qrRows(qr: QrMatrix): string[] {
  return qr.modules.map((row) => row.map((v) => (v ? "1" : "0")).join(""));
}

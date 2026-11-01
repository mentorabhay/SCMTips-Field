/**
 * M5-L03: the console's QR encoder (lib/qr.ts), byte mode, level M, versions 1-10.
 *
 * The fixed matrices below were produced by an independent reference, Project Nayuki's qrcodegen (Python, 1.8.0,
 * `QrCode.encode_segments([QrSegment.make_bytes(...)], Ecc.MEDIUM, v, v, mask, boost_ecl=False)`), and are frozen
 * here. While building, 110 (text, version, mask) cases were also matched module for module against qrcodegen and
 * the `qrcode` package, and every one was read back by the zxing-cpp decoder (see the M5-L03 ledger note).
 */
import { createHash } from "node:crypto";
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import {
  alignmentPositions,
  blocksOf,
  byteCapacity,
  dataBytes,
  dataCodewords,
  encodeQr,
  formatBits,
  gfEval,
  gfPow2,
  QR_MAX_VERSION,
  QR_QUIET_ZONE,
  qrRows,
  qrSvgPath,
  QrTooLongError,
  totalCodewords,
  utf8,
  versionBits,
} from "../lib/qr";

/** qrcodegen: "HELLO", version 1, mask 5. */
const HELLO_V1_M5 = [
  "111111100010001111111",
  "100000101110101000001",
  "101110101100001011101",
  "101110101100101011101",
  "101110100100101011101",
  "100000100011001000001",
  "111111101010101111111",
  "000000001000000000000",
  "100000101011011001110",
  "010101011001110111101",
  "001111101000101101110",
  "011110000011111101100",
  "001100100011111111110",
  "000000001110100001000",
  "111111100111010010110",
  "100000100100001001111",
  "101110100101010010110",
  "101110100001111001000",
  "101110100111110111111",
  "100000100011111111100",
  "111111101100100010110",
];

/** qrcodegen: the pairing App Link "https://app.scmtips.com/pair?code=AB12CD34" (42 bytes), version 3, mask 2; rows in hex. */
const LINK = "https://app.scmtips.com/pair?code=AB12CD34";
const LINK_V3_M2_HEX = [
  "1fcf4f7f", "104d2141", "1751435d", "1755ae5d", "17587f5d", "105ab941", "1fd5557f", "00102200", "17c0687c", "1b8e3371",
  "1249b480", "1e07776a", "17565a0c", "122306d1", "1cc8759c", "1e1a3252", "03e9a92c", "11845ff5", "13dca454", "149a7012",
  "13dda9f7", "001b531f", "1fc37f5c", "105f1713", "175f0df7", "17589a2f", "175ef97e", "104f813a", "1fd26a94",
];

/** qrcodegen, SHA-256 of the rows joined by "\n": larger versions (version bits from 7, a 16-bit count at 10), UTF-8. */
const DIGESTS: [string, number, number, string][] = [
  ["x".repeat(100), 7, 4, "a8dc048f49c010489a21d431eb2d11efa8e4ba860ad0aeaae6c9bb4debba5402"],
  ["z".repeat(200), 10, 7, "9c109fe4f06e12934dfca428773493356fb90f8e27ce4605913f4171fd831395"],
  ["München 🙂", 1, 0, "62d17522712b61aeada9aef41977fb89284d517301f7841fed89a040e694c054"],
];

const hexRows = (rows: string[]) => rows.map((r) => parseInt(r, 2).toString(16).padStart(Math.ceil(r.length / 4), "0"));
const digest = (rows: string[]) => createHash("sha256").update(rows.join("\n")).digest("hex");

describe("M5-L03 QR encoder: matches the reference implementation", () => {
  test("HELLO, version 1, mask 5 equals the reference matrix", () => {
    const qr = encodeQr("HELLO", { mask: 5 });
    expect(qr.version).toBe(1);
    expect(qr.size).toBe(21);
    expect(qrRows(qr)).toEqual(HELLO_V1_M5);
  });

  test("the pairing App Link, version 3, mask 2 equals the reference matrix", () => {
    const qr = encodeQr(LINK, { mask: 2 });
    expect(LINK.length).toBe(42);
    expect(qr.version).toBe(3);
    expect(hexRows(qrRows(qr))).toEqual(LINK_V3_M2_HEX);
  });

  test("versions 7 and 10 and UTF-8 text equal the reference matrices", () => {
    for (const [text, version, mask, sha] of DIGESTS) {
      const qr = encodeQr(text, { mask, minVersion: version });
      expect(qr.version).toBe(version);
      expect(digest(qrRows(qr))).toBe(sha);
    }
  });
});

describe("M5-L03 QR encoder: structure", () => {
  test("level M capacities and codeword counts per version (ISO/IEC 18004 table 7)", () => {
    expect([1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(byteCapacity)).toEqual([14, 26, 42, 62, 84, 106, 122, 152, 180, 213]);
    expect([1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(totalCodewords)).toEqual([26, 44, 70, 100, 134, 172, 196, 242, 292, 346]);
    expect([1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(dataCodewords)).toEqual([16, 28, 44, 64, 86, 108, 124, 154, 182, 216]);
    expect(alignmentPositions(1)).toEqual([]);
    expect(alignmentPositions(2)).toEqual([6, 18]);
    expect(alignmentPositions(7)).toEqual([6, 22, 38]);
    expect(alignmentPositions(10)).toEqual([6, 28, 50]);
  });

  test("format and version bits (ISO/IEC 18004 annex C and D)", () => {
    // level M, masks 0..7 (ISO/IEC 18004 table C.1)
    expect([0, 1, 2, 3, 4, 5, 6, 7].map((k) => formatBits(k).toString(2).padStart(15, "0"))).toEqual([
      "101010000010010", "101000100100101", "101111001111100", "101101101001011",
      "100010111111001", "100000011001110", "100111110010111", "100101010100000",
    ]);
    expect(versionBits(7).toString(16)).toBe("7c94");
    expect(versionBits(10).toString(16)).toBe("a4d3");
  });

  test("data codewords: mode, count, terminator, pad bytes", () => {
    expect(dataBytes(utf8("HELLO"), 1)).toEqual([0x40, 0x54, 0x84, 0x54, 0xc4, 0xc4, 0xf0, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11, 0xec]);
  });

  test("the smallest version that holds the text; above version 10 is refused", () => {
    expect(encodeQr("x".repeat(14)).version).toBe(1);
    expect(encodeQr("x".repeat(15)).version).toBe(2);
    expect(encodeQr("x".repeat(213)).version).toBe(10);
    expect(() => encodeQr("x".repeat(214))).toThrow(QrTooLongError);
    expect(encodeQr(LINK).version).toBe(3);
    expect(() => encodeQr("x", { mask: 8 })).toThrow(RangeError);
  });

  test("the SVG path draws every dark module once, offset by the quiet zone", () => {
    const qr = encodeQr("HELLO", { mask: 5 });
    const path = qrSvgPath(qr);
    let drawn = 0;
    for (const m of path.matchAll(/M(\d+) (\d+)h(\d+)v1h-(\d+)z/g)) {
      const [x, y, w] = [Number(m[1]), Number(m[2]), Number(m[3])];
      expect(Number(m[4])).toBe(w);
      for (let i = 0; i < w; i++) expect(qr.modules[y - QR_QUIET_ZONE]![x - QR_QUIET_ZONE + i]).toBe(true);
      drawn += w;
    }
    expect(drawn).toBe(qr.modules.flat().filter(Boolean).length);
  });
});

describe("M5-L03 QR encoder: properties", () => {
  test("property: every block's Reed-Solomon codeword is a multiple of the generator (zero syndromes)", () => {
    fc.assert(
      fc.property(fc.uint8Array({ minLength: 0, maxLength: byteCapacity(QR_MAX_VERSION) }), (bytes) => {
        const version = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].find((v) => byteCapacity(v) >= bytes.length)!;
        const data = dataBytes(bytes, version);
        expect(data).toHaveLength(dataCodewords(version));
        for (const b of blocksOf(data, version)) {
          const word = [...b.data, ...b.ec];
          for (let i = 0; i < b.ec.length; i++) expect(gfEval(word, gfPow2(i))).toBe(0);
        }
      }),
      { numRuns: 150 },
    );
  });

  test("property: finder, timing, dark module and both format copies hold for any text and mask", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 120 }), fc.integer({ min: 0, max: 7 }), (text, mask) => {
        const qr = encodeQr(text, { mask });
        const s = qr.size;
        const m = qr.modules;
        const finder = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"];
        for (const [ox, oy] of [[0, 0], [s - 7, 0], [0, s - 7]] as const) {
          for (let y = 0; y < 7; y++) expect(m[oy + y]!.slice(ox, ox + 7).map((v) => (v ? "1" : "0")).join("")).toBe(finder[y]);
        }
        for (let i = 8; i < s - 8; i++) {
          expect(m[6]![i]).toBe(i % 2 === 0);
          expect(m[i]![6]).toBe(i % 2 === 0);
        }
        expect(m[s - 8]![8]).toBe(true);
        const bits = formatBits(mask);
        const bit = (i: number) => ((bits >>> i) & 1) === 1;
        // copy 1 around the top-left finder, copy 2 split between the other two
        const copy1 = [0, 1, 2, 3, 4, 5, 7, 8].map((y) => m[y]![8]).concat([7, 5, 4, 3, 2, 1, 0].map((x) => m[8]![x]));
        const copy2 = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => m[8]![s - 1 - i]).concat([8, 9, 10, 11, 12, 13, 14].map((i) => m[s - 15 + i]![8]));
        expect(copy1).toEqual([...Array(15).keys()].map(bit));
        expect(copy2).toEqual([...Array(15).keys()].map(bit));
      }),
      { numRuns: 100 },
    );
  });
});

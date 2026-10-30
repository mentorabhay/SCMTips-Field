/**
 * Console property tests for Phase 4 (T4.070 / T4.057).
 *
 * These exercise the console's own code: lib/exploded.ts (used by components/ModelViewer) and the
 * generated design tokens in @scmtips-field/ui-tokens. (Previously this file re-computed formulas
 * locally and asserted them against themselves, and it was never run.)
 */
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import { tokens } from "@scmtips-field/ui-tokens";
import { explodedPosition, type Vec3 } from "../lib/exploded";
import { contrastRatio } from "../lib/contrast";

const coord = fc.double({ min: -100, max: 100, noNaN: true });
const vec = fc.tuple(coord, coord, coord) as fc.Arbitrary<Vec3>;
const unit = fc.double({ min: 0, max: 1, noNaN: true });

describe("PR4.09 exploded offsets (FR4.056)", () => {
  test("PR4.09: p(0) = p0, p(1) = p0 + v, p(t) linear in t, t clamped to [0, 1]", () => {
    fc.assert(
      fc.property(vec, vec, unit, unit, fc.double({ min: -5, max: 5, noNaN: true }), (p0, v, a, b, wild) => {
        const at0 = explodedPosition(p0, v, 0);
        for (let i = 0; i < 3; i++) expect(at0[i] === p0[i]).toBe(true); // numeric equality (-0 === 0)
        const at1 = explodedPosition(p0, v, 1);
        for (let i = 0; i < 3; i++) expect(at1[i] - p0[i]).toBeCloseTo(v[i], 9);
        // linearity: p(a) - p(b) = (a - b) * v
        const pa = explodedPosition(p0, v, a);
        const pb = explodedPosition(p0, v, b);
        for (let i = 0; i < 3; i++) expect(pa[i] - pb[i]).toBeCloseTo((a - b) * v[i], 9);
        // overshoot is clamped
        const pw = explodedPosition(p0, v, wild);
        const clamped = explodedPosition(p0, v, Math.min(1, Math.max(0, wild)));
        for (let i = 0; i < 3; i++) expect(pw[i] === clamped[i]).toBe(true);
      }),
      { numRuns: 1000 },
    );
  });
});

describe("TC4.164 token contrast (WCAG 2.1 AA, text >= 4.5:1)", () => {
  const themes = Object.keys(tokens.color) as (keyof typeof tokens.color)[];
  for (const theme of themes) {
    test(`TC4.164: ${theme} text, muted text and primary-button text meet 4.5:1`, () => {
      const c = tokens.color[theme] as Record<string, { value: string }>;
      const pairs: [string, string][] = [
        ["text", "bg"],
        ["text", "surface"],
        ["textMuted", "bg"],
      ];
      if (c.primaryText) pairs.push(["primaryText", "primary"]);
      for (const [fg, bg] of pairs) {
        if (!c[fg] || !c[bg]) continue;
        expect(contrastRatio(c[fg].value, c[bg].value), `${theme} ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
      }
    });
  }
});

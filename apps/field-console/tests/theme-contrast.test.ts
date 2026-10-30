/**
 * WCAG 2.1 AA for the M2 console palette (lib/theme.ts, mirrored in tailwind.config.js): every text /
 * background pair the views use is at least 4.5:1, and the Tailwind config carries the same values.
 */
import { createRequire } from "node:module";
import { describe, expect, test } from "vitest";
import { contrastRatio } from "../lib/contrast";
import { palette, TEXT_PAIRS } from "../lib/theme";

describe("console palette contrast", () => {
  test.each(TEXT_PAIRS.map(([fg, bg]) => [fg, bg, palette[fg], palette[bg]] as const))("%s on %s (%s on %s) >= 4.5:1", (_fg, _bg, a, b) => {
    expect(contrastRatio(a, b)).toBeGreaterThanOrEqual(4.5);
  });

  test("the design's primary, page, ink and muted are used unchanged", () => {
    expect(palette).toMatchObject({ primary: "#1567D3", page: "#F0F2F5", card: "#FFFFFF", ink: "#1C1E21", muted: "#65676B" });
  });

  test("tailwind.config.js uses the same colours as lib/theme.ts", () => {
    const require = createRequire(import.meta.url);
    const tw = require("../tailwind.config.js") as { theme: { extend: { colors: Record<string, unknown> } } };
    const flat: string[] = [];
    const walk = (v: unknown) => {
      if (typeof v === "string") flat.push(v.toUpperCase());
      else if (v && typeof v === "object") Object.values(v).forEach(walk);
    };
    walk(tw.theme.extend.colors);
    const used = new Set(flat);
    for (const [k, v] of Object.entries(palette)) {
      if (k === "white") continue;
      expect(used.has(v.toUpperCase()), `${k} ${v} missing from tailwind.config.js`).toBe(true);
    }
  });
});

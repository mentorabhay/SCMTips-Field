/**
 * Console palette (design: Console.dc.html, social-app style). Tailwind reads these through
 * tailwind.config.js; tests/theme-contrast.test.ts checks every text/background pair below meets
 * WCAG 2.1 AA (4.5:1 for normal text).
 */
export const palette = {
  primary: "#1567D3",
  primaryHover: "#0E4BA0",
  page: "#F0F2F5",
  card: "#FFFFFF",
  soft: "#F7F8FA",
  column: "#E4E6EB",
  ink: "#1C1E21",
  muted: "#65676B",
  line: "#DADDE1",
  lineSoft: "#E4E6EB",
  control: "#CED0D4",
  selected: "#E7F3FF",
  selectedSoft: "#EEF6FF",
  selectedLine: "#BBD7F7",
  warnBg: "#FFF7E6",
  warnLine: "#D97706",
  warnInk: "#8A3B04",
  warnPillBg: "#FDF0E1",
  warnPillInk: "#6B3304",
  warnNumber: "#9A4A05",
  okBg: "#E6F4EA",
  okInk: "#14532D",
  okDot: "#157A3C",
  alertBg: "#FDECEA",
  alertLine: "#B42318",
  alertInk: "#8E1B1B",
  danger: "#B42318",
  pillBg: "#E4E6EB",
  pillInk: "#4B4F56",
  unknownDot: "#8A939B",
  white: "#FFFFFF",
} as const;

export type PaletteKey = keyof typeof palette;

/** [text, background] pairs the console actually renders as text. */
export const TEXT_PAIRS: ReadonlyArray<readonly [PaletteKey, PaletteKey]> = [
  ["ink", "page"], ["ink", "card"], ["ink", "soft"], ["ink", "column"], ["ink", "warnBg"], ["ink", "selectedSoft"],
  ["muted", "page"], ["muted", "card"], ["muted", "soft"], ["muted", "column"], ["muted", "selectedSoft"],
  ["primary", "card"], ["primary", "page"], ["primary", "selected"], ["primary", "selectedSoft"],
  ["white", "primary"], ["white", "primaryHover"], ["white", "ink"], ["white", "danger"],
  ["warnInk", "warnBg"], ["warnInk", "card"], ["warnPillInk", "warnPillBg"], ["warnNumber", "card"],
  ["okInk", "okBg"], ["okInk", "card"], ["okDot", "card"],
  ["alertInk", "alertBg"], ["alertInk", "card"], ["danger", "card"],
  ["pillInk", "pillBg"],
];

/** @type {import('tailwindcss').Config} */
// Colours mirror lib/theme.ts (checked for WCAG AA contrast by tests/theme-contrast.test.ts).
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#1567D3", hover: "#0E4BA0" },
        page: "#F0F2F5",
        card: "#FFFFFF",
        soft: "#F7F8FA",
        column: "#E4E6EB",
        ink: "#1C1E21",
        muted: "#65676B",
        line: { DEFAULT: "#DADDE1", soft: "#E4E6EB" },
        control: "#CED0D4",
        selected: { DEFAULT: "#E7F3FF", soft: "#EEF6FF", line: "#BBD7F7" },
        warn: { bg: "#FFF7E6", line: "#D97706", ink: "#8A3B04", pill: "#FDF0E1", pillink: "#6B3304", number: "#9A4A05" },
        ok: { bg: "#E6F4EA", ink: "#14532D", dot: "#157A3C" },
        alert: { bg: "#FDECEA", line: "#B42318", ink: "#8E1B1B" },
        danger: "#B42318",
        pill: { bg: "#E4E6EB", ink: "#4B4F56" },
        unknown: "#8A939B",
      },
      fontFamily: {
        sans: ['"Segoe UI"', "Roboto", "Helvetica", "Arial", "system-ui", "sans-serif"],
        mono: ['ui-monospace', '"Cascadia Mono"', "Consolas", "monospace"],
      },
      borderRadius: { card: "8px" },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./core/templates/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        paper: "#FAFAF8",
        surface: "#FFFFFF",
        ink: "#1F2937",
        "ink-soft": "#6B7280",
        line: "#E5E7EB",
        water: "#0F766E",
        "water-soft": "#CCFBF1",
        amber: { DEFAULT: "#B45309", bg: "#FEF3C7" },
        red: { DEFAULT: "#B91C1C", bg: "#FEE2E2" },
        violet: { DEFAULT: "#6D28D9", bg: "#EDE9FE" },
        star: "#CA8A04",
      },
      fontFamily: {
        display: ["Bricolage Grotesque", "sans-serif"],
        body: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        md: "6px",
      },
      maxWidth: {
        xl: "36rem",
      },
    },
  },
  // Status/badge class maps must return full literal strings from a template
  // tag (see docs/design.md §8.1) — anything dynamic-ish gets added here.
  safelist: [],
  plugins: [],
};

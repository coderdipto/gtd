/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./core/templates/**/*.html",
    "./core/templatetags/**/*.py",
  ],
  theme: {
    extend: {
      colors: {
        // Warm/editorial palette recolored 2026-07-14, taking cues from
        // cocoindex.io (parchment bg, deep maroon ink, terracotta accent).
        // Token names kept stable so every bg-water/text-ink/etc. usage
        // across templates cascades without per-template edits.
        paper: "#FAF3E5",
        surface: "#FFFCF6",
        ink: "#2A121B",
        "ink-soft": "#7C6259",
        line: "#E8DDD0",
        water: "#BE5133",
        "water-soft": "#F8E3D6",
        amber: { DEFAULT: "#B45309", bg: "#FEF3C7" },
        red: { DEFAULT: "#B91C1C", bg: "#FEE2E2" },
        violet: { DEFAULT: "#6D28D9", bg: "#EDE9FE" },
        star: "#CA8A04",
      },
      fontFamily: {
        display: ["Plus Jakarta Sans", "sans-serif"],
        body: ["Plus Jakarta Sans", "sans-serif"],
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

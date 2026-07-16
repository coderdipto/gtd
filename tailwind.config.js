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
        //
        // 2026-07-15: values now indirect through CSS custom properties
        // (defined in input.css as "R G B" triples) instead of literal hex,
        // so the same token/utility-class names serve both the light
        // (:root) and dark (:root[data-theme="dark"]) palettes - no
        // template ever needs a dark: variant, per docs/design.md's
        // no-dynamic-class-name rule. rgb(var(--x) / <alpha-value>) is the
        // Tailwind-documented form that keeps opacity modifiers (bg-water/50)
        // working.
        paper: "rgb(var(--color-paper) / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        ink: "rgb(var(--color-ink) / <alpha-value>)",
        "ink-soft": "rgb(var(--color-ink-soft) / <alpha-value>)",
        line: "rgb(var(--color-line) / <alpha-value>)",
        water: "rgb(var(--color-water) / <alpha-value>)",
        "water-soft": "rgb(var(--color-water-soft) / <alpha-value>)",
        amber: {
          DEFAULT: "rgb(var(--color-amber) / <alpha-value>)",
          bg: "rgb(var(--color-amber-bg) / <alpha-value>)",
        },
        red: {
          DEFAULT: "rgb(var(--color-red) / <alpha-value>)",
          bg: "rgb(var(--color-red-bg) / <alpha-value>)",
        },
        violet: {
          DEFAULT: "rgb(var(--color-violet) / <alpha-value>)",
          bg: "rgb(var(--color-violet-bg) / <alpha-value>)",
        },
        star: "rgb(var(--color-star) / <alpha-value>)",
      },
      fontFamily: {
        // title: brand "GTD" wordmark only (base.html) - a warm editorial
        // serif, deliberately distinct from font-display so the two never
        // read as the same typeface at a glance.
        title: ["Fraunces", "serif"],
        // display: in-page h1s/headers - geometric sans, confident/modern.
        display: ["Space Grotesk", "sans-serif"],
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

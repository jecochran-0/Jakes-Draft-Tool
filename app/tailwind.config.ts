import type { Config } from "tailwindcss";

/**
 * Mossy-stone dark-green design system.
 * Deep moss-charcoal surfaces, a bright chartreuse-lime accent, position hues for scanning.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0E1311",        // app background — deep moss black
        surface: "#161D19",     // card
        "surface-2": "#1E2722", // nested / elevated
        "surface-3": "#27332C", // hover / chips
        line: "rgba(255,255,255,0.07)",
        lime: {
          DEFAULT: "#C5F23D",   // primary accent
          dim: "#A9D62F",
          soft: "rgba(197,242,61,0.14)",
        },
        ink: {
          DEFAULT: "#F2F5F0",   // primary text
          muted: "#929C93",     // secondary
          faint: "#646E66",     // tertiary / disabled
        },
        steal: "#8FE06A",       // value vs ADP positive
        reach: "#FF7E6B",       // value vs ADP negative
        // Position hues
        pos: {
          QB: "#F5A623",
          RB: "#8FE06A",
          WR: "#4FA8FF",
          TE: "#C77DFF",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
        glow: "0 0 0 1px rgba(197,242,61,0.4), 0 8px 30px -8px rgba(197,242,61,0.25)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.25s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;

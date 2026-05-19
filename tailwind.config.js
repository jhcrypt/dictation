/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        jarvis: {
          bg:           "#141414",   // Python BG
          sidebar:      "#1a1a1a",   // Python SIDEBAR
          card:         "#222222",   // Python CARD
          surface:      "#2a2a2a",   // Python CARD_HI (hover / elevated)
          border:       "#2e2e2e",   // Python SEP
          accent:       "#0a84ff",   // Python ACC
          "accent-dim": "#1a3a5c",   // Python ACC_DIM
          "accent-hover": "#0070d4", // darker press state
          text:         "#f0f0f0",   // Python FG
          muted:        "#6a6a6a",   // Python DIM
          hint:         "#8ab4f8",   // Python HINT
          recording:    "#ff453a",   // Python danger
          transcribing: "#ff9f0a",   // Python warning
          success:      "#30d158",   // Python success
          danger:       "#ff453a",   // alias
        },
      },
      fontFamily: {
        sans: ["Helvetica Neue", "-apple-system", "BlinkMacSystemFont", "SF Pro Text", "Segoe UI", "sans-serif"],
      },
      borderRadius: {
        card: "8px",
      },
    },
  },
  plugins: [],
};

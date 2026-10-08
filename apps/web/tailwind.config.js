/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0f1420",
          soft: "#161d2c",
          line: "#243044",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

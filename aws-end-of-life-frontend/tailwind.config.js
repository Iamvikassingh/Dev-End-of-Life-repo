/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      colors: {
        nav:    "#0F1E35",
        accent: "#2A85D8",
        bg:     "#F0F4F8",
        eol:    { DEFAULT: "#922B21", light: "#FDEDEC" },
        warn:   { DEFAULT: "#B7770D", light: "#FEF9E7" },
        ext:    { DEFAULT: "#1A6EBD", light: "#D6EAF8" },
        ok:     { DEFAULT: "#0D6E56", light: "#D5F5E3" },
      },
    },
  },
  plugins: [],
};

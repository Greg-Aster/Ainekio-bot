/** @type {import('tailwindcss').Config} */
const defaultTheme = require("tailwindcss/defaultTheme")
module.exports = {
  content: [
    "./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue,mjs}",
    // Explicitly include admin components
    "./src/components/svelte/admin/**/*.svelte",
    // Shared blog-core components
    "../../packages/blog-core/src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue,mjs}",
  ],
  darkMode: "class", // allows toggling dark mode manually
  theme: {
    extend: {
      fontFamily: {
        sans: ["Roboto", "sans-serif", ...defaultTheme.fontFamily.sans],
        sriracha: ["Sriracha", "cursive"],
        "jetbrains-mono": ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
}

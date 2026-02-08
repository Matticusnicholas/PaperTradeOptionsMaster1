import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bullish: "#22c55e",
        bearish: "#ef4444",
        neutral: "#6b7280",
      },
    },
  },
  plugins: [],
};
export default config;

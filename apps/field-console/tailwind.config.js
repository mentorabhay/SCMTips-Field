/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        lens: {
          bg: "#000000",
          text: "#00FF66",
          dim: "#009933",
          accent: "#00FFCC",
          alert: "#FF3333",
        },
      },
    },
  },
  plugins: [],
};

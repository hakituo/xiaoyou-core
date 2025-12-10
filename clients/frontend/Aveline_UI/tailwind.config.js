/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'bg-900': '#05060a'
      },
      borderRadius: {
        'xl-2': '18px'
      },
    },
  },
  plugins: [],
}
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0a0a0a',
        panel: '#141414',
        panel2: '#1b1b1b',
        line: '#262626',
        ink: '#e6edf3',
        muted: '#8b949e',
        accent: '#58a6ff',
        good: '#3fb950',
        bad: '#f85149',
        purple: '#a371f7',
        amber: '#d29922',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}

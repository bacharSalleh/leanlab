import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built assets land inside the Python package so the wheel ships them.
// `base: './'` keeps asset URLs relative, so the board works mounted at '/'.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../leanlab/core/coding/board_dist',
    emptyOutDir: true,
  },
  // For local dev: `leanlab board --no-open` (serves the API on 8766) + `npm run dev`.
  server: { proxy: { '/api': 'http://localhost:8766' } },
})

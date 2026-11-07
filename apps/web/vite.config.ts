import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // FastAPI (make dev-api) runs on :8000
    proxy: { '/api': 'http://localhost:8000' },
  },
})

import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // FastAPI (make dev-api) runs on :8000; override with API_PORT=8017 npm run dev
  const apiPort = loadEnv(mode, '.', '').API_PORT || '8000'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: { '/api': `http://localhost:${apiPort}` },
      // The mock API seeds itself from WS4's fixtures in packages/scenarios/fixtures/.
      fs: { allow: ['.', '../../packages/scenarios/fixtures'] },
    },
  }
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the React app runs on :5173 and the FastAPI backend on :8000.
// Proxying /api means the frontend code can always call relative URLs like
// "/api/ask" - the same URLs work in production, where FastAPI serves the build.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})

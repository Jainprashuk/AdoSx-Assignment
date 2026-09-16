import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies /api to Django. Two servers, one origin as far as the
// browser is concerned, so there is no CORS setup and no base URL to configure
// per environment -- the app always fetches a relative path.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})

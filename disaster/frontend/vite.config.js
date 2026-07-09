import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/predict': 'http://localhost:8000',
      '/download': 'http://localhost:8000',
      '/files': 'http://localhost:8000',
      '/original': 'http://localhost:8000',
      '/history': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/ai': 'http://localhost:8000',
    },
  },
})

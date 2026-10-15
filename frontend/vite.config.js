import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const target = process.env.LORE_API || 'http://127.0.0.1:8000'
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': target, '/health': target, '/mcp': target } },
})

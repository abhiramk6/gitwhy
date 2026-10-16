import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The product name is defined once, in product.json at the repository root (/product.json inside the Docker build).
const productPath = ['../product.json', '/product.json'].find((p) => { try { readFileSync(new URL(p, import.meta.url)); return true } catch { try { readFileSync(p); return true } catch { return false } } })
const product = JSON.parse(readFileSync(productPath.startsWith('/') ? productPath : new URL(productPath, import.meta.url), 'utf8'))
const titlePlugin = { name: 'product-title', transformIndexHtml: (html) => html.replace(/%PRODUCT_TITLE%/g, `${product.name}: ${product.tagline}`) }

const target = process.env.GITWHY_API || 'http://127.0.0.1:8000'
export default defineConfig({
  plugins: [react(), titlePlugin],
  resolve: { alias: { '@product': new URL(productPath.startsWith('/') ? 'file://' + productPath : productPath, import.meta.url).pathname } },
  server: { proxy: { '/api': target, '/health': target, '/mcp': target }, fs: { allow: ['..'] } },
})

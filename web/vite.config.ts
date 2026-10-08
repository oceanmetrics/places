/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'

// the sibling client package is used from its TypeScript source, so `web/` builds without building `client/` first
const CLIENT_SRC = fileURLToPath(new URL('../client/src/index.ts', import.meta.url))

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    alias     : { '@oceanmetrics/places': CLIENT_SRC },
    conditions: ['browser'],
  },
  build : { target: 'es2022', chunkSizeWarningLimit: 1200 },
  server: { port: 5180, strictPort: true, fs: { allow: ['..'] } },
  test  : { environment: 'node', include: ['src/**/*.test.ts'] },
})

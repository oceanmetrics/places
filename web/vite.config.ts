/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'

// the client lives in oceanmetrics/platform `packages/places` since 2026-10-22; until Day 5 (2026-10-26, npm publish) it is a
// sibling checkout used from its TypeScript source, so `web/` builds without building the client first
const CLIENT_SRC = fileURLToPath(new URL('../../platform/packages/places/src/index.ts', import.meta.url))

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    alias     : { '@oceanmetrics/places': CLIENT_SRC },
    conditions: ['browser'],
  },
  build : { target: 'es2022', chunkSizeWarningLimit: 1200 },
  server: { port: 5180, strictPort: true, fs: { allow: ['..', '../../platform'] } },
  test  : { environment: 'node', include: ['src/**/*.test.ts'] },
})

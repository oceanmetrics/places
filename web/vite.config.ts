/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    conditions: ['browser'],
    // the client and the indicators slot both read parquet: one copy of hyparquet, from web/node_modules
    dedupe    : ['hyparquet'],
  },
  build : { target: 'es2022', chunkSizeWarningLimit: 1200 },
  server: { port: 5180, strictPort: true, fs: { allow: ['..'] } },
  // @oceanmetrics/places 0.5.1 ships dist/ with extensionless relative imports (`./client`), which Node's ESM loader rejects; inline it so
  // vitest resolves it through vite like the bundler does (drop this once the client emits `.js` specifiers)
  test  : { environment: 'node', include: ['src/**/*.test.ts'], server: { deps: { inline: ['@oceanmetrics/places'] } } },
})

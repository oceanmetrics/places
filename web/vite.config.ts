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
  // the platform checkout: @oceanmetrics/catalog is a file: link until 0.3.0 is on npm (then drop both entries); its own
  // import of @oceanmetrics/status (0.1.1, the status words) resolves from that checkout's node_modules
  server: { port: 5180, strictPort: true, fs: { allow: ['..', '../../platform/packages', '../../platform/node_modules'] } },
  test  : { environment: 'node', include: ['src/**/*.test.ts'] },
})

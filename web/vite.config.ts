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
  // MapLibre 6 import()s a worker module only when its url ends in .mjs (`importScriptInWorkers`), so worker chunks are .mjs
  worker: { format: 'es', rollupOptions: { output: { entryFileNames: 'assets/[name]-[hash].mjs', chunkFileNames: 'assets/[name]-[hash].mjs' } } },
  // DuckDB-WASM ships its own worker and wasm, which the dep optimizer breaks (as in indicators, atlas, obis-hex)
  optimizeDeps: { exclude: ['@duckdb/duckdb-wasm'] },
  // the manifest tells the size budget (scripts/size-budget.mjs) which chunk is the map's and which the engine's
  build : { target: 'es2022', chunkSizeWarningLimit: 1200, manifest: true },
  server: { port: 5180, strictPort: true, fs: { allow: ['..'] } },
  test  : { environment: 'node', include: ['src/**/*.test.ts'] },
})

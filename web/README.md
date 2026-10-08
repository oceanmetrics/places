# web/

The website at places.oceanmetrics.io: search by name, type, authority, bbox and licence; a browse map with layer
toggles (`layers=slug[:colour][:opacity][:width],...`, `place=<place_id>`); place pages `/p/<place_id>`, layer pages
`/l/<slug>`, `/credits`, `/docs`. Planned stack: Svelte 5 + Vite + MapLibre + PMTiles + hyparquet/DuckDB-WASM, hosted
on Cloudflare Workers static assets. Not started.

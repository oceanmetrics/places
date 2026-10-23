<script lang="ts">
  // "Values of this place": every values file its indicators list, read whole in the browser, the place's rows kept and
  // written as one CSV or Parquet file (downloads.ts, a lazy chunk; tested on fixtures). this only wires the buttons.
  import { INDICATORS_BASE, readCatalog } from './indicators'
  import { valuesFiles, type ValuesFile } from './reports'

  let { placeId }: { placeId: string } = $props()

  let files = $state<ValuesFile[] | null>(null)
  let busy = $state(false)
  let note = $state('')
  $effect(() => {
    const id = placeId
    readCatalog().then(([m, rows]) => { files = valuesFiles(rows, m, id, INDICATORS_BASE) }).catch(() => { files = [] })
  })

  const base = $derived(placeId.replace(/[^\w.-]+/g, '_'))
  function save(blob: Blob, name: string) {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = name
    document.body.append(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(a.href), 10_000)
  }
  async function get(kind: 'csv' | 'parquet') {
    if (!files?.length || busy) return
    busy = true
    note = `Reading ${files.length} values files…`
    try {
      const d = await import('./downloads')
      const got = await d.downloadValues(placeId, files)
      if (kind === 'csv') save(new Blob([d.valuesCsv(got.rows)], { type: 'text/csv' }), `values_${base}.csv`)
      else save(new Blob([d.valuesParquet(got.rows)], { type: 'application/vnd.apache.parquet' }), `values_${base}.parquet`)
      note = `${got.rows.length.toLocaleString('en-US')} values from ${files.length - got.failed.length} files` +
        (got.failed.length ? `; not read: ${got.failed.map((x) => x.url.split('/indicator=')[1]?.split('/')[0] ?? x.url).join(', ')}` : '') + '.'
    } catch (e) {
      note = `The values could not be read: ${(e as Error)?.message ?? e}`
    } finally {
      busy = false
    }
  }
</script>

{#if files?.length}
  <h3>Values of this place's indicators</h3>
  <div class="row">
    <button class="btn secondary" type="button" disabled={busy} onclick={() => get('csv')}>Values (CSV)</button>
    <button class="btn secondary" type="button" disabled={busy} onclick={() => get('parquet')}>Values (Parquet)</button>
  </div>
  <p class="muted small">Every value of the place from the {files.length} values files its indicator cards list (each read whole from the indicators catalog, then filtered to <code>{placeId}</code>), one row per value with the file it came from; each card's Reproduce gives the same file and a DuckDB query.{#if note}{' '}<span aria-live="polite">{note}</span>{/if}</p>
{/if}

<style>
  .small { font-size: 13px; }
  h3 { margin: 12px 0 4px; font-size: 1rem; }
</style>

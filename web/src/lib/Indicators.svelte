
<script lang="ts">
  // the indicators slot of the place page: the cards of the place from the indicators catalog, or which absence applies.
  // the rules are @oceanmetrics/catalog's cards (wired in indicators.ts, tested); this only draws them.
  import { coverageFor, footerLine, readCatalog, slotFor, type Slot } from './indicators'
  import { placeRollup, summaryLine } from './reports'
  import { GLYPH_PATHS } from './glyphs'
  import CopyButton from './CopyButton.svelte'

  let { placeId, layer }: { placeId: string; layer?: { title?: string; collection?: string } | null } = $props()

  let phase = $state<'loading' | 'ok' | 'error'>('loading')
  let message = $state('')
  let slot = $state<Slot | null>(null)
  let summary = $state<string | null>(null)
  let expanded = $state(false)

  $effect(() => {
    const id = placeId, l = layer
    phase = 'loading'; expanded = false
    readCatalog()
      .then(([m, rows]) => {
        if (id !== placeId) return
        const mine = coverageFor(rows, id)
        slot = slotFor(mine, m, id, l)
        summary = summaryLine(placeRollup(mine, id))
        phase = 'ok'
      })
      .catch((e: unknown) => { phase = 'error'; message = String((e as Error)?.message ?? e) })
  })

  const shown = $derived(slot ? (expanded ? slot.cards : slot.cards.slice(0, slot.first)) : [])
</script>

<section class="indicators" aria-labelledby="indicators-h">
  <h2 id="indicators-h">Indicators</h2>
  {#if phase === 'loading'}
    <p class="notice" aria-live="polite">Loading the indicators of this place…</p>
  {:else if phase === 'error'}
    <p class="notice">The indicators catalog could not be read: {message}</p>
  {:else if slot}
    {#if summary}<p class="summary">{summary}</p>{/if}
    {#if slot.absence}
      <p class="notice">{slot.absence.text}{#if slot.absence.href}{' '}<a href={slot.absence.href} target="_blank" rel="noopener noreferrer">{slot.absence.linkText} ↗</a>{#each slot.absence.more ?? [] as l}{' · '}<a href={l.href} target="_blank" rel="noopener noreferrer">{l.linkText} ↗</a>{/each}{/if}</p>
    {/if}
    {#if shown.length}
      <div class="row cards">
        {#each shown as c (c.id)}
          <article class="card ind">
            <h3>{c.title}</h3>
            <p class="val"><strong>{c.value}</strong>{#if c.unit}{' '}<span>{c.unit}</span>{/if} <span class="muted">· {c.period}</span></p>
            <p class="st">
              <svg class="glyph" viewBox="0 0 24 24" aria-hidden="true"><path d={GLYPH_PATHS[c.glyph]} /></svg>
              {#if c.trendGlyph}<svg class="glyph" viewBox="0 0 24 24" aria-hidden="true"><path d={GLYPH_PATHS[c.trendGlyph]} /></svg>{/if}
              <span>{c.caption}</span>
            </p>
            <details>
              <summary>Sentence, method and citation</summary>
              {#if c.sentence}<p>{c.sentence}</p>{/if}
              <p><span class="muted">Method:</span> {c.methodLabel}. {c.methodNote}</p>
              <p><span class="muted">Citation:</span> {c.citation}</p>
              <p><CopyButton text={c.citation} label="Copy citation" /></p>
            </details>
            <details class="repro">
              <summary>Reproduce</summary>
              {#if c.reproduce.valuesUrl}
                <p><span class="muted">Values:</span> <a href={c.reproduce.valuesUrl}>{c.reproduce.valuesUrl}</a></p>
                <pre><code>{c.reproduce.snippet}</code></pre>
                <p><CopyButton text={c.reproduce.snippet ?? ''} label="Copy DuckDB SQL" /></p>
              {:else}
                <p class="muted">The indicators manifest lists no values file for this place's collection.</p>
              {/if}
              <p><span class="muted">Config hash:</span> <code>{c.reproduce.hash}</code></p>
              <pre><code>{c.reproduce.config.join('\n')}</code></pre>
            </details>
            <a class="btn secondary small" href={c.href} target="_blank" rel="noopener noreferrer">Open in Indicators ↗</a>
          </article>
        {/each}
      </div>
      {#if slot.cards.length > slot.first}
        <button class="btn secondary small" type="button" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
          {expanded ? `Show the ${slot.first} lead indicators` : `Show all ${slot.cards.length} indicators`}
        </button>
      {/if}
    {/if}
    {#if slot.noStatus}
      <p class="muted nostatus">
        <svg class="glyph" viewBox="0 0 24 24" aria-hidden="true"><path d={GLYPH_PATHS['st-none']} /></svg>
        <span>{slot.noStatus.text} <a href={slot.noStatus.href} target="_blank" rel="noopener noreferrer">{slot.noStatus.linkText} ↗</a></span>
      </p>
    {/if}
    {#if slot.total}<p class="muted foot">{footerLine(slot.total)}</p>{/if}
  {/if}
</section>

<style>
  /* a grid, not the flex .row: a last card alone keeps its column's width */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(15rem, 100%), 1fr)); align-items: stretch; margin: 8px 0; }
  .ind { min-width: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
  .ind h3 { margin: 0; font-size: .95rem; line-height: 1.3; overflow-wrap: anywhere; }
  .ind p { margin: 0; }
  .val { font-size: 14px; color: var(--text-body); }
  .val strong { font-family: var(--mono); font-size: 1.15rem; color: var(--text); }
  .st, .nostatus { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-body); }
  .nostatus { align-items: flex-start; color: var(--text-muted); }
  .glyph { width: 18px; height: 18px; flex: none; fill: currentColor; color: var(--brand-text); }
  details { font-size: 12.5px; color: var(--text-body); }
  details summary { cursor: pointer; color: var(--link); }
  details p { margin: 4px 0 0; overflow-wrap: anywhere; }
  .repro pre { margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
  .ind .btn { align-self: flex-start; margin-top: auto; }
  .foot { font-size: 12.5px; margin: 8px 0 0; }
  .summary { margin: 0 0 4px; color: var(--text-body); }
</style>

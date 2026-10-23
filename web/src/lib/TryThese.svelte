<script lang="ts">
  // "Try these" (tryThese.ts): on the home page under the search, and on the Data page. A Place page is an in-app link (under
  // APP_BASE, keeping a `base=` override like the page's other links); a way out to another app is an absolute link
  import { BASE } from './data.svelte'
  import { withBase } from './helpers'
  import { TRY_THESE } from './tryThese'

  let { heading = 'h2' }: { heading?: 'h2' | 'h3' } = $props()
</script>

<section class="try" aria-labelledby="try-these-h" data-testid="try-these">
  <svelte:element this={heading} id="try-these-h">Try these</svelte:element>
  <ul>
    {#each TRY_THESE as t (t.id)}
      <li>
        {#if t.kind === 'place'}
          <a href={withBase(t.to, BASE)} data-testid="try-{t.id}">{t.label}</a>
        {:else}
          <a href={t.to} target="_blank" rel="noopener" data-testid="try-{t.id}">{t.label} <span aria-hidden="true">↗</span></a>
        {/if}
        <span class="muted note">{t.note}</span>
      </li>
    {/each}
  </ul>
</section>

<style>
  .try { margin: .6rem 0 .4rem; }
  .try :global(h2), .try :global(h3) { margin: 1rem 0 .3rem; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { padding: 5px 0; border-bottom: 1px solid var(--border); }
  li:last-child { border-bottom: 0; }
  a { font-weight: 600; }
  .note { display: block; font-size: 12px; }
</style>

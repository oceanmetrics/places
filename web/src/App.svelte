<script lang="ts">
  import { onMount } from 'svelte'
  import { BASE, loadManifest } from './lib/data.svelte'
  import { withBase } from './lib/helpers'
  import { loc, route, startRouter } from './lib/router.svelte'
  import { theme, toggleTheme } from './lib/theme.svelte'
  import OmMark from './lib/OmMark.svelte'
  import Home from './pages/Home.svelte'
  import Place from './pages/Place.svelte'
  import LayerPage from './pages/LayerPage.svelte'
  import Credits from './pages/Credits.svelte'
  import Docs from './pages/Docs.svelte'

  onMount(() => { startRouter(); loadManifest() })

  const r = $derived((loc.path, route()))
  const nav = [
    { href: '/', label: 'Map', name: 'home' },
    { href: '/credits', label: 'Credits', name: 'credits' },
    { href: '/docs', label: 'Docs', name: 'docs' },
  ]
  const here = $derived(r.name === 'place' || r.name === 'layer' ? 'home' : r.name)

  $effect(() => {
    const t = { home: 'Places', place: 'Place', layer: 'Layer', credits: 'Credits', docs: 'Docs', notfound: 'Not found' }[r.name]
    document.title = `${t} · Ocean Metrics marine gazetteer`
  })
</script>

<header class="site-header">
  <a class="brand" href={withBase('/', BASE)} aria-label="Places — the Ocean Metrics marine gazetteer">
    <OmMark />
    <span class="om-ocean">Ocean</span><span class="om-metrics">Metrics</span>
    <span class="brand-product">Places</span>
  </a>
  <nav aria-label="Main">
    {#each nav as n}
      <a href={withBase(n.href, BASE)} aria-current={here === n.name ? 'page' : undefined}>{n.label}</a>
    {/each}
    <button class="theme-toggle" type="button" onclick={toggleTheme}
      aria-label={theme.dark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={theme.dark ? 'Switch to light theme' : 'Switch to dark theme'}>
      {#if theme.dark}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2" /><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5 5l1.7 1.7M17.3 17.3L19 19M19 5l-1.7 1.7M6.7 17.3L5 19" /></svg>
      {:else}
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.3 14.6A8.4 8.4 0 0 1 9.4 3.7a.6.6 0 0 0-.8-.74 9.6 9.6 0 1 0 12.44 12.44.6.6 0 0 0-.74-.8z" /></svg>
      {/if}
    </button>
  </nav>
</header>

{#if r.name === 'home'}
  <Home />
{:else if r.name === 'place'}
  {#key r.id}<Place id={r.id} />{/key}
{:else if r.name === 'layer'}
  {#key r.slug}<LayerPage slug={r.slug} />{/key}
{:else if r.name === 'credits'}
  <Credits />
{:else if r.name === 'docs'}
  <Docs />
{:else}
  <main class="page">
    <h1>Page not found</h1>
    <p><a href={withBase('/', BASE)}>Back to the map</a></p>
  </main>
{/if}

{#if r.name !== 'home'}
  <footer class="site-footer">Data: <a href={BASE}>{BASE}</a> · Every feature carries its licence and attribution · <a href={withBase('/credits', BASE)}>Credits</a></footer>
{/if}

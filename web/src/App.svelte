<script lang="ts">
  import { onMount } from 'svelte'
  import { BASE, loadManifest } from './lib/data.svelte'
  import { withBase } from './lib/helpers'
  import { loc, route, startRouter } from './lib/router.svelte'
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
  <a class="brand" href={withBase('/', BASE)}>
    <svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#0b4f6c" /><path d="M16 5a8 8 0 0 0-8 8c0 6 8 14 8 14s8-8 8-14a8 8 0 0 0-8-8zm0 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6z" fill="#f2b134" /></svg>
    Places <span class="muted long">· Ocean Metrics marine gazetteer</span>
  </a>
  <nav aria-label="Main">
    {#each nav as n}
      <a href={withBase(n.href, BASE)} aria-current={here === n.name ? 'page' : undefined}>{n.label}</a>
    {/each}
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

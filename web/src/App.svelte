<script lang="ts">
  import '@oceanmetrics/nav/define'
  import { onMount } from 'svelte'
  import { BASE, loadManifest } from './lib/data.svelte'
  import { navSearchTarget, withBase } from './lib/helpers'
  import { loc, navigate, route, startRouter } from './lib/router.svelte'
  import { theme, toggleTheme } from './lib/theme.svelte'
  import Home from './pages/Home.svelte'
  import Place from './pages/Place.svelte'
  import LayerPage from './pages/LayerPage.svelte'
  import Credits from './pages/Credits.svelte'
  import Docs from './pages/Docs.svelte'

  let bar: HTMLElement
  onMount(() => {
    startRouter(); loadManifest()
    // the bar's place search: Places is the target itself, so a url on this origin routes in-app; others fall through to the bar
    const onSearch = (e: Event) => {
      const to = navSearchTarget((e as CustomEvent<{ url: string }>).detail.url, location.origin)
      if (to) { e.preventDefault(); navigate(to) }
    }
    bar.addEventListener('om-nav-search', onSearch)
    return () => bar.removeEventListener('om-nav-search', onSearch)
  })

  const r = $derived((loc.path, route()))
  const nav = [
    { href: '/', label: 'Map', name: 'home' },
    { href: '/credits', label: 'Credits', name: 'credits' },
    { href: '/docs', label: 'Data', name: 'docs' },
  ]
  const here = $derived(r.name === 'place' || r.name === 'layer' ? 'home' : r.name)

  // the place and layer pages set their own title (the prerendered shell already carries it, scripts/shell-lib.mjs)
  $effect(() => {
    if (r.name === 'place' || r.name === 'layer') return
    const t = { home: 'Places', credits: 'Credits', docs: 'Docs', notfound: 'Not found' }[r.name]
    document.title = `${t} · Ocean Metrics marine gazetteer`
  })
</script>

<om-nav bind:this={bar} current="places" changes-href="https://oceanmetrics.io/docs/" search-href={new URL(withBase('/', BASE), location.origin).href}>
  <nav class="app-nav" aria-label="Places">
    {#each nav as n}
      <a href={withBase(n.href, BASE)} aria-current={here === n.name ? 'page' : undefined}>{n.label}</a>
    {/each}
  </nav>
  <button class="theme-toggle" type="button" onclick={toggleTheme}
    aria-label={theme.dark ? 'Switch to light theme' : 'Switch to dark theme'}
    title={theme.dark ? 'Switch to light theme' : 'Switch to dark theme'}>
    {#if theme.dark}
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2" /><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5 5l1.7 1.7M17.3 17.3L19 19M19 5l-1.7 1.7M6.7 17.3L5 19" /></svg>
    {:else}
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.3 14.6A8.4 8.4 0 0 1 9.4 3.7a.6.6 0 0 0-.8-.74 9.6 9.6 0 1 0 12.44 12.44.6.6 0 0 0-.74-.8z" /></svg>
    {/if}
  </button>
</om-nav>

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

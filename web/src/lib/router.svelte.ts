// a tiny history router: the URL is the single source of truth (path = page, query = map state)
import { matchRoute, type Route } from './helpers'

export const loc = $state({ path: location.pathname, search: location.search })

export const route = (): Route => matchRoute(loc.path)

const sync = () => { loc.path = location.pathname; loc.search = location.search }

/** go to an in-app url; `replace` rewrites the current history entry (used for map state, which should not flood history). */
export function navigate(url: string, opts: { replace?: boolean } = {}) {
  const u = new URL(url, location.href)
  history[opts.replace ? 'replaceState' : 'pushState'](null, '', u.pathname + u.search + u.hash)
  sync()
  if (!opts.replace) window.scrollTo(0, 0)
}

/** call once: back/forward and plain clicks on in-app links. */
export function startRouter() {
  addEventListener('popstate', sync)
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const a = (e.target as Element | null)?.closest?.('a')
    if (!a || a.target || a.hasAttribute('download') || a.origin !== location.origin) return
    e.preventDefault()
    navigate(a.pathname + a.search + a.hash)
  })
}

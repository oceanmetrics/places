// the app theme, per the Ocean Metrics brand (oceanmetrics.io/brand/v1): an explicit choice persists as
// localStorage 'om-theme' and is set on <html data-theme> before first paint by an inline script in
// index.html (no flash); without one the OS preference applies. CSS resolves through light-dark() keyed
// on color-scheme; only the MapLibre basemap and the toggle button need `theme.dark` from here.
import { effectiveDark } from './helpers'

const root = typeof document !== 'undefined' ? document.documentElement : null
const mq = typeof matchMedia !== 'undefined' ? matchMedia('(prefers-color-scheme: dark)') : null

export const theme = $state({ dark: effectiveDark(root?.dataset.theme, mq?.matches ?? false) })

// follow the OS while the user hasn't made an explicit choice
mq?.addEventListener('change', (e) => { if (!root?.dataset.theme) theme.dark = e.matches })

export function toggleTheme() {
  const next = theme.dark ? 'light' : 'dark'
  if (root) root.dataset.theme = next
  try { localStorage.setItem('om-theme', next) } catch { /* storage unavailable: the choice lasts the session */ }
  theme.dark = next === 'dark'
}

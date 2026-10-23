/// <reference types="svelte" />
/// <reference types="vite/client" />
interface ImportMetaEnv {
  /** the storage host (@oceanmetrics/catalog/storage): storage | s3 | preview | an https url; default the package's */
  readonly VITE_OM_STORAGE?: string
  /** gazetteer root, default https://storage.oceanmetrics.io/gazetteer/ */
  readonly VITE_PLACES_BASE?: string
  /** indicators catalog root, default https://storage.oceanmetrics.io/indicators/ */
  readonly VITE_INDICATORS_BASE?: string
}

// the shared bar (@oceanmetrics/nav), a custom element: its attributes as Svelte sees them
declare namespace svelteHTML {
  interface IntrinsicElements {
    'om-nav': import('svelte/elements').HTMLAttributes<HTMLElement> & {
      current?: string; theme?: 'light' | 'dark'; 'changes-href'?: string; 'search-href'?: string; 'collapse-at'?: string | number; items?: string
    }
  }
}

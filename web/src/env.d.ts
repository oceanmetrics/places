/// <reference types="svelte" />
/// <reference types="vite/client" />
interface ImportMetaEnv {
  /** gazetteer root, default https://storage.oceanmetrics.io/gazetteer/ */
  readonly VITE_PLACES_BASE?: string
}

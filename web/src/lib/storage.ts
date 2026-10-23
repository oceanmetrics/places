// the storage host this build reads, chosen once (@oceanmetrics/catalog/storage): `data-om-storage` on <html> >
// VITE_OM_STORAGE > the package default (path-style S3 until the DNS cutover flips it). every bucket url of the app is
// `store(key)`; no file keeps a host of its own.
import { resolveStorageHost, storageUrl } from '@oceanmetrics/catalog/storage'

export const STORAGE = resolveStorageHost(
  typeof document !== 'undefined' ? document.documentElement.dataset.omStorage : undefined,
  import.meta.env?.VITE_OM_STORAGE as string | undefined,
)
/** the url of a bucket key (or prefix) on this build's storage host */
export const store = (key: string): string => storageUrl(key, { host: STORAGE })

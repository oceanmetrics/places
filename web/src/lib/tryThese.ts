// "Try these": the examples of the home page (under the search) and of the Data page (/docs). Ben 2026-10-23: the features
// must be findable without asking. three Place pages and the two ways out to the other apps (the indicators viewer's Then
// vs Now at the Channel Islands, the atlas's OBIS species richness on the globe); the same affordance is the indicators
// viewer's Help -> Try these, the atlas's Help -> Try these and oceanmetrics.io /docs/ "Maps". a plain list: the components
// (TryThese.svelte) only draw it, and tryThese.test.ts asserts every link against the grammar that reads it.
import { buildSearch } from './grammar'
import { placePath } from './helpers'
import { ATLAS_APP } from './layers'
import { compareHref, DEFAULT_LAYER } from './thenNow'

export interface TryThis {
  id: string
  /** the row */
  label: string
  /** one line under it */
  note: string
  /** a Place page of this site (`in-app`: the link goes through the router, under APP_BASE) or another app (`out`: an absolute url) */
  kind: 'place' | 'out'
  /** place: the path with its query (`/p/NMS:CINMS?layer=…`); out: the full url */
  to: string
}

/** the atlas's OBIS species-richness view on the globe: the codec's own url (the globe is its default projection, `res=auto` its default resolution) */
export const ATLAS_OBIS_GLOBE = `${ATLAS_APP}?c=obis_h3&i=all&dim.indicator=sp&dim.period=all`

export const TRY_THESE: readonly TryThis[] = [
  {
    id: 'cinms-sst',
    label: 'Channel Islands, with sea surface temperature under the map',
    note: 'A sanctuary’s Place page: its indicators, species, layers and reports.',
    kind: 'place',
    to: placePath('NMS:CINMS') + buildSearch({ layer: DEFAULT_LAYER }, ''),
  },
  {
    id: 'fgbnms',
    label: 'Flower Garden Banks',
    note: 'A sanctuary in the Gulf with its own indicators and species.',
    kind: 'place',
    to: placePath('NMS:FGBNMS'),
  },
  {
    id: 'senegal-eez',
    label: 'The Senegalese EEZ',
    note: 'An exclusive economic zone from Marine Regions (MRGID:8371), not a sanctuary.',
    kind: 'place',
    to: placePath('MRGID:8371'),
  },
  {
    id: 'then-now',
    label: 'Then vs Now at the Channel Islands',
    note: 'In the indicators viewer: July 2016 against July 2024, side by side.',
    kind: 'out',
    to: compareHref({ place: 'NMS:CINMS', layer: DEFAULT_LAYER, t: '2024-07', coll: 'places' })!,
  },
  {
    id: 'obis-globe',
    label: 'OBIS species richness on the globe',
    note: 'In the atlas: every OBIS record as hexagons, by species count.',
    kind: 'out',
    to: ATLAS_OBIS_GLOBE,
  },
]

// the GA4 measurement id of this build: the repository variable VITE_GA_ID (pages.yml), never a literal. unset or
// malformed is '' and the bar gets no data-ga, so nothing loads (@oceanmetrics/nav README "Analytics").
export const GA_ID_RE = /^G-[A-Z0-9]{4,16}$/

export function gaId(raw: string | undefined = import.meta.env?.VITE_GA_ID): string {
  const v = (raw ?? '').trim()
  return GA_ID_RE.test(v) ? v : ''
}

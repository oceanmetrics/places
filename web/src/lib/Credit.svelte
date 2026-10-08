<script lang="ts">
  // one layer's licence + attribution + citation block (used by the place, layer and credits pages)
  import type { Layer } from '@oceanmetrics/places'
  import { sanitizeHtml } from './helpers'
  import CopyButton from './CopyButton.svelte'
  let { layer, heading = true }: { layer: Layer; heading?: boolean } = $props()
</script>

<table class="kv">
  <tbody>
    <tr>
      <th>Licence</th>
      <td>
        {#if layer.license_url}<a href={layer.license_url} target="_blank" rel="noopener noreferrer">{layer.license ?? layer.license_url}</a>
        {:else}{layer.license ?? 'not stated'}{/if}
      </td>
    </tr>
    <tr><th>Attribution</th><td>{@html sanitizeHtml(layer.attribution_html || layer.attribution) || '–'}</td></tr>
    <tr>
      <th>Citation</th>
      <td>
        {#if layer.citation}
          <blockquote>{layer.citation}</blockquote>
          <CopyButton text={layer.citation} label="Copy citation" />
        {:else}–{/if}
      </td>
    </tr>
  </tbody>
</table>

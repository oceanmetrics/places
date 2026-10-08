<script lang="ts">
  let { text, label = 'Copy' }: { text: string; label?: string } = $props()
  let done = $state(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      done = true
      setTimeout(() => (done = false), 1500)
    } catch { /* clipboard unavailable: the text stays selectable */ }
  }
</script>

<button type="button" class="btn secondary small" onclick={copy}>{done ? 'Copied' : label}</button>

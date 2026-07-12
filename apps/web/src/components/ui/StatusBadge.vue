<script setup lang="ts">
defineProps<{ status: string | null | undefined }>()

function tone(status: string | null | undefined) {
  if (status === 'ready' || status === 'healthy') return 'success'
  if (status === 'failed' || status === 'unhealthy' || status === 'unavailable') return 'danger'
  if (status === 'pending' || status === 'processing' || status === 'warming' || status === 'degraded') return 'warning'
  return 'neutral'
}
</script>

<template>
  <span class="status-badge" :data-tone="tone(status)">
    {{ status ?? 'unknown' }}
  </span>
</template>

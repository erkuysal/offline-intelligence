<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { RefreshCw } from '@lucide/vue'

import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useSystemStore, type HealthKey } from '@/stores/system'

const system = useSystemStore()
const labels: Record<HealthKey, string> = {
  api: 'API',
  database: 'PostgreSQL',
  redis: 'Redis',
  embedding: 'Embedding',
  worker: 'Ingestion worker',
  llm: 'LLM',
}

onMounted(() => system.startAutoRefresh())
onUnmounted(() => system.stopAutoRefresh())

function formatUpdated(value: string | null): string {
  if (!value) return 'Not checked'
  return new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' }).format(new Date(value))
}
</script>

<template>
  <section class="view-stack">
    <header class="view-header">
      <div><p class="eyebrow">System</p><h1>Health</h1></div>
      <button class="secondary-button" type="button" :disabled="system.loading" @click="system.refresh">
        <RefreshCw :class="{ spin: system.loading }" :size="18" /> Refresh
      </button>
    </header>
    <p class="health-summary" role="status" aria-live="polite" :aria-busy="system.loading">
      <span v-if="system.loading">Checking services</span>
      <span v-else-if="system.unavailableCount">{{ system.unavailableCount }} unavailable</span>
      <span v-else>Services checked</span>
      <span>Updated {{ formatUpdated(system.lastUpdated) }}</span>
    </p>
    <div class="health-grid">
      <article v-for="(value, key) in system.health" :key="key" class="health-item">
        <header>
          <h2>{{ labels[key] }}</h2>
          <StatusBadge :status="value?.status ?? 'unknown'" />
        </header>
        <p>{{ value?.detail ?? 'Waiting for health check' }}</p>
        <code v-if="value?.code">{{ value.code }}</code>
        <dl v-if="value && Object.keys(value.metadata).length" class="health-metadata">
          <template v-for="(metadataValue, metadataKey) in value.metadata" :key="metadataKey">
            <dt>{{ metadataKey }}</dt>
            <dd>{{ metadataValue ?? '-' }}</dd>
          </template>
        </dl>
      </article>
    </div>
  </section>
</template>

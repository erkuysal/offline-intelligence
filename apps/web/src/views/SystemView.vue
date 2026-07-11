<script setup lang="ts">
import { onMounted } from 'vue'

import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useSystemStore } from '@/stores/system'

const system = useSystemStore()
onMounted(() => system.refresh())
</script>

<template>
  <section class="view-stack">
    <header class="view-header">
      <div><p class="eyebrow">System</p><h1>Health</h1></div>
      <button class="secondary-button" type="button" @click="system.refresh">Refresh</button>
    </header>
    <div class="health-grid">
      <article v-for="(value, key) in system.health" :key="key" class="health-item">
        <span>{{ key }}</span>
        <StatusBadge :status="value?.status ?? 'unknown'" />
      </article>
    </div>
  </section>
</template>

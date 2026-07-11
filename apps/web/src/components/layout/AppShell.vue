<script setup lang="ts">
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { FileText, HeartPulse, LogOut, MessageSquare } from '@lucide/vue'

import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const router = useRouter()

function logout() {
  session.clear()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-frame">
    <aside class="sidebar" aria-label="Primary">
      <div class="brand">
        <span class="brand-mark">OI</span>
        <span>Offline Intelligence</span>
      </div>
      <nav class="nav-list">
        <RouterLink to="/documents"><FileText :size="18" /> Documents</RouterLink>
        <RouterLink to="/chat"><MessageSquare :size="18" /> Chat</RouterLink>
        <RouterLink to="/system"><HeartPulse :size="18" /> System</RouterLink>
      </nav>
      <button class="icon-text-button" type="button" @click="logout">
        <LogOut :size="18" /> Log out
      </button>
    </aside>
    <main class="main-panel">
      <RouterView />
    </main>
  </div>
</template>

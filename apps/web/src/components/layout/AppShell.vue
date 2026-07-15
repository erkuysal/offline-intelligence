<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import {
  ChevronDown,
  FileText,
  HeartPulse,
  LogOut,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  X,
} from '@lucide/vue'

import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()
const mobileNavOpen = ref(false)
const sidebarCollapsed = ref(localStorage.getItem('offlineHub.sidebarCollapsed') === 'true')
const accountMenuOpen = ref(false)
const accountMenu = ref<HTMLElement | null>(null)

const userInitial = computed(() => session.user?.email?.charAt(0).toUpperCase() ?? 'U')
const routeContext = computed(() => {
  const contexts: Record<string, { section: string; page: string; sectionTo?: string }> = {
    documents: { section: 'Workspace', page: 'Documents' },
    'document-detail': {
      section: 'Documents',
      page: `Document ${String(route.params.id)}`,
      sectionTo: '/documents',
    },
    chat: { section: 'Workspace', page: 'Chat' },
    system: { section: 'Operations', page: 'System' },
  }
  return contexts[String(route.name)] ?? { section: 'Workspace', page: 'Overview' }
})

watch(
  () => route.fullPath,
  () => {
    mobileNavOpen.value = false
    accountMenuOpen.value = false
  },
)

function logout() {
  mobileNavOpen.value = false
  accountMenuOpen.value = false
  session.clear()
  router.push({ name: 'login' })
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('offlineHub.sidebarCollapsed', String(sidebarCollapsed.value))
}

function closeAccountMenu(event: MouseEvent) {
  if (!accountMenu.value?.contains(event.target as Node)) accountMenuOpen.value = false
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') accountMenuOpen.value = false
}

onMounted(() => {
  document.addEventListener('click', closeAccountMenu)
  document.addEventListener('keydown', handleEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeAccountMenu)
  document.removeEventListener('keydown', handleEscape)
})
</script>

<template>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <div
    class="app-frame"
    :class="{ 'nav-open': mobileNavOpen, 'sidebar-collapsed': sidebarCollapsed }"
  >
    <header class="mobile-header">
      <div class="brand brand-compact" aria-label="Offline Intelligence Hub">
        <span class="brand-mark">OI</span>
        <span>Intelligence Hub</span>
      </div>
      <button
        class="shell-icon-button"
        type="button"
        :aria-expanded="mobileNavOpen"
        aria-controls="primary-navigation"
        aria-label="Open navigation"
        @click="mobileNavOpen = true"
      >
        <Menu :size="21" />
      </button>
    </header>

    <button
      v-if="mobileNavOpen"
      class="nav-scrim"
      type="button"
      aria-label="Close navigation"
      @click="mobileNavOpen = false"
    />

    <aside
      id="primary-navigation"
      class="sidebar"
      :class="{ open: mobileNavOpen, collapsed: sidebarCollapsed }"
      aria-label="Primary"
    >
      <div class="sidebar-header">
        <div class="brand">
          <span class="brand-mark">OI</span>
          <span class="brand-copy">
            <strong>Offline Intelligence</strong>
            <small>Private AI workspace</small>
          </span>
        </div>
        <button
          class="shell-icon-button sidebar-close"
          type="button"
          aria-label="Close navigation"
          @click="mobileNavOpen = false"
        >
          <X :size="20" />
        </button>
      </div>

      <div class="workspace-label">
        <span class="workspace-dot" aria-hidden="true" />
        <span><strong>Local workspace</strong><small>On-device services</small></span>
      </div>

      <nav class="nav-list">
        <p class="nav-section-label">Workspace</p>
        <RouterLink to="/documents" aria-label="Documents" title="Documents"><FileText :size="19" /> <span>Documents</span></RouterLink>
        <RouterLink to="/chat" aria-label="Chat" title="Chat"><MessageSquare :size="19" /> <span>Chat</span></RouterLink>
        <p class="nav-section-label nav-section-spaced">Operations</p>
        <RouterLink to="/system" aria-label="System" title="System"><HeartPulse :size="19" /> <span>System</span></RouterLink>
      </nav>

      <div class="sidebar-desktop-footer">
        <button
          class="sidebar-collapse-button"
          type="button"
          :aria-label="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          :title="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          :aria-expanded="!sidebarCollapsed"
          @click="toggleSidebar"
        >
          <PanelLeftOpen v-if="sidebarCollapsed" :size="19" />
          <PanelLeftClose v-else :size="19" />
          <span>{{ sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar' }}</span>
        </button>
      </div>

      <footer class="sidebar-footer">
        <div class="user-summary">
          <span class="user-avatar" aria-hidden="true">{{ userInitial }}</span>
          <span class="user-copy">
            <strong>{{ session.user?.email ?? 'Signed in' }}</strong>
            <small>Authenticated session</small>
          </span>
        </div>
        <button class="icon-text-button" type="button" title="Log out" @click="logout">
          <LogOut :size="18" /> <span>Log out</span>
        </button>
      </footer>
    </aside>

    <main id="main-content" class="main-panel" tabindex="-1">
      <header class="desktop-appbar">
        <div class="appbar-left">
          <nav class="appbar-breadcrumbs" aria-label="Breadcrumb">
            <RouterLink v-if="routeContext.sectionTo" :to="routeContext.sectionTo">
              {{ routeContext.section }}
            </RouterLink>
            <span v-else>{{ routeContext.section }}</span>
            <span aria-hidden="true">/</span>
            <strong>{{ routeContext.page }}</strong>
          </nav>
        </div>

        <div class="appbar-center" aria-label="Runtime context">
          <span><span class="workspace-dot" aria-hidden="true" /> Local runtime</span>
          <span><ShieldCheck :size="13" /> Private</span>
        </div>

        <div ref="accountMenu" class="appbar-account">
          <button
            class="account-menu-trigger"
            type="button"
            aria-label="User menu"
            aria-haspopup="menu"
            :aria-expanded="accountMenuOpen"
            @click="accountMenuOpen = !accountMenuOpen"
          >
            <span class="user-avatar" aria-hidden="true">{{ userInitial }}</span>
            <span class="account-trigger-copy">
              <strong>{{ session.user?.email ?? 'Signed in' }}</strong>
              <small>Local account</small>
            </span>
            <ChevronDown :size="15" />
          </button>
          <div v-if="accountMenuOpen" class="account-menu" role="menu">
            <div class="account-menu-summary">
              <span class="user-avatar" aria-hidden="true">{{ userInitial }}</span>
              <span>
                <strong>{{ session.user?.email ?? 'Signed in' }}</strong>
                <small>Authenticated session</small>
              </span>
            </div>
            <button type="button" role="menuitem" @click="logout">
              <LogOut :size="16" /> Log out
            </button>
          </div>
        </div>
      </header>
      <div class="main-content"><RouterView /></div>
    </main>
  </div>
</template>

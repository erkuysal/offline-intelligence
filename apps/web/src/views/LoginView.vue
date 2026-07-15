<script setup lang="ts">
import {
  ArrowRight,
  CheckCircle2,
  Database,
  KeyRound,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Sparkles,
  WifiOff,
} from '@lucide/vue'
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { DEMO_CREDENTIALS } from '@/config/demo'
import { useSessionStore } from '@/stores/session'

const email = ref('')
const password = ref('')
const session = useSessionStore()
const router = useRouter()

async function submit() {
  try {
    await session.login(email.value, password.value)
    await router.push({ name: 'documents' })
  } catch {
    // The session store exposes a user-facing error.
  }
}

async function enterDemo() {
  if (!DEMO_CREDENTIALS) return
  email.value = DEMO_CREDENTIALS.email
  password.value = DEMO_CREDENTIALS.password
  await submit()
}
</script>

<template>
  <main class="auth-screen">
    <section class="auth-shell" aria-label="Offline Intelligence Hub access">
      <aside class="auth-story">
        <div class="auth-brand">
          <span class="auth-brand-mark">OI</span>
          <span>
            <strong>Offline Intelligence</strong>
            <small>Private AI workspace</small>
          </span>
        </div>

        <div class="auth-story-copy">
          <span class="auth-story-icon"><Sparkles :size="25" /></span>
          <p class="auth-story-eyebrow">Your knowledge. Your hardware.</p>
          <h2>Turn private documents into answers you can verify.</h2>
          <p>
            Search, retrieve, and chat with your local knowledge base while keeping sensitive data
            under your control.
          </p>
        </div>

        <ul class="auth-trust-list">
          <li><WifiOff :size="17" /><span><strong>Offline-first</strong>Local model execution</span></li>
          <li><ShieldCheck :size="17" /><span><strong>Private by design</strong>Data stays in your workspace</span></li>
          <li><Database :size="17" /><span><strong>Grounded answers</strong>Inspectable source passages</span></li>
        </ul>

        <p class="auth-story-note"><LockKeyhole :size="14" /> No cloud account required</p>
      </aside>

      <section class="auth-form-side">
        <div class="auth-brand auth-brand-mobile">
          <span class="auth-brand-mark">OI</span>
          <span><strong>Offline Intelligence</strong><small>Private AI workspace</small></span>
        </div>

        <form class="auth-panel" @submit.prevent="submit">
          <header class="auth-panel-header">
            <span class="auth-form-icon"><KeyRound :size="20" /></span>
            <div>
              <p class="eyebrow">Welcome back</p>
              <h1>Sign in to your workspace</h1>
              <p>Continue to your private documents and conversations.</p>
            </div>
          </header>

          <div class="auth-fields">
            <label class="auth-field">
              <span>Email address</span>
              <span class="auth-input-wrap">
                <Mail :size="17" aria-hidden="true" />
                <input v-model="email" type="email" autocomplete="email" placeholder="you@example.com" required />
              </span>
            </label>
            <label class="auth-field">
              <span>Password</span>
              <span class="auth-input-wrap">
                <LockKeyhole :size="17" aria-hidden="true" />
                <input
                  v-model="password"
                  type="password"
                  autocomplete="current-password"
                  placeholder="Enter your password"
                  required
                />
              </span>
            </label>
          </div>

          <p v-if="session.error" class="form-error auth-error" role="alert">{{ session.error }}</p>

          <button class="primary-button auth-submit" type="submit" :disabled="session.loading">
            Sign in <ArrowRight :size="17" />
          </button>

          <div v-if="DEMO_CREDENTIALS" class="auth-divider"><span>or preview the workspace</span></div>

          <button v-if="DEMO_CREDENTIALS" class="demo-account-button" type="button" :disabled="session.loading" @click="enterDemo">
            <span class="demo-account-icon"><Sparkles :size="17" /></span>
            <span><strong>Use demo account</strong><small>Open the preloaded local workspace</small></span>
            <ArrowRight :size="17" />
          </button>

          <p class="auth-switch">New to Offline Intelligence? <RouterLink to="/register">Create account</RouterLink></p>

          <div class="auth-local-note">
            <CheckCircle2 :size="15" /> Authentication is handled by your local API.
          </div>
        </form>
      </section>
    </section>
  </main>
</template>

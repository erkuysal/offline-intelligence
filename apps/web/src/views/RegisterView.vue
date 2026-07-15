<script setup lang="ts">
import {
  ArrowRight,
  CheckCircle2,
  Database,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Sparkles,
  UserPlus,
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
    await session.register(email.value, password.value)
    await router.push({ name: 'documents' })
  } catch {
    // The session store exposes a user-facing error.
  }
}

async function enterDemo() {
  if (!DEMO_CREDENTIALS) return
  email.value = DEMO_CREDENTIALS.email
  password.value = DEMO_CREDENTIALS.password
  try {
    await session.login(email.value, password.value)
    await router.push({ name: 'documents' })
  } catch {
    // The session store exposes a user-facing error.
  }
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
          <span class="auth-story-icon"><ShieldCheck :size="25" /></span>
          <p class="auth-story-eyebrow">Build a private corpus</p>
          <h2>Start with documents. Finish with evidence.</h2>
          <p>
            Create a workspace for local retrieval, grounded conversations, and operationally
            transparent AI.
          </p>
        </div>

        <ul class="auth-trust-list">
          <li><WifiOff :size="17" /><span><strong>Offline-first</strong>Works without cloud inference</span></li>
          <li><Database :size="17" /><span><strong>One private corpus</strong>Upload, index, and search locally</span></li>
          <li><Sparkles :size="17" /><span><strong>Clear provenance</strong>Answers link back to passages</span></li>
        </ul>

        <p class="auth-story-note"><LockKeyhole :size="14" /> Your account lives on this installation</p>
      </aside>

      <section class="auth-form-side">
        <div class="auth-brand auth-brand-mobile">
          <span class="auth-brand-mark">OI</span>
          <span><strong>Offline Intelligence</strong><small>Private AI workspace</small></span>
        </div>

        <form class="auth-panel" @submit.prevent="submit">
          <header class="auth-panel-header">
            <span class="auth-form-icon"><UserPlus :size="20" /></span>
            <div>
              <p class="eyebrow">Local account</p>
              <h1>Create your workspace</h1>
              <p>Set up private access to documents, retrieval, and chat.</p>
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
                  autocomplete="new-password"
                  minlength="8"
                  placeholder="At least 8 characters"
                  required
                />
              </span>
              <small class="auth-field-hint">Use at least 8 characters.</small>
            </label>
          </div>

          <p v-if="session.error" class="form-error auth-error" role="alert">{{ session.error }}</p>

          <button class="primary-button auth-submit" type="submit" :disabled="session.loading">
            Create account <ArrowRight :size="17" />
          </button>

          <div v-if="DEMO_CREDENTIALS" class="auth-divider"><span>or preview before creating one</span></div>

          <button v-if="DEMO_CREDENTIALS" class="demo-account-button" type="button" :disabled="session.loading" @click="enterDemo">
            <span class="demo-account-icon"><Sparkles :size="17" /></span>
            <span><strong>Use demo account</strong><small>Enter the existing preloaded workspace</small></span>
            <ArrowRight :size="17" />
          </button>

          <p class="auth-switch">Already have an account? <RouterLink to="/login">Sign in</RouterLink></p>

          <div class="auth-local-note">
            <CheckCircle2 :size="15" /> Credentials are stored by your local installation.
          </div>
        </form>
      </section>
    </section>
  </main>
</template>

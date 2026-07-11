<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

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
</script>

<template>
  <main class="auth-screen">
    <form class="auth-panel" @submit.prevent="submit">
      <h1>Create account</h1>
      <label>Email<input v-model="email" type="email" autocomplete="email" required /></label>
      <label>Password<input v-model="password" type="password" autocomplete="new-password" minlength="8" required /></label>
      <p v-if="session.error" class="form-error">{{ session.error }}</p>
      <button class="primary-button" type="submit" :disabled="session.loading">Create account</button>
      <RouterLink to="/login">Sign in</RouterLink>
    </form>
  </main>
</template>

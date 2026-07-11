<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { useSessionStore } from '@/stores/session'

const email = ref('')
const password = ref('')
const session = useSessionStore()
const router = useRouter()

async function submit() {
  await session.login(email.value, password.value)
  router.push({ name: 'documents' })
}
</script>

<template>
  <main class="auth-screen">
    <form class="auth-panel" @submit.prevent="submit">
      <h1>Sign in</h1>
      <label>Email<input v-model="email" type="email" autocomplete="email" required /></label>
      <label>Password<input v-model="password" type="password" autocomplete="current-password" required /></label>
      <p v-if="session.error" class="form-error">{{ session.error }}</p>
      <button class="primary-button" type="submit" :disabled="session.loading">Sign in</button>
      <RouterLink to="/register">Create account</RouterLink>
    </form>
  </main>
</template>

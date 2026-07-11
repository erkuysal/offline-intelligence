import { createRouter, createWebHistory } from 'vue-router'

import AppShell from '@/components/layout/AppShell.vue'
import { useSessionStore } from '@/stores/session'
import ChatView from '@/views/ChatView.vue'
import DocumentDetailView from '@/views/DocumentDetailView.vue'
import DocumentsView from '@/views/DocumentsView.vue'
import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'
import SystemView from '@/views/SystemView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/register', name: 'register', component: RegisterView, meta: { public: true } },
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', redirect: '/documents' },
        { path: 'documents', name: 'documents', component: DocumentsView },
        {
          path: 'documents/:id',
          name: 'document-detail',
          component: DocumentDetailView,
          props: route => ({ id: Number(route.params.id) }),
        },
        { path: 'chat', name: 'chat', component: ChatView },
        { path: 'system', name: 'system', component: SystemView },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/documents' },
  ],
})

window.addEventListener('offlineHub:session-expired', () => {
  void router.push({ name: 'login' })
})

router.beforeEach(async to => {
  const session = useSessionStore()
  if (!session.user && session.accessToken) await session.loadUser()
  if (!to.meta.public && !session.isAuthenticated) return { name: 'login' }
  if (to.meta.public && session.isAuthenticated) return { name: 'documents' }
})

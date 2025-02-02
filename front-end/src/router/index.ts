import { createRouter, createWebHistory } from 'vue-router'
import InitView from '../views/InitView.vue'
import HomeView from '@/views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'init',
      component: InitView,
    },
    {
      path: '/vendors',
      name: 'vendors',
      component: () => import('../views/VendorsView.vue'),
    },
    {
      path: '/welcome',
      name: 'welcome',
      component: () => import('../views/HomeView.vue'),
    },
  ],
})

export default router

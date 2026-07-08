import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/',        redirect: '/login' },
  { path: '/login',   component: () => import('../views/Login.vue') },
  { path: '/dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/tasks',   component: () => import('../views/TaskList.vue') },
  { path: '/tasks/:id', component: () => import('../views/TaskDetail.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (to.path !== '/login' && !token) return '/login'
  if (to.path === '/login' && token) return '/dashboard'
})

export default router

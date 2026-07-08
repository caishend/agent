import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/',        redirect: '/login' },
  { path: '/login',   component: () => import('../views/Login.vue') },
  { path: '/dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/tasks',   component: () => import('../views/TaskList.vue') },
  { path: '/tasks/:id', component: () => import('../views/TaskDetail.vue') }
]

export default createRouter({
  history: createWebHistory(),
  routes
})

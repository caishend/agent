import { defineStore } from 'pinia'
import { getCurrentUser, login, register } from '../api/auth'

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('userInfo') || 'null')
  } catch {
    localStorage.removeItem('userInfo')
    return null
  }
}

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    userInfo: readStoredUser()
  }),
  getters: {
    displayName: state => state.userInfo?.username || '分析员',
    initials: state => (state.userInfo?.username || 'SG').slice(0, 2).toUpperCase()
  },
  actions: {
    async login(data) {
      const res = await login(data)
      this.token = res.access_token
      this.userInfo = res.user || { username: data.username }
      localStorage.setItem('token', res.access_token)
      localStorage.setItem('userInfo', JSON.stringify(this.userInfo))
    },
    async register(data) {
      return register(data)
    },
    async fetchProfile() {
      if (!this.token) return null
      const user = await getCurrentUser()
      this.userInfo = user
      localStorage.setItem('userInfo', JSON.stringify(user))
      return user
    },
    logout() {
      this.token = ''
      this.userInfo = null
      localStorage.removeItem('token')
      localStorage.removeItem('userInfo')
    }
  }
})

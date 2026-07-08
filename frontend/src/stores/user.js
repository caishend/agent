import { defineStore } from 'pinia'
import { login, register } from '../api/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    userInfo: null
  }),
  actions: {
    async login(data) {
      const res = await login(data)
      this.token = res.access_token
      localStorage.setItem('token', res.access_token)
    },
    logout() {
      this.token = ''
      this.userInfo = null
      localStorage.removeItem('token')
    }
  }
})

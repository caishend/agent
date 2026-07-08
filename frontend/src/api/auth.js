import http from './index'

export const login = (data) => http.post('/auth/login', data)
export const register = (data) => http.post('/auth/register', data)

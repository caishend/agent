import http from './index'

export const getTasks    = ()       => http.get('/tasks')
export const getTask     = (id)     => http.get(`/tasks/${id}`)
export const createTask  = (data)   => http.post('/tasks', data)
export const deleteTask  = (id)     => http.delete(`/tasks/${id}`)
export const uploadFile  = (id, form) => http.post(`/tasks/${id}/upload`, form, {
  headers: { 'Content-Type': 'multipart/form-data' }
})
export const getAnalysis = (id)     => http.get(`/tasks/${id}/analysis`)
export const getReport   = (id)     => http.get(`/tasks/${id}/report`, { responseType: 'blob' })
export const sendReport  = (id, data) => http.post(`/tasks/${id}/report/send`, data)

import http from './index'

export const getTasks = () => http.get('/tasks')
export const getTask = (id) => http.get(`/tasks/${id}`)
export const createTask = (data) => http.post('/tasks', data)
export const deleteTask = (id) => http.delete(`/tasks/${id}`)
export const uploadFile = (id, form) => http.post(`/tasks/${id}/upload`, form, {
  headers: { 'Content-Type': 'multipart/form-data' }
})
export const runAgentMessage = (id, data) => http.post(`/tasks/${id}/agent/message`, data)
export const getChatHistory = (id) => http.get(`/tasks/${id}/chat`)
export const getTaskDocuments = (id) => http.get(`/tasks/${id}/documents`)
export const deleteTaskDocument = (taskId, docId) => http.delete(`/tasks/${taskId}/documents/${docId}`)
export const deleteTaskDocumentByPath = (taskId, filePath) => http.post(`/tasks/${taskId}/documents/delete-path`, { file_path: filePath })
export async function streamAgentMessage(id, data, onEvent) {
  const token = localStorage.getItem('token')
  const response = await fetch(`/api/tasks/${id}/agent/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(data)
  })

  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败：HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      const line = chunk.split('\n').find(item => item.startsWith('data: '))
      if (!line) continue
      onEvent(JSON.parse(line.slice(6)))
    }
  }

  if (buffer.trim().startsWith('data: ')) {
    onEvent(JSON.parse(buffer.trim().slice(6)))
  }
}
export const confirmDraft = (id, data) => http.post(`/tasks/${id}/agent/confirm-draft`, data)
export const getAgentSession = (id) => http.get(`/tasks/${id}/agent/session`)
export const saveAgentRecord = (id, content) => http.post(`/tasks/${id}/agent/record`, { content })
export const clearAgentSession = (id) => http.delete(`/tasks/${id}/agent/session`)
export const runTool = (id, toolName, data) => http.post(`/tasks/${id}/tools/${toolName}`, data)
export const getAnalysis = (id)     => http.get(`/tasks/${id}/analysis`)
export const getReport   = (id)     => http.get(`/tasks/${id}/report`, { responseType: 'blob' })
export const sendReport  = (id, data) => http.post(`/tasks/${id}/report/send`, data)
export const getOverviewSummary = (params = {}) => http.get('/overview/summary', { params })
export const getChinaGeoJson = () => http.get('/overview/china-geojson')
export const getPopulationHeatmap = () => http.get('/overview/population-heatmap')

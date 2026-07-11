import http from './index'

export const getTasks = () => http.get('/tasks')
export const getTask = (id) => http.get(`/tasks/${id}`)
export const createTask = (data) => http.post('/tasks', data)
export const deleteTask = (id) => http.delete(`/tasks/${id}`)
export const uploadFile = (id, form) => http.post(`/tasks/${id}/upload`, form, {
  headers: { 'Content-Type': 'multipart/form-data' }
})
export const uploadTempFile = (id, form) => http.post(`/tasks/${id}/upload-temp`, form, {
  headers: { 'Content-Type': 'multipart/form-data' }
})
export const runAgentMessage = (id, data) => http.post(`/tasks/${id}/agent/message`, data)
export const getChatHistory = (id) => http.get(`/tasks/${id}/chat`)
export const getTaskDocuments = (id) => http.get(`/tasks/${id}/documents`)
export const deleteTaskDocument = (taskId, docId) => http.delete(`/tasks/${taskId}/documents/${docId}`)
export const deleteTaskDocumentByPath = (taskId, filePath) => http.post(`/tasks/${taskId}/documents/delete-path`, { file_path: filePath })
export const deleteTaskArtifact = (taskId, path) => http.post(`/tasks/${taskId}/artifacts/delete`, { path })

export async function streamAgentMessage(id, data, onEvent) {
  const token = localStorage.getItem('token')
  const apiBaseUrl = String(http.defaults.baseURL || '/api').replace(/\/$/, '')
  const response = await fetch(`${apiBaseUrl}/tasks/${id}/agent/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
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

  const dispatchBlock = async block => {
    const normalizedBlock = block.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
    const dataLines = normalizedBlock
      .split('\n')
      .filter(line => line === 'data:' || line.startsWith('data:'))
      .map(line => line.slice(5).replace(/^ /, ''))
    if (!dataLines.length) return
    const payload = dataLines.join('\n')
    if (payload === '[DONE]') return
    await onEvent(JSON.parse(payload))
  }

  const consumeEvents = async (flush = false) => {
    // Match complete boundaries in the raw buffer. A CRLF pair may itself be
    // split across reads, so normalizing each received chunk is not safe.
    let boundary = buffer.match(/\r\n\r\n|\n\n|\r\r/)
    while (boundary) {
      const index = boundary.index ?? 0
      const block = buffer.slice(0, index)
      buffer = buffer.slice(index + boundary[0].length)
      await dispatchBlock(block)
      boundary = buffer.match(/\r\n\r\n|\n\n|\r\r/)
    }

    if (flush && buffer.trim()) {
      const block = buffer
      buffer = ''
      await dispatchBlock(block)
    } else if (flush) {
      buffer = ''
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    await consumeEvents()
  }

  buffer += decoder.decode()
  await consumeEvents(true)
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

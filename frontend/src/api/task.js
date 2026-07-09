import http from './index'

export const getTasks = () => http.get('/tasks')
export const getTask = (id) => http.get(`/tasks/${id}`)
export const createTask = (data) => http.post('/tasks', data)
export const deleteTask = (id) => http.delete(`/tasks/${id}`)
export const uploadFile = (id, form) => http.post(`/tasks/${id}/upload`, form, {
  headers: { 'Content-Type': 'multipart/form-data' }
})
export const getTaskDocuments = (id) => http.get(`/tasks/${id}/documents`)
export const runAgentMessage = (id, data) => http.post(`/tasks/${id}/agent/message`, data)
export const getChatHistory = (id) => http.get(`/tasks/${id}/chat`)

export async function streamAgentMessage(id, data, onEvent) {
  const token = localStorage.getItem('token')
  const response = await fetch(`/api/tasks/${id}/agent/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'Cache-Control': 'no-cache',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(data)
  })

  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `Stream request failed: HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = consumeSseBuffer(buffer, onEvent)
  }

  buffer += decoder.decode()
  consumeSseBuffer(`${buffer}\n\n`, onEvent)
}

function consumeSseBuffer(buffer, onEvent) {
  const chunks = buffer.split(/\r?\n\r?\n/)
  const rest = chunks.pop() || ''

  for (const chunk of chunks) {
    const data = chunk
      .split(/\r?\n/)
      .filter(line => line.startsWith('data:'))
      .map(line => line.replace(/^data:\s?/, ''))
      .join('\n')
      .trim()
    if (!data || data === '[DONE]') continue

    try {
      onEvent(JSON.parse(data))
    } catch (error) {
      onEvent({ type: 'error', content: `Stream parse failed: ${error.message}` })
    }
  }

  return rest
}

export const confirmDraft = (id, data) => http.post(`/tasks/${id}/agent/confirm-draft`, data)
export const getAgentSession = (id) => http.get(`/tasks/${id}/agent/session`)
export const clearAgentSession = (id) => http.delete(`/tasks/${id}/agent/session`)
export const runTool = (id, toolName, data) => http.post(`/tasks/${id}/tools/${toolName}`, data)
export const getAnalysis = (id) => http.get(`/tasks/${id}/analysis`)
export const getReport = (id) => http.get(`/tasks/${id}/report`, { responseType: 'blob' })
export const sendReport = (id, data) => http.post(`/tasks/${id}/report/send`, data)

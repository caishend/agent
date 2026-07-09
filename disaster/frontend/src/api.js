const BASE = '' // 开发时 vite proxy 处理，生产时可设为后端地址

export async function checkHealth() {
  const res = await fetch(`${BASE}/health`)
  return res.json()
}

export async function predictImage(file, threshold) {
  const form = new FormData()
  form.append('file', file)
  let url = `${BASE}/predict/image`
  if (threshold != null && threshold >= 0 && threshold <= 1) {
    url += `?threshold=${threshold}`
  }
  const res = await fetch(url, { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || '图片推理失败')
  }
  return res.json()
}

export async function predictVideo(file, threshold) {
  const form = new FormData()
  form.append('file', file)
  let url = `${BASE}/predict/video`
  if (threshold != null && threshold >= 0 && threshold <= 1) {
    url += `?threshold=${threshold}`
  }
  const res = await fetch(url, { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || '视频推理失败')
  }
  return res.json()
}

// 流式视频推理：边处理边推送标注帧。onEvent 收到 {type:'frame'|'done'|'error', ...}
export async function predictVideoStream(file, threshold, onEvent, signal) {
  const form = new FormData()
  form.append('file', file)
  let url = `${BASE}/predict/video/stream`
  if (threshold != null && threshold >= 0 && threshold <= 1) {
    url += `?threshold=${threshold}`
  }
  const res = await fetch(url, { method: 'POST', body: form, signal })
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || '视频推理失败')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sep
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const line = chunk.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      let event
      try {
        event = JSON.parse(payload)
      } catch {
        continue
      }
      onEvent(event)
    }
  }
}

export async function fetchHistory() {
  const res = await fetch(`${BASE}/history`)
  if (!res.ok) {
    throw new Error('获取历史记录失败')
  }
  return res.json()
}

export function resultUrl(path) {
  if (!path) return ''
  return `${BASE}${path}`
}

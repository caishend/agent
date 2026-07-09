<template>
  <AppShell>
    <div class="simple-workbench">
      <header class="simple-chat-header">
        <div>
          <div class="workspace-kicker">SkyGuard Agent</div>
          <h1>{{ task?.task_name || '新分析对话' }}</h1>
        </div>
        <button class="ghost-button" @click="clearSession">清空上下文</button>
      </header>

      <section ref="messagePanel" class="simple-message-panel">
        <div v-if="!messages.length" class="empty-chat">
          <h2>你好，准备开始了吗？</h2>
          <p>直接输入即可对话；Agent 会判断意图并按需调用搜索、截图、文档、GraphRAG、遥感、报告和邮件工具。</p>
        </div>

        <article v-for="item in messages" :key="item.id" class="message-row" :class="item.role">
          <div class="avatar">{{ item.role === 'user' ? '你' : 'SG' }}</div>
          <div class="bubble">
            <div class="message-meta">{{ item.title }}</div>
            <div v-if="item.role === 'agent' && item.requestText" class="current-request">
              <span>本轮请求</span>
              <strong>{{ item.requestText }}</strong>
            </div>
            <details v-if="item.progress?.length" class="trace-panel" :open="item.traceOpen !== false">
              <summary>
                <span>执行轨迹</span>
                <small>{{ latestProgress(item.progress) }}</small>
              </summary>
              <div class="progress-list">
                <div v-for="(step, index) in item.progress" :key="index" class="progress-step">
                  <span class="progress-dot">{{ progressIcon(step, index, item.progress.length) }}</span>
                  <span>{{ step }}</span>
                </div>
              </div>
            </details>

            <div v-if="item.role === 'agent'" class="message-content markdown-body" v-html="renderMarkdown(item.content)" />
            <div v-else class="message-content">{{ item.content }}</div>

            <div v-if="displayArtifacts(item.artifacts).length" class="artifact-panel">
              <div v-for="artifact in displayArtifacts(item.artifacts)" :key="artifact.path" class="artifact-card">
                <div class="artifact-title">
                  {{ artifact.type === 'screenshot' ? '浏览器真实截图' : artifact.type === 'report' ? '分析报告已生成' : '工具产物' }}
                </div>
                <a :href="artifactUrl(artifact)" target="_blank" rel="noreferrer">
                  <img v-if="artifact.type === 'screenshot'" :src="artifactUrl(artifact)" alt="网页截图" />
                  <span v-else>{{ artifactName(artifact) }}</span>
                </a>
                <small>{{ artifact.metadata?.url || artifact.path }}</small>
              </div>
            </div>

            <details v-if="item.searchResults?.length" class="evidence-panel">
              <summary>
                搜索证据 · {{ item.searchResults.length }} 条
                <span>{{ compactSearchSummary(item.searchResults) }}</span>
              </summary>
              <div class="search-result-list">
                <a
                  v-for="(result, index) in item.searchResults"
                  :key="index"
                  class="search-result-card"
                  :href="result.url || undefined"
                  target="_blank"
                  rel="noreferrer"
                >
                  <strong>{{ result.title || result.name || `搜索结果 ${index + 1}` }}</strong>
                  <span>{{ result.content || result.snippet || result.summary || '暂无摘要' }}</span>
                  <small v-if="result.url">{{ result.url }}</small>
                </a>
              </div>
            </details>

            <details v-if="item.data" class="json-details">
              <summary>查看结构化数据</summary>
              <pre class="json-block">{{ pretty(item.data) }}</pre>
            </details>

            <div v-if="item.needConfirm" class="confirm-box">
              <span>这些信息是否需要保留到正式任务记忆？</span>
              <button class="solid-button inline" @click="confirmDraftFromMessage(item)">确认保留</button>
            </div>

            <div v-if="item.needReportFormat" class="confirm-box">
              <span>请选择报告导出格式：</span>
              <button class="solid-button inline" @click="chooseReportFormat(item, 'docx')">Word</button>
              <button class="ghost-button inline" @click="chooseReportFormat(item, 'pdf')">PDF</button>
            </div>
          </div>
        </article>
      </section>

      <aside class="simple-side-panel">
        <section class="record-card">
          <div class="rail-title">本次对话记录</div>
          <textarea
            v-model="conversationRecord"
            class="record-editor"
            placeholder="可编辑保存：关键信息、已确认事实、后续需要进入灾害分析/报告的信息。"
          />
          <div class="record-actions">
            <button class="ghost-button" @click="generateRecord">从对话生成</button>
            <button class="solid-button inline" @click="saveRecord">保存</button>
          </div>
          <small v-if="recordSavedAt">已保存 {{ recordSavedAt }}</small>
          <details v-if="conversationRecord.trim()" class="record-preview">
            <summary>预览保存内容</summary>
            <div class="markdown-body" v-html="renderMarkdown(conversationRecord)" />
          </details>
        </section>

        <section class="upload-card">
          <div class="rail-title">相关文档</div>
          <label class="upload-zone">
            <input type="file" @change="upload" />
            <span>上传本次对话相关文档/图片</span>
          </label>
          <div class="uploaded-list">
            <div v-for="file in uploadedFiles" :key="file.file_path" class="uploaded-item">
              <a :href="fileUrl(file)" target="_blank" rel="noreferrer">
                <strong>{{ file.filename }}</strong>
                <small>{{ file.file_type }} · 点击预览/下载</small>
              </a>
              <button class="doc-delete-button" type="button" @click="removeDocument(file)">删除</button>
            </div>
          </div>
        </section>
      </aside>

      <form class="simple-composer" @submit.prevent="runAgent">
        <div class="tool-picker">
          <button type="button" class="attach-button" :class="{ active: selectedTool }" @click="toolMenuOpen = !toolMenuOpen">
            {{ selectedTool ? selectedTool.icon : '+' }}
          </button>
          <div v-if="toolMenuOpen" class="tool-menu">
            <button type="button" class="tool-option" @click="chooseTool(null)">
              <span>💬</span>
              <span><strong>自动判断</strong><small>由 LLM 判断是否调用工具</small></span>
            </button>
            <button v-for="tool in toolOptions" :key="tool.value" type="button" class="tool-option" @click="chooseTool(tool)">
              <span>{{ tool.icon }}</span>
              <span><strong>{{ tool.label }}</strong><small>{{ tool.desc }}</small></span>
            </button>
          </div>
        </div>

        <textarea
          v-model="message"
          rows="1"
          :placeholder="selectedTool ? selectedTool.placeholder : '例如：搜索成都暴雨最新预警并截图'"
          @keydown.enter.exact.prevent="runAgent"
        />
        <button class="send-button" :disabled="loading || !message.trim()">{{ loading ? '…' : '→' }}</button>
      </form>
    </div>
  </AppShell>
</template>

<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import {
  clearAgentSession,
  confirmDraft,
  deleteTaskDocument,
  deleteTaskDocumentByPath,
  getAgentSession,
  getChatHistory,
  getTaskDocuments,
  getTask,
  saveAgentRecord,
  streamAgentMessage,
  uploadFile
} from '../api/task'

marked.setOptions({ breaks: true, gfm: true })

const route = useRoute()
const taskId = computed(() => route.params.id)
const recordKey = computed(() => `skyguard:conversation-record:${taskId.value}`)

const task = ref(null)
const message = ref('')
const loading = ref(false)
const messages = ref([])
const session = ref({})
const uploadedFiles = ref([])
const messagePanel = ref(null)
const selectedTool = ref(null)
const toolMenuOpen = ref(false)
const conversationRecord = ref('')
const recordSavedAt = ref('')
const typingState = new Map()

const toolOptions = [
  { value: 'browser', icon: '🌐', label: '网页搜索', desc: '搜索网页并可用浏览器截图', placeholder: '搜索成都暴雨最新预警并截图' },
  { value: 'research', icon: '🔎', label: '深度研究', desc: 'GraphRAG / 文档综合检索', placeholder: '输入需要深度研究的问题' },
  { value: 'remote_sensing', icon: '🛰️', label: '图像识别', desc: '遥感影像或图片识别', placeholder: '描述要从图片中识别什么' },
  { value: 'disaster_analysis', icon: '⚠️', label: '灾害分析/报告', desc: '整合记录、文档、联网搜索并生成报告', placeholder: '描述灾害分析目标，系统会先询问导出 Word 还是 PDF' },
  { value: 'report', icon: '📄', label: '生成报告', desc: '选择格式后生成 Word/PDF 报告', placeholder: '生成一份灾害研判报告' },
  { value: 'email', icon: '✉️', label: '发送邮件', desc: '发送正文或报告附件', placeholder: '发给 xxx@example.com，并附上报告' }
]

onMounted(() => loadTaskState())
watch(taskId, () => loadTaskState())

async function loadTaskState() {
  if (!taskId.value) return
  task.value = await getTask(taskId.value)
  messages.value = []
  uploadedFiles.value = []
  selectedTool.value = null
  toolMenuOpen.value = false
  await refreshSession()
  await loadUploadedDocuments()
  await loadChatHistory()
  conversationRecord.value = session.value.conversation_record || localStorage.getItem(recordKey.value) || ''
  recordSavedAt.value = ''
}

async function loadUploadedDocuments() {
  uploadedFiles.value = await getTaskDocuments(taskId.value)
}

async function loadChatHistory() {
  const history = await getChatHistory(taskId.value)
  const restored = []
  let pendingTrace = null

  for (const item of history) {
    if (item.role === 'tool') {
      const parsedTrace = parseTraceRecord(item.content)
      if (parsedTrace) pendingTrace = parsedTrace
      continue
    }

    if (item.role === 'assistant') {
      restored.push({
        id: `db-${item.conv_id}`,
        role: 'agent',
        title: 'Agent',
        content: item.content,
        requestText: pendingTrace?.requestText,
        progress: pendingTrace?.progress || [],
        searchResults: pendingTrace?.searchResults || [],
        artifacts: pendingTrace?.artifacts || [],
        data: pendingTrace?.data,
        traceOpen: false
      })
      pendingTrace = null
      continue
    }

    restored.push({
      id: `db-${item.conv_id}`,
      role: 'user',
      title: '用户',
      content: item.content
    })
  }

  if (pendingTrace) {
    restored.push({
      id: `trace-${crypto.randomUUID()}`,
      role: 'agent',
      title: 'Agent · 执行轨迹',
      content: '本轮执行轨迹已恢复；如果没有最终回答，可能是页面刷新或请求中断导致。',
      requestText: pendingTrace.requestText,
      progress: pendingTrace.progress || [],
      searchResults: pendingTrace.searchResults || [],
      artifacts: pendingTrace.artifacts || [],
      data: pendingTrace.data,
      traceOpen: true
    })
  }

  messages.value = restored
  syncArtifactsToRelatedFiles(restored)
  await scrollToBottom()
}

function parseTraceRecord(content) {
  try {
    const parsed = JSON.parse(content || '{}')
    if (parsed?.kind !== 'agent_trace') return null
    return {
      requestText: parsed.requestText || '',
      progress: Array.isArray(parsed.progress) ? parsed.progress : [],
      searchResults: Array.isArray(parsed.searchResults) ? parsed.searchResults : [],
      artifacts: Array.isArray(parsed.artifacts) ? parsed.artifacts : [],
      data: parsed.data || null
    }
  } catch {
    return null
  }
}

async function runAgent() {
  const text = message.value.trim()
  if (!text || loading.value) return

  const currentTool = selectedTool.value
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'user',
    title: currentTool ? `用户 · ${currentTool.label}` : '用户',
    content: text
  })
  await scrollToBottom()

  message.value = ''
  toolMenuOpen.value = false
  loading.value = true
  const progressMessage = {
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 执行中',
    content: '正在准备...',
    requestText: text,
    progress: ['请求已发送，等待后端开始流式响应...'],
    traceOpen: true,
    searchResults: [],
    artifacts: []
  }
  messages.value.push(progressMessage)
  await scrollToBottom()

  try {
    const params = {
      conversation_record: conversationRecord.value,
      ...(currentTool ? { forced_tool: currentTool.value } : {})
    }
    await streamAgentMessage(taskId.value, { message: text, files: currentFilePayload(), params }, event => {
      handleStreamEvent(event, progressMessage)
    })
  } catch (error) {
    progressMessage.title = 'Agent · 调用失败'
    progressMessage.content = error?.response?.data?.detail || error.message || '调用失败，请检查后端服务。'
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

function handleStreamEvent(event, progressMessage) {
  if (event.type === 'report_format_required') {
    progressMessage.title = 'Agent · 等待选择'
    progressMessage.content = event.content
    progressMessage.needReportFormat = true
    progressMessage.progress.push('需要用户选择报告格式')
    scrollToBottom()
    return
  }

  if (event.type === 'thinking' || event.type === 'tool_call' || event.type === 'llm_call') {
    progressMessage.content = event.content
    progressMessage.progress.push(event.content)
    scrollToBottom()
    return
  }

  if (event.type === 'intent') {
    progressMessage.progress.push(event.content)
    scrollToBottom()
    return
  }

  if (event.type === 'answer_delta') {
    if (!progressMessage.streamingAnswerStarted) {
      progressMessage.title = 'Agent · LLM 生成中'
      progressMessage.content = ''
      progressMessage.streamingAnswerStarted = true
    }
    enqueueAnswerDelta(progressMessage, event.content || '')
    return
  }

  if (event.type === 'llm_fallback') {
    progressMessage.progress.push(event.content)
    scrollToBottom()
    return
  }

  if (event.type === 'tool_result') {
    const toolLabel = event.tool ? `工具 ${event.tool}` : '工具'
    progressMessage.content = `${toolLabel} 已完成`
    progressMessage.progress.push(`${toolLabel} 已完成`)
    if (event.tool === 'browser' && event.data?.search_results?.length) {
      progressMessage.searchResults = event.data.search_results
    }
    if (event.tool === 'browser' && event.data?.screenshot_observations?.length) {
      progressMessage.progress.push(...event.data.screenshot_observations)
    }
    if (event.artifacts?.length) {
      progressMessage.artifacts = [...(progressMessage.artifacts || []), ...event.artifacts]
      addArtifactsToRelatedFiles(event.artifacts)
      if (event.artifacts.some(artifact => artifact.type === 'report')) loadUploadedDocuments()
    }
    if (event.need_user_confirm && event.data?.draft) {
      messages.value.push({
        id: crypto.randomUUID(),
        role: 'agent',
        title: 'Agent',
        content: '我识别到你可能要进行灾害分析。下面是根据本轮对话生成的临时信息草稿，请确认哪些信息需要保留。',
        data: event.data.draft,
        draft: event.data.draft,
        needConfirm: true
      })
    }
    scrollToBottom()
    return
  }

  if (event.type === 'answer') {
    progressMessage.title = 'Agent'
    progressMessage.traceOpen = false
    finishTyping(progressMessage, event.content || progressMessage.content || '已完成。')
    scrollToBottom()
    return
  }

  if (event.type === 'done') {
    session.value = event.session || session.value
    return
  }

  if (event.type === 'error') {
    progressMessage.title = 'Agent · 调用失败'
    progressMessage.content = event.content || event.error || '调用失败。'
  }
}

async function chooseReportFormat(item, format) {
  if (loading.value) return
  item.needReportFormat = false
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'user',
    title: '用户 · 报告格式',
    content: format === 'docx' ? 'Word' : 'PDF'
  })

  loading.value = true
  const progressMessage = {
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 生成报告中',
    content: `已选择 ${format === 'docx' ? 'Word' : 'PDF'}，正在生成灾害分析报告...`,
    requestText: item.requestText || conversationRecord.value || '继续生成灾害分析报告',
    progress: ['已选择报告格式，等待后端继续执行...'],
    traceOpen: true,
    searchResults: [],
    artifacts: []
  }
  messages.value.push(progressMessage)
  await scrollToBottom()

  try {
    await streamAgentMessage(taskId.value, {
      message: format === 'docx' ? 'Word' : 'PDF',
      files: currentFilePayload(),
      params: {
        conversation_record: conversationRecord.value,
        report_format: format,
        format
      }
    }, event => handleStreamEvent(event, progressMessage))
  } catch (error) {
    progressMessage.title = 'Agent · 调用失败'
    progressMessage.content = error?.response?.data?.detail || error.message || '报告生成失败。'
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

async function confirmDraftFromMessage(item) {
  if (!item.draft) return
  const result = await confirmDraft(taskId.value, { draft: item.draft })
  session.value.formal_memory = result.data.formal_memory
  item.needConfirm = false
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 已确认',
    content: '已写入正式任务记忆。后续可以继续要求风险评估、生成报告或邮件发送。'
  })
}

async function upload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  const uploaded = await uploadFile(taskId.value, form)
  uploadedFiles.value.push(uploaded)
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 文件已上传',
    content: `已接入 **${uploaded.filename}**，后续研究、灾害分析和报告都会自动带上该文件。`
  })
  event.target.value = ''
}

async function removeDocument(file) {
  if (file.doc_id) {
    await deleteTaskDocument(taskId.value, file.doc_id)
  } else if (file.file_path) {
    await deleteTaskDocumentByPath(taskId.value, file.file_path)
  }
  uploadedFiles.value = uploadedFiles.value.filter(item => item !== file && item.file_path !== file.file_path)
}

async function refreshSession() {
  const payload = await getAgentSession(taskId.value)
  session.value = payload.session || {}
}

async function clearSession() {
  await clearAgentSession(taskId.value)
  session.value = {}
  messages.value = []
  localStorage.removeItem(recordKey.value)
  conversationRecord.value = ''
  recordSavedAt.value = ''
}

function chooseTool(tool) {
  selectedTool.value = tool
  toolMenuOpen.value = false
}

function generateRecord() {
  conversationRecord.value = messages.value
    .filter(item => item.role === 'user' || item.role === 'agent')
    .map(formatRecordItem)
    .filter(Boolean)
    .join('\n\n---\n\n')
}

function formatRecordItem(item) {
  const lines = [`## ${item.title || (item.role === 'user' ? '用户' : 'Agent')}`]
  if (item.requestText) lines.push(`**本轮请求：** ${item.requestText}`)
  if (item.content) lines.push(item.content)
  if (item.artifacts?.length) {
    lines.push('', '**相关图片/产物：**')
    for (const artifact of item.artifacts) {
      const url = artifactUrl(artifact)
      const name = artifactName(artifact)
      if (artifact.type === 'screenshot') {
        lines.push(`![${name}](${url})`)
        if (artifact.metadata?.url) lines.push(`来源网页：${artifact.metadata.url}`)
      } else {
        lines.push(`- [${name}](${url})`)
      }
    }
  }
  if (item.searchResults?.length) {
    lines.push('', '**搜索来源：**')
    for (const result of item.searchResults.slice(0, 5)) {
      const title = result.title || result.name || result.url || '搜索结果'
      const snippet = result.content || result.snippet || result.summary || ''
      lines.push(`- ${result.url ? `[${title}](${result.url})` : title}${snippet ? `：${snippet}` : ''}`)
    }
  }
  return lines.join('\n\n')
}

async function saveRecord() {
  localStorage.setItem(recordKey.value, conversationRecord.value)
  await saveAgentRecord(taskId.value, conversationRecord.value)
  session.value.conversation_record = conversationRecord.value
  recordSavedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function renderMarkdown(content) {
  return DOMPurify.sanitize(marked.parse(content || ''))
}

function compactSearchSummary(results) {
  const first = results[0]
  const title = first?.title || first?.name || '搜索结果'
  const text = first?.content || first?.snippet || first?.summary || ''
  return `${title}${text ? `：${text.slice(0, 42)}...` : ''}`
}

function latestProgress(progress = []) {
  const latest = progress[progress.length - 1] || '等待执行'
  return latest.length > 42 ? `${latest.slice(0, 42)}...` : latest
}

function progressIcon(step, index, total) {
  if (index === total - 1) return '●'
  if (String(step).includes('失败')) return '!'
  return '✓'
}

function artifactUrl(artifact) {
  const normalized = String(artifact.path || '').replaceAll('\\', '/')
  const filename = normalized.split('/').pop()
  if (artifact.type === 'screenshot' && filename) return `/artifacts/screenshots/${filename}`
  if (artifact.type === 'report' && filename) return `/artifacts/reports/${filename}`
  return normalized
}

function artifactName(artifact) {
  const normalized = String(artifact.path || '').replaceAll('\\', '/')
  return normalized.split('/').pop() || normalized || '打开产物'
}

function displayArtifacts(artifacts = []) {
  return (artifacts || []).filter(artifact => artifact.type !== 'report_metadata')
}

function fileUrl(file) {
  if (file.artifact) return artifactUrl(file.artifact)
  const normalized = String(file.file_path || '').replaceAll('\\', '/')
  if (normalized.startsWith('data/uploads/')) return `/artifacts/uploads/${normalized.slice('data/uploads/'.length)}`
  if (normalized.startsWith('data/reports/')) return `/artifacts/reports/${normalized.split('/').pop()}`
  return normalized.startsWith('/artifacts/') ? normalized : normalized
}

function syncArtifactsToRelatedFiles(items) {
  for (const item of items) addArtifactsToRelatedFiles(item.artifacts || [])
}

function addArtifactsToRelatedFiles(artifacts = []) {
  for (const artifact of artifacts) {
    if (artifact.type !== 'report') continue
    const path = String(artifact.path || '')
    if (!path || uploadedFiles.value.some(file => file.file_path === path)) continue
    uploadedFiles.value.push({
      filename: artifactName(artifact),
      file_type: (artifact.metadata?.format || path.split('.').pop() || 'REPORT').toUpperCase(),
      file_path: path,
      artifact
    })
  }
}

function currentFilePayload() {
  return uploadedFiles.value.map(file => ({
    path: file.file_path,
    name: file.filename,
    type: file.file_type
  }))
}

function enqueueAnswerDelta(messageItem, text) {
  if (!text) return
  let state = typingState.get(messageItem.id)
  if (!state) {
    state = { queue: '', timer: null, finalContent: '' }
    typingState.set(messageItem.id, state)
  }
  state.queue += text
  if (!state.timer) {
    state.timer = window.setInterval(() => {
      const current = typingState.get(messageItem.id)
      if (!current) return
      if (!current.queue.length) {
        if (current.finalContent) {
          messageItem.content = current.finalContent
          cleanupTyping(messageItem)
        }
        return
      }
      const chunk = current.queue.slice(0, 2)
      current.queue = current.queue.slice(2)
      messageItem.content += chunk
      scrollToBottom()
    }, 18)
  }
}

function finishTyping(messageItem, finalContent) {
  const state = typingState.get(messageItem.id)
  if (!state) {
    messageItem.content = finalContent
    delete messageItem.streamingAnswerStarted
    return
  }
  state.finalContent = finalContent
  if (!state.queue.length) {
    messageItem.content = finalContent
    cleanupTyping(messageItem)
  }
}

function cleanupTyping(messageItem) {
  const state = typingState.get(messageItem.id)
  if (state?.timer) window.clearInterval(state.timer)
  typingState.delete(messageItem.id)
  delete messageItem.streamingAnswerStarted
}

async function scrollToBottom() {
  await nextTick()
  if (messagePanel.value) messagePanel.value.scrollTop = messagePanel.value.scrollHeight
}

function pretty(value) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}
</script>


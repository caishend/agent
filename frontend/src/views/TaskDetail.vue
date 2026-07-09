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

            <div
              v-if="item.role === 'agent'"
              class="message-content markdown-body"
              v-html="renderMarkdown(item.content)"
            />
            <div v-else class="message-content">{{ item.content }}</div>

            <div v-if="item.attachments?.length" class="message-attachments">
              <a
                v-for="file in item.attachments"
                :key="file.file_path || file.doc_id || file.filename"
                class="message-attachment"
                :href="filePreviewUrl(file) || undefined"
                target="_blank"
                rel="noreferrer"
              >
                <img v-if="isUploadedImage(file) && filePreviewUrl(file)" :src="filePreviewUrl(file)" alt="upload preview" />
                <span v-else class="attachment-icon">{{ attachmentIcon(file) }}</span>
                <span>
                  <strong>{{ file.filename }}</strong>
                  <small>{{ file.file_type || file.type || 'FILE' }}</small>
                </span>
              </a>
            </div>

            <details v-if="item.progress?.length" class="trace-panel" open>
              <summary>已规划任务、调用工具、生成结果 · {{ item.progress.length }} 步</summary>
              <div class="progress-list">
                <div v-for="(step, index) in item.progress" :key="index" class="progress-step">
                  <span class="progress-dot">{{ index + 1 }}</span>
                  <span>{{ step }}</span>
                </div>
              </div>
            </details>

            <div v-if="item.artifacts?.length" class="artifact-panel">
              <div v-for="artifact in item.artifacts" :key="artifact.path" class="artifact-card">
                <div class="artifact-title">{{ artifactTitle(artifact) }}</div>
                <a :href="artifactUrl(artifact)" target="_blank" rel="noreferrer">
                  <img v-if="isImageArtifact(artifact)" :src="artifactUrl(artifact)" alt="artifact preview" />
                  <span v-else>{{ artifact.path }}</span>
                </a>
                <div v-if="artifactMeta(artifact)" class="artifact-meta">{{ artifactMeta(artifact) }}</div>
                <small>{{ artifact.metadata?.url || artifactUrl(artifact) }}</small>
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
        </section>

        <section class="upload-card">
          <div class="rail-title">相关文档</div>
          <label class="upload-zone">
            <input type="file" multiple @change="upload" />
            <span>上传本次对话相关文档</span>
          </label>
          <div class="uploaded-list">
            <div v-for="file in visibleUploadedFiles" :key="file.file_path" class="uploaded-item">
              <strong>{{ file.filename }}</strong>
              <small>{{ file.file_type }}</small>
            </div>
          </div>
        </section>
      </aside>

      <form class="simple-composer" @submit.prevent="runAgent">
        <div class="composer-files" v-if="pendingFiles.length">
          <div
            v-for="file in pendingFiles"
            :key="file.file_path || file.doc_id || file.filename"
            class="composer-file-chip"
          >
            <img v-if="isUploadedImage(file) && filePreviewUrl(file)" :src="filePreviewUrl(file)" alt="pending upload" />
            <span v-else>{{ attachmentIcon(file) }}</span>
            <strong>{{ file.filename }}</strong>
            <button type="button" title="移除附件" @click="removePendingFile(file)">×</button>
          </div>
        </div>

        <div class="composer-actions">
          <input ref="composerFileInput" class="hidden-file-input" type="file" multiple @change="attachFromComposer" />
          <button type="button" class="attach-button" title="上传文件或图片" :disabled="loading || uploading" @click="openComposerFilePicker">
            {{ uploading ? '…' : '+' }}
          </button>
          <div class="tool-picker">
            <button type="button" class="tool-button" :class="{ active: selectedTool }" title="选择工具" @click="toolMenuOpen = !toolMenuOpen">
              {{ selectedTool ? selectedTool.icon : '⌘' }}
            </button>
            <div v-if="toolMenuOpen" class="tool-menu">
              <button type="button" class="tool-option" @click="chooseTool(null)">
                <span>💬</span>
                <span><strong>自动判断</strong><small>由 LLM 判断是否调用工具</small></span>
              </button>
              <button
                v-for="tool in toolOptions"
                :key="tool.value"
                type="button"
                class="tool-option"
                @click="chooseTool(tool)"
              >
                <span>{{ tool.icon }}</span>
                <span><strong>{{ tool.label }}</strong><small>{{ tool.desc }}</small></span>
              </button>
            </div>
          </div>
        </div>

        <textarea
          v-model="message"
          rows="1"
          :placeholder="selectedTool ? selectedTool.placeholder : '例如：上传图片后问：识别这张图里的灾害目标'"
          @keydown.enter.exact.prevent="runAgent"
        />
        <button class="send-button" :disabled="loading || uploading || !canSend">
          {{ loading ? '…' : '→' }}
        </button>
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
  getAgentSession,
  getChatHistory,
  getTask,
  getTaskDocuments,
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
const uploading = ref(false)
const messages = ref([])
const session = ref({})
const uploadedFiles = ref([])
const pendingFiles = ref([])
const messagePanel = ref(null)
const composerFileInput = ref(null)
const selectedTool = ref(null)
const toolMenuOpen = ref(false)
const conversationRecord = ref('')
const recordSavedAt = ref('')
const typingState = new Map()

const canSend = computed(() => Boolean(message.value.trim() || pendingFiles.value.length))
const visibleUploadedFiles = computed(() => uploadedFiles.value.filter(file => !isUploadedImage(file)))

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
  pendingFiles.value = []
  selectedTool.value = null
  toolMenuOpen.value = false
  await refreshSession()
  await loadDocuments()
  await loadChatHistory()
  conversationRecord.value = localStorage.getItem(recordKey.value) || ''
  recordSavedAt.value = ''
}

async function loadChatHistory() {
  const history = await getChatHistory(taskId.value)
  messages.value = history.map(item => ({
    id: `db-${item.conv_id}`,
    role: item.role === 'user' ? 'user' : 'agent',
    title: item.role === 'user' ? '用户' : 'Agent',
    content: item.content
  }))
  await scrollToBottom()
}

async function loadDocuments() {
  uploadedFiles.value = await getTaskDocuments(taskId.value)
}

async function runAgent() {
  const text = message.value.trim()
  if (!canSend.value || loading.value || uploading.value) return

  const currentTool = selectedTool.value
  const attachments = [...pendingFiles.value]
  const userContent = text ? withAttachmentSummary(text, attachments) : attachmentPrompt(attachments)
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'user',
    title: currentTool ? `用户 · ${currentTool.label}` : '用户',
    content: userContent,
    attachments
  })

  message.value = ''
  pendingFiles.value = []
  toolMenuOpen.value = false
  loading.value = true
  const progressMessage = {
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 执行中',
    content: '正在准备...',
    requestText: userContent,
    progress: [],
    searchResults: [],
    artifacts: []
  }
  messages.value.push(progressMessage)
  await scrollToBottom()

  try {
    const files = currentFilePayload(currentTurnFiles(attachments))
    const params = {
      conversation_record: conversationRecord.value,
      ...(currentTool ? { forced_tool: currentTool.value } : {})
    }
    await streamAgentMessage(taskId.value, { message: userContent, files, params }, event => {
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
    if (event.artifacts?.length) {
      progressMessage.artifacts = [...(progressMessage.artifacts || []), ...event.artifacts]
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
    const finalContent = event.content || progressMessage.content || '已完成。'
    if (!progressMessage.streamingAnswerStarted) {
      progressMessage.content = ''
      progressMessage.streamingAnswerStarted = true
      enqueueAnswerDelta(progressMessage, finalContent)
    }
    finishTyping(progressMessage, finalContent)
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
    progress: [],
    searchResults: [],
    artifacts: []
  }
  messages.value.push(progressMessage)
  await scrollToBottom()

  try {
    const params = {
      conversation_record: conversationRecord.value,
      report_format: format,
      format
    }
    await streamAgentMessage(taskId.value, {
      message: format === 'docx' ? 'Word' : 'PDF',
      files: currentFilePayload(currentTurnFiles()),
      params
    }, event => handleStreamEvent(event, progressMessage))
  } catch (error) {
    progressMessage.title = 'Agent · 调用失败'
    progressMessage.content = error?.response?.data?.detail || error.message || '报告生成失败。'
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

async function upload(event) {
  const uploads = await uploadSelectedFiles(event.target.files)
  if (!uploads.length) return
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 文件已上传',
    content: `已接入 ${uploads.map(file => `**${file.filename}**`).join('、')}，后续研究、灾害分析和报告都会自动带上这些文件。`
  })
  event.target.value = ''
}

function openComposerFilePicker() {
  composerFileInput.value?.click()
}

async function attachFromComposer(event) {
  const uploads = await uploadSelectedFiles(event.target.files)
  pendingFiles.value = dedupeFiles([...pendingFiles.value, ...uploads])
  event.target.value = ''
  await scrollToBottom()
}

async function uploadSelectedFiles(fileList) {
  const files = Array.from(fileList || [])
  if (!files.length) return []
  uploading.value = true
  try {
    const uploads = []
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      const uploaded = await uploadFile(taskId.value, form)
      uploads.push(uploaded)
    }
    uploadedFiles.value = dedupeFiles([...uploads, ...uploadedFiles.value])
    return uploads
  } finally {
    uploading.value = false
  }
}

function removePendingFile(file) {
  const key = fileKey(file)
  pendingFiles.value = pendingFiles.value.filter(item => fileKey(item) !== key)
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
    .map(item => `${item.title}：${item.content}`)
    .join('\n\n')
}

function saveRecord() {
  localStorage.setItem(recordKey.value, conversationRecord.value)
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

function artifactUrl(artifact) {
  const normalized = String(artifact.path || '').replaceAll('\\', '/')
  const filename = normalized.split('/').pop()
  if (artifact.type === 'screenshot' && filename) {
    return `/artifacts/screenshots/${filename}`
  }
  if (artifact.type === 'report' && filename) {
    return `/artifacts/reports/${filename}`
  }
  if ((artifact.type === 'remote_sensing_overlay' || artifact.type === 'object_detection') && normalized.includes('data/remote_sensing/')) {
    return normalized.replace(/^.*data\/remote_sensing\//, '/artifacts/remote-sensing/')
  }
  return normalized
}

function artifactTitle(artifact) {
  const titles = {
    screenshot: '浏览器真实截图 · Playwright',
    remote_sensing_overlay: '灾害区域叠加图 · Image Analysis',
    object_detection: '灾害物体检测结果 · Detection Model',
    report: '生成报告'
  }
  return titles[artifact.type] || '处理结果'
}

function artifactMeta(artifact) {
  const metadata = artifact.metadata || {}
  if (artifact.type === 'object_detection') {
    const count = metadata.detections ?? 0
    const detector = metadata.detector || 'detector'
    return `检测框 ${count} 个 · ${detector}`
  }
  if (artifact.type === 'remote_sensing_overlay') {
    return metadata.class ? `识别类别：${metadata.class}` : ''
  }
  return ''
}

function isImageArtifact(artifact) {
  return ['screenshot', 'remote_sensing_overlay', 'object_detection'].includes(artifact.type)
}

function currentTurnFiles(attachments = []) {
  return attachments.length ? attachments : visibleUploadedFiles.value
}

function currentFilePayload(files = currentTurnFiles()) {
  return files.map(file => ({
    path: file.file_path,
    name: file.filename,
    type: file.file_type,
    mime_type: file.mime_type
  }))
}

function attachmentPrompt(files) {
  if (!files.length) return ''
  const hasImage = files.some(isUploadedImage)
  return hasImage ? `请分析我上传的 ${files.length} 个图片附件` : `请阅读我上传的 ${files.length} 个文件附件`
}

function withAttachmentSummary(text, files) {
  if (!files.length) return text
  const imageCount = files.filter(isUploadedImage).length
  const documentCount = files.length - imageCount
  const parts = []
  if (imageCount) parts.push(`${imageCount} 个图片`)
  if (documentCount) parts.push(`${documentCount} 个文件`)
  return `${text}\n\n已上传附件：${parts.join('、')}`
}

function filePreviewUrl(file) {
  if (file.preview_url) return file.preview_url
  const normalized = String(file.file_path || file.path || '').replaceAll('\\', '/')
  const marker = 'data/uploads/'
  if (normalized.includes(marker)) {
    return normalized.replace(/^.*data\/uploads\//, '/artifacts/uploads/')
  }
  return ''
}

function isUploadedImage(file) {
  const fileType = String(file.file_type || file.type || '').toUpperCase()
  const name = String(file.filename || file.name || '').toLowerCase()
  return fileType === 'IMAGE' || /\.(png|jpe?g|webp|bmp|tiff?|gif)$/.test(name)
}

function attachmentIcon(file) {
  if (isUploadedImage(file)) return 'IMG'
  const fileType = String(file.file_type || file.type || '').toUpperCase()
  if (fileType === 'PDF') return 'PDF'
  if (fileType === 'DOCX') return 'DOC'
  if (fileType === 'TXT') return 'TXT'
  return 'FILE'
}

function dedupeFiles(files) {
  const seen = new Set()
  return files.filter(file => {
    const key = fileKey(file)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function fileKey(file) {
  return String(file.doc_id || file.file_path || file.path || file.filename || file.name)
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
  if (state?.timer) {
    window.clearInterval(state.timer)
  }
  typingState.delete(messageItem.id)
  delete messageItem.streamingAnswerStarted
}

async function scrollToBottom() {
  await nextTick()
  if (messagePanel.value) {
    messagePanel.value.scrollTop = messagePanel.value.scrollHeight
  }
}

function pretty(value) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}
</script>

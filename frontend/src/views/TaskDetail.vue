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

            <div v-if="item.attachments?.length" class="message-attachments">
              <a
                v-for="file in item.attachments"
                :key="file.file_path || file.doc_id || file.filename"
                class="message-attachment"
                :href="fileUrl(file)"
                target="_blank"
                rel="noreferrer"
              >
                <img v-if="isUploadedImage(file) && fileUrl(file)" :src="fileUrl(file)" alt="附件预览" />
                <span v-else class="attachment-icon">{{ attachmentIcon(file) }}</span>
                <span>
                  <strong>{{ file.filename || file.name || '附件' }}</strong>
                  <small>{{ file.file_type || file.type || 'FILE' }}</small>
                </span>
              </a>
            </div>

            <div v-if="displayArtifacts(item.artifacts).length" class="artifact-panel">
              <div v-for="artifact in displayArtifacts(item.artifacts)" :key="artifact.path" class="artifact-card">
                <div class="artifact-title">{{ artifactTitle(artifact) }}</div>
                <a :href="artifactUrl(artifact)" target="_blank" rel="noreferrer">
                  <img v-if="isImageArtifact(artifact)" :src="artifactUrl(artifact)" alt="工具产物预览" />
                  <span v-else>{{ artifactName(artifact) }}</span>
                </a>
                <div v-if="artifactMeta(artifact)" class="artifact-meta">{{ artifactMeta(artifact) }}</div>
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

            <div v-if="item.needConfirm" class="confirm-box">
              <span>这些信息是否需要保留到正式任务记忆？</span>
              <button class="solid-button inline" @click="confirmDraftFromMessage(item)">确认保留</button>
            </div>

            <div v-if="item.needEmailConfirm" class="confirm-box">
              <span>确认发送这封邮件？</span>
              <button class="solid-button inline" @click="confirmEmailFromMessage(item)">确认发送</button>
              <button class="ghost-button inline" @click="item.needEmailConfirm = false">暂不发送</button>
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
          <div class="rail-title record-title-row">
            <span>本次对话记录</span>
            <button
              v-if="conversationRecord.trim()"
              class="ghost-button tiny"
              type="button"
              @click="recordPreviewMode = !recordPreviewMode"
            >
              {{ recordPreviewMode ? '编辑' : '预览' }}
            </button>
          </div>
          <div
            v-if="recordPreviewMode"
            class="record-editor record-preview-surface markdown-body"
            v-html="renderMarkdown(conversationRecord || '暂无保存内容')"
          />
          <textarea
            v-else
            v-model="conversationRecord"
            class="record-editor"
            placeholder="可编辑保存：关键信息、已确认事实、后续需要进入灾害分析/报告的信息。"
          />
          <div class="record-actions">
            <button class="ghost-button" @click="generateRecord">从对话生成</button>
            <button class="solid-button inline" :disabled="recordSaving" @click="saveRecord">
              {{ recordSaving ? '保存中' : '保存' }}
            </button>
          </div>
          <small v-if="recordSavedAt">{{ recordSavedAt }}</small>
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
              <button
                class="doc-delete-button"
                type="button"
                :disabled="deletingDocumentKey === documentKey(file)"
                @click.stop.prevent="removeDocument(file)"
              >
                {{ deletingDocumentKey === documentKey(file) ? '删除中' : '删除' }}
              </button>
            </div>
          </div>
        </section>
      </aside>

      <form class="simple-composer" @submit.prevent="runAgent">
        <div v-if="pendingFiles.length" class="composer-files">
          <div
            v-for="file in pendingFiles"
            :key="file.file_path || file.doc_id || file.filename"
            class="composer-file-chip"
          >
            <img v-if="isUploadedImage(file) && fileUrl(file)" :src="fileUrl(file)" alt="待发送附件" />
            <span v-else>{{ attachmentIcon(file) }}</span>
            <strong>{{ file.filename }}</strong>
            <button type="button" title="移除附件" @click="removePendingFile(file)">×</button>
          </div>
        </div>

        <div class="tool-picker">
          <input
            ref="composerFileInput"
            class="hidden-file-input"
            type="file"
            multiple
            :accept="selectedTool?.value === 'remote_sensing' ? 'image/*,.tif,.tiff' : undefined"
            @change="attachFromComposer"
          />
          <button
            type="button"
            class="attach-button"
            title="上传并随本轮发送"
            :disabled="loading || uploading"
            @click="openComposerFilePicker"
          >
            {{ uploading ? '…' : '＋' }}
          </button>
          <button type="button" class="attach-button" :class="{ active: selectedTool }" @click="toolMenuOpen = !toolMenuOpen">
            {{ selectedTool ? selectedTool.icon : '⌘' }}
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
        <button class="send-button" :disabled="loading || (!message.trim() && !pendingFiles.length)">{{ loading ? '…' : '→' }}</button>
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
  deleteTaskArtifact,
  deleteTaskDocument,
  deleteTaskDocumentByPath,
  getAgentSession,
  getChatHistory,
  getTaskDocuments,
  getTask,
  saveAgentRecord,
  streamAgentMessage,
  uploadFile,
  uploadTempFile
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
const pendingFiles = ref([])
const composerFileInput = ref(null)
const uploading = ref(false)
const messagePanel = ref(null)
const selectedTool = ref(null)
const toolMenuOpen = ref(false)
const conversationRecord = ref('')
const recordSavedAt = ref('')
const recordSaving = ref(false)
const recordPreviewMode = ref(false)
const deletingDocumentKey = ref('')
const removedRelatedFilePaths = ref(new Set())
const typingState = new Map()
let streamFallbackTimer = null

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
  removedRelatedFilePaths.value = new Set()
  selectedTool.value = null
  toolMenuOpen.value = false
  await refreshSession()
  await loadUploadedDocuments()
  await loadChatHistory()
  conversationRecord.value = session.value.conversation_record || localStorage.getItem(recordKey.value) || ''
  recordPreviewMode.value = false
  recordSavedAt.value = session.value.conversation_record
    ? `已从数据库恢复${formatRecordSavedAt(session.value.conversation_record_saved_at)}`
    : ''
}

async function loadUploadedDocuments() {
  const documents = await getTaskDocuments(taskId.value)
  uploadedFiles.value = documents
    .map(normalizeRelatedFile)
    .filter(file => !removedRelatedFilePaths.value.has(normalizeFilePath(file.file_path)))
}

async function loadChatHistory() {
  const history = await getChatHistory(taskId.value)
  const restored = []
  let pendingTrace = null

  for (const item of history) {
    if (item.role === 'tool') {
      const parsedTrace = parseTraceRecord(item.content)
      if (parsedTrace) {
        const attached = attachTraceToPreviousAgent(restored, parsedTrace)
        if (!attached) pendingTrace = parsedTrace
      }
      continue
    }

    if (item.role === 'assistant') {
      const agentMessage = {
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
      }
      restored.push(agentMessage)
      pendingTrace = null
      continue
    }

    restored.push({
      id: `db-${item.conv_id}`,
      role: 'user',
      title: '用户',
      content: stripAttachmentManifest(item.content),
      attachments: attachmentsFromMessageContent(item.content)
    })
  }

  messages.value = restored
  syncArtifactsToRelatedFiles(restored)
  await scrollToBottom()
}

function attachTraceToPreviousAgent(items, trace) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index]
    if (item.role === 'user') return false
    if (item.role !== 'agent') continue
    item.requestText = item.requestText || trace.requestText
    item.progress = trace.progress || []
    item.searchResults = trace.searchResults || []
    item.artifacts = trace.artifacts || []
    item.data = trace.data
    item.traceOpen = false
    return true
  }
  return false
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

function attachmentsFromMessageContent(content) {
  const manifest = attachmentManifestFromContent(content)
  if (manifest.length) return manifest.map(normalizeRelatedFile)
  return []
}

function attachmentManifestFromContent(content) {
  const match = String(content || '').match(/<!--\s*skyguard_attachments:(.*?)\s*-->/s)
  if (!match) return []
  try {
    const parsed = JSON.parse(match[1])
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function stripAttachmentManifest(content) {
  return String(content || '').replace(/\n*\s*<!--\s*skyguard_attachments:.*?-->\s*/s, '').trim()
}

function startStreamFallbackPolling(progressMessage) {
  stopStreamFallbackPolling()
  streamFallbackTimer = window.setInterval(async () => {
    if (!loading.value) return
    try {
      await refreshRunningMessageFromHistory(progressMessage)
    } catch {
      // 流式兜底不能影响主请求
    }
  }, 1200)
}

function stopStreamFallbackPolling() {
  if (streamFallbackTimer) window.clearInterval(streamFallbackTimer)
  streamFallbackTimer = null
}

async function refreshRunningMessageFromHistory(progressMessage) {
  const history = await getChatHistory(taskId.value)
  let latestTrace = null
  let latestAssistant = null

  for (let index = history.length - 1; index >= 0; index -= 1) {
    const item = history[index]
    if (item.role === 'tool') {
      const trace = parseTraceRecord(item.content)
      if (trace && (!progressMessage.requestText || trace.requestText === progressMessage.requestText)) {
        latestTrace = trace
        continue
      }
    }
    if (latestTrace && item.role === 'assistant') latestAssistant = item
    if (latestTrace && latestAssistant) break
    if (item.role === 'user' && latestTrace) break
  }

  if (latestTrace) {
    progressMessage.requestText = progressMessage.requestText || latestTrace.requestText
    progressMessage.progress = latestTrace.progress || progressMessage.progress
    progressMessage.searchResults = latestTrace.searchResults || progressMessage.searchResults
    progressMessage.artifacts = latestTrace.artifacts || progressMessage.artifacts
    progressMessage.data = latestTrace.data
    progressMessage.traceOpen = true
  }

  const assistantContent = String(latestAssistant?.content || '').trim()
  if (assistantContent && assistantContent !== '正在生成回复...' && assistantContent !== progressMessage.content) {
    progressMessage.title = 'Agent'
    progressMessage.content = assistantContent
  }

  await scrollToBottom()
}

async function runAgent() {
  const text = message.value.trim()
  if ((!text && !pendingFiles.value.length) || loading.value) return

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
  await scrollToBottom()

  message.value = ''
  pendingFiles.value = []
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
  startStreamFallbackPolling(progressMessage)

  try {
    const params = {
      conversation_record: conversationRecord.value,
      ...(currentTool ? { forced_tool: currentTool.value } : {})
    }
    await streamAgentMessage(taskId.value, { message: text, files: currentFilePayload(attachments, currentTool), params }, async event => {
      await handleStreamEvent(event, progressMessage)
    })
  } catch (error) {
    progressMessage.title = 'Agent · 调用失败'
    progressMessage.content = error?.response?.data?.detail || error.message || '调用失败，请检查后端服务。'
  } finally {
    stopStreamFallbackPolling()
    loading.value = false
    await scrollToBottom()
  }
}

async function handleStreamEvent(event, progressMessage) {
  if (event.type === 'report_format_required') {
    progressMessage.title = 'Agent · 等待选择'
    progressMessage.content = event.content
    progressMessage.needReportFormat = true
    progressMessage.progress.push('需要用户选择报告格式')
    progressMessage.traceOpen = true
    await scrollToBottom()
    return
  }

  if (event.type === 'thinking' || event.type === 'tool_call' || event.type === 'llm_call') {
    progressMessage.content = event.content
    progressMessage.progress.push(event.content)
    progressMessage.traceOpen = true
    await scrollToBottom()
    return
  }

  if (event.type === 'intent') {
    progressMessage.progress.push(event.content)
    progressMessage.traceOpen = true
    await scrollToBottom()
    return
  }

  if (event.type === 'answer_delta') {
    if (!progressMessage.streamingAnswerStarted) {
      progressMessage.title = 'Agent · LLM 生成中'
      progressMessage.content = ''
      progressMessage.streamingAnswerStarted = true
    }
    enqueueAnswerDelta(progressMessage, event.content || '')
    await nextTick()
    return
  }

  if (event.type === 'llm_fallback') {
    progressMessage.progress.push(event.content)
    progressMessage.traceOpen = true
    await scrollToBottom()
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
    if (event.need_user_confirm && event.data?.email_status === 'pending_confirmation' && event.data?.email_draft) {
      progressMessage.emailDraft = event.data.email_draft
      progressMessage.needEmailConfirm = true
      progressMessage.content = event.content || '请确认是否发送这封邮件。'
    }
    progressMessage.traceOpen = true
    await scrollToBottom()
    return
  }

  if (event.type === 'answer') {
    progressMessage.title = 'Agent'
    progressMessage.traceOpen = false
    finishTyping(progressMessage, event.content || progressMessage.content || '已完成。')
    await scrollToBottom()
    return
  }

  if (event.type === 'done') {
    session.value = event.session || session.value
    return
  }

  if (event.type === 'error') {
    progressMessage.title = 'Agent · 调用失败'
    progressMessage.content = event.content || event.error || '调用失败。'
    progressMessage.traceOpen = true
    await scrollToBottom()
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
    }, async event => {
      await handleStreamEvent(event, progressMessage)
    })
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
  const files = Array.from(event.target.files || [])
  if (!files.length) return
  const uploadedBatch = await uploadSelectedFiles(files)
  if (!uploadedBatch.length) return
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 文件已上传',
    content: `已接入 ${uploadedBatch.map(file => `**${file.filename}**`).join('、')}，后续研究、灾害分析和报告都会自动带上这些文件。`
  })
  event.target.value = ''
}

async function confirmEmailFromMessage(item) {
  if (!item.emailDraft || loading.value) return
  item.needEmailConfirm = false
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'user',
    title: '用户 · 邮件确认',
    content: '确认发送邮件'
  })

  loading.value = true
  const progressMessage = {
    id: crypto.randomUUID(),
    role: 'agent',
    title: 'Agent · 发送邮件中',
    content: '已确认，正在发送邮件...',
    requestText: item.requestText || '确认发送邮件',
    progress: ['用户已确认邮件草稿，准备调用邮件工具...'],
    traceOpen: true,
    searchResults: [],
    artifacts: []
  }
  messages.value.push(progressMessage)
  await scrollToBottom()

  try {
    await streamAgentMessage(taskId.value, {
      message: '确认发送邮件',
      files: [],
      params: {
        forced_tool: 'email',
        confirm_email: true,
        email_draft: item.emailDraft
      }
    }, async event => {
      await handleStreamEvent(event, progressMessage)
    })
  } catch (error) {
    progressMessage.title = 'Agent · 发送失败'
    progressMessage.content = error?.response?.data?.detail || error.message || '邮件发送失败。'
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

async function uploadSelectedFiles(files) {
  uploading.value = true
  const uploadedBatch = []
  try {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      const uploaded = await uploadFile(taskId.value, form)
      const normalized = normalizeRelatedFile(uploaded)
      uploadedFiles.value.push(normalized)
      uploadedBatch.push(normalized)
    }
    return uploadedBatch
  } finally {
    uploading.value = false
  }
}

function openComposerFilePicker() {
  composerFileInput.value?.click()
}

async function attachFromComposer(event) {
  const files = Array.from(event.target.files || [])
  if (!files.length) return
  const uploadedBatch = selectedTool.value?.value === 'remote_sensing'
    ? await uploadTemporaryImages(files)
    : await uploadSelectedFiles(files)
  pendingFiles.value.push(...uploadedBatch)
  event.target.value = ''
}

async function uploadTemporaryImages(files) {
  const invalidFiles = files.filter(file => !isImageLikeFile(file))
  if (invalidFiles.length) {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'agent',
      title: 'Agent · 文件未接入',
      content: `图像识别只支持图片文件，已忽略：${invalidFiles.map(file => file.name).join('、')}`
    })
  }

  const imageFiles = files.filter(isImageLikeFile)
  if (!imageFiles.length) return []

  uploading.value = true
  const uploadedBatch = []
  try {
    for (const file of imageFiles) {
      const form = new FormData()
      form.append('file', file)
      const normalized = normalizeRelatedFile(await uploadTempFile(taskId.value, form))
      uploadedBatch.push(normalized)
    }
    return uploadedBatch
  } finally {
    uploading.value = false
  }
}

function removePendingFile(file) {
  pendingFiles.value = pendingFiles.value.filter(item => item !== file && item.file_path !== file.file_path)
}

async function removeDocument(file) {
  const key = documentKey(file)
  if (!key || deletingDocumentKey.value) return

  deletingDocumentKey.value = key
  try {
    if (isReportArtifactFile(file)) {
      await deleteTaskArtifact(taskId.value, file.file_path)
      removeArtifactFromMessages(file.file_path)
    } else if (file.doc_id) {
      await deleteTaskDocument(taskId.value, file.doc_id)
    } else if (file.file_path) {
      await deleteTaskDocumentByPath(taskId.value, file.file_path)
    }
    if (file.file_path) removedRelatedFilePaths.value.add(normalizeFilePath(file.file_path))
    uploadedFiles.value = uploadedFiles.value.filter(item => {
      if (documentKey(item) === key) return false
      return normalizeFilePath(item.file_path) !== normalizeFilePath(file.file_path)
    })
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'agent',
      title: 'Agent · 文档已删除',
      content: `已删除 **${file.filename || '相关文档'}**。后台会基于剩余相关文档重新构建当前任务知识图谱。`
    })
    await loadUploadedDocuments()
  } catch (error) {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'agent',
      title: 'Agent · 删除失败',
      content: error?.response?.data?.detail || error?.message || '删除相关文档失败，请查看后端日志。'
    })
  } finally {
    deletingDocumentKey.value = ''
  }
}

function documentKey(file) {
  return String(file?.doc_id || normalizeFilePath(file?.file_path) || file?.filename || '')
}

function normalizeFilePath(path) {
  return String(path || '').replaceAll('\\', '/')
}

function normalizeRelatedFile(file) {
  return {
    ...file,
    file_path: normalizeFilePath(file?.file_path)
  }
}

function isReportArtifactFile(file) {
  const path = normalizeFilePath(file?.file_path)
  return file?.artifact?.type === 'report' || path.startsWith('data/reports/')
}

function removeArtifactFromMessages(path) {
  const refs = relatedArtifactPaths(path)
  for (const item of messages.value) {
    if (!Array.isArray(item.artifacts)) continue
    item.artifacts = item.artifacts.filter(artifact => !refs.has(normalizeFilePath(artifact.path)))
  }
}

function relatedArtifactPaths(path) {
  const normalized = normalizeFilePath(path)
  const refs = new Set([normalized])
  const dotIndex = normalized.lastIndexOf('.')
  if (dotIndex > -1) {
    const base = normalized.slice(0, dotIndex)
    refs.add(`${base}.json`)
    refs.add(`${base}.docx`)
    refs.add(`${base}.pdf`)
  }
  return refs
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
  recordPreviewMode.value = false
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
  recordPreviewMode.value = false
  recordSavedAt.value = '已生成，尚未保存到数据库'
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
  recordSaving.value = true
  try {
    localStorage.setItem(recordKey.value, conversationRecord.value)
    const result = await saveAgentRecord(taskId.value, conversationRecord.value)
    session.value.conversation_record = result.conversation_record ?? conversationRecord.value
    session.value.conversation_record_saved_at = result.saved_at
    recordSavedAt.value = `已保存到数据库${formatRecordSavedAt(result.saved_at)}`
  } finally {
    recordSaving.value = false
  }
}

function formatRecordSavedAt(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return ` · ${date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })}`
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
  if ((artifact.type === 'remote_sensing_overlay' || artifact.type === 'object_detection') && normalized.includes('data/remote_sensing/')) {
    return normalized.replace(/^.*data\/remote_sensing\//, '/artifacts/remote-sensing/')
  }
  return normalized
}

function artifactTitle(artifact) {
  const titles = {
    screenshot: '浏览器真实截图',
    report: '分析报告已生成',
    remote_sensing_overlay: '遥感叠加结果',
    object_detection: '图像识别结果'
  }
  return titles[artifact.type] || '工具产物'
}

function artifactMeta(artifact) {
  const metadata = artifact.metadata || {}
  if (artifact.type === 'object_detection') {
    const count = metadata.detections_count ?? metadata.count
    return count !== undefined ? `识别目标：${count} 个` : ''
  }
  if (artifact.type === 'remote_sensing_overlay') {
    return metadata.description || metadata.layer || ''
  }
  if (artifact.type === 'report') {
    return metadata.format ? `格式：${String(metadata.format).toUpperCase()}` : ''
  }
  return ''
}

function isImageArtifact(artifact) {
  return ['screenshot', 'remote_sensing_overlay', 'object_detection'].includes(artifact.type)
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

function isUploadedImage(file) {
  const value = `${file.file_type || file.type || ''} ${file.filename || file.name || ''}`.toLowerCase()
  return ['image', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff'].some(token => value.includes(token))
}

function isImageLikeFile(file) {
  const value = `${file.type || ''} ${file.name || file.filename || ''}`.toLowerCase()
  return ['image/', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'].some(token => value.includes(token))
}

function attachmentIcon(file) {
  const value = `${file.file_type || file.type || ''} ${file.filename || file.name || ''}`.toLowerCase()
  if (isUploadedImage(file)) return 'IMG'
  if (value.includes('pdf')) return 'PDF'
  if (value.includes('doc')) return 'DOC'
  if (value.includes('xls') || value.includes('csv')) return 'XLS'
  if (value.includes('tif') || value.includes('tiff')) return 'TIF'
  return 'FILE'
}

function syncArtifactsToRelatedFiles(items) {
  for (const item of items) addArtifactsToRelatedFiles(item.artifacts || [])
}

function addArtifactsToRelatedFiles(artifacts = []) {
  for (const artifact of artifacts) {
    if (artifact.type !== 'report') continue
    const path = normalizeFilePath(artifact.path)
    if (!path || uploadedFiles.value.some(file => normalizeFilePath(file.file_path) === path)) continue
    if (removedRelatedFilePaths.value.has(path)) continue
    uploadedFiles.value.push({
      filename: artifactName(artifact),
      file_type: (artifact.metadata?.format || path.split('.').pop() || 'REPORT').toUpperCase(),
      file_path: path,
      artifact
    })
  }
}

function currentFilePayload(currentTurnFiles = [], currentTool = null) {
  const files = currentTurnFiles
  return files.map(file => ({
    path: file.file_path,
    name: file.filename,
    type: file.file_type
  }))
}

function withAttachmentSummary(text, attachments = []) {
  if (!attachments.length) return text
  return `${text}\n\n已随本轮发送附件：${attachments.map(file => file.filename).join('、')}`
}

function attachmentPrompt(attachments = []) {
  return attachments.length
    ? `请分析本轮上传的附件：${attachments.map(file => file.filename).join('、')}`
    : ''
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

</script>


<template>
  <div class="login-page">
    <section class="login-hero">
      <div class="brand">
        <span class="brand-mark" />
        <span>
          <div class="brand-title">SkyGuard</div>
          <div class="brand-subtitle">Emergency Intelligence Platform</div>
        </span>
      </div>

      <div>
        <div class="eyebrow">Earth Observation · Graph RAG · Decision Support</div>
        <h1 class="page-title" style="font-size:58px; max-width:780px;">
          面向灾害分析人员的可信智能研判平台
        </h1>
        <p class="page-desc" style="max-width:680px; font-size:17px;">
          融合文档、网页证据、知识图谱与遥感影像，支撑应急管理场景下的任务化分析、风险评估和报告输出。
        </p>
      </div>

      <div class="grid-12">
        <div class="metric" style="grid-column:span 4;">
          <div class="metric-label">Evidence Trace</div>
          <div class="metric-value">100%</div>
        </div>
        <div class="metric" style="grid-column:span 4;">
          <div class="metric-label">Agent Tools</div>
          <div class="metric-value">10</div>
        </div>
        <div class="metric" style="grid-column:span 4;">
          <div class="metric-label">Decision Mode</div>
          <div class="metric-value">Human</div>
        </div>
      </div>
    </section>

    <section class="login-card panel panel-pad">
      <div class="row-between">
        <div>
          <div class="eyebrow">Secure Console</div>
          <h2 class="page-title" style="font-size:30px;">
            {{ mode === 'login' ? '控制台登录' : '创建分析员账号' }}
          </h2>
        </div>
        <span class="status-pill">{{ mode === 'login' ? 'SIGN IN' : 'REGISTER' }}</span>
      </div>
      <p class="page-desc">
        {{ mode === 'login' ? '进入任务管理、证据检索和智能灾害分析工作台。' : '注册后即可创建灾害任务并运行 Agent 工具链。' }}
      </p>

      <form class="stack" style="margin-top:26px;" @submit.prevent="submit">
        <label>
          <span class="field-label">用户名</span>
          <input v-model="form.username" class="field" autocomplete="username" required />
        </label>

        <label v-if="mode === 'register'">
          <span class="field-label">邮箱</span>
          <input v-model="form.email" class="field" type="email" autocomplete="email" required />
        </label>

        <label>
          <span class="field-label">密码</span>
          <input
            v-model="form.password"
            class="field"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>

        <button class="btn" :disabled="loading">
          {{ loading ? '处理中...' : mode === 'login' ? '进入平台' : '注册账号' }}
        </button>
        <button class="btn secondary" type="button" @click="toggleMode">
          {{ mode === 'login' ? '没有账号？创建一个' : '已有账号？返回登录' }}
        </button>

        <p v-if="error" class="muted" style="color:var(--danger);">{{ error }}</p>
        <p v-if="message" class="muted" style="color:var(--success);">{{ message }}</p>
      </form>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const error = ref('')
const message = ref('')
const mode = ref('login')
const form = reactive({ username: '', email: '', password: '' })

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
  message.value = ''
}

async function submit() {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    if (mode.value === 'register') {
      await userStore.register({
        username: form.username,
        email: form.email,
        password: form.password
      })
      message.value = '注册成功，请登录。'
      mode.value = 'login'
      return
    }

    await userStore.login({
      username: form.username,
      password: form.password
    })
    router.push('/dashboard')
  } catch (err) {
    error.value = err.response?.data?.detail || (mode.value === 'login' ? '登录失败，请检查账号信息。' : '注册失败，请检查信息是否已存在。')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="login-hero">
      <div class="login-brand-row">
        <span class="login-brand-mark">SG</span>
        <span>
          <strong>SkyGuard</strong>
          <small>灾害智能分析平台</small>
        </span>
      </div>

      <div class="login-hero-copy">
        <div class="eyebrow">Emergency Operations Console</div>
        <h1>把灾害线索、证据和研判收进同一个工作台。</h1>
        <p>面向应急分析人员的任务化工作空间，支持文档、网页证据、遥感影像与报告流程协同。</p>
      </div>

      <div class="login-command-stage" aria-hidden="true">
        <div class="command-board">
          <div class="board-topline">
            <span>Situation Board</span>
            <strong>LIVE</strong>
          </div>
          <div class="board-map">
            <span class="map-line horizontal one" />
            <span class="map-line horizontal two" />
            <span class="map-line vertical one" />
            <span class="map-line vertical two" />
            <span class="map-node main" />
            <span class="map-node left" />
            <span class="map-node right" />
          </div>
          <div class="board-metrics">
            <div>
              <small>Evidence</small>
              <strong>42</strong>
            </div>
            <div>
              <small>Reports</small>
              <strong>08</strong>
            </div>
            <div>
              <small>Tasks</small>
              <strong>16</strong>
            </div>
          </div>
        </div>
        <div class="command-slab slab-a" />
        <div class="command-slab slab-b" />
      </div>
    </section>

    <section class="login-panel-wrap">
      <div class="login-card">
        <div class="login-card-header">
          <div>
            <div class="eyebrow">Secure Access</div>
            <h2>{{ mode === 'login' ? '登录工作台' : '创建分析员账号' }}</h2>
          </div>
          <span class="status-pill">{{ mode === 'login' ? 'SIGN IN' : 'REGISTER' }}</span>
        </div>

        <p class="login-note">
          {{ mode === 'login' ? '继续进入任务、证据与灾害研判工作流。' : '创建账号后即可保存任务与对话记录。' }}
        </p>

        <form class="login-form" @submit.prevent="submit">
          <label class="login-field">
            <span>用户名</span>
            <input v-model="form.username" autocomplete="username" required />
          </label>

          <label v-if="mode === 'register'" class="login-field">
            <span>邮箱</span>
            <input v-model="form.email" type="email" autocomplete="email" required />
          </label>

          <label class="login-field">
            <span>密码</span>
            <input
              v-model="form.password"
              type="password"
              autocomplete="current-password"
              required
            />
          </label>

          <button class="login-submit" :disabled="loading">
            {{ loading ? '处理中...' : mode === 'login' ? '进入平台' : '注册账号' }}
          </button>

          <button class="login-switch" type="button" @click="toggleMode">
            {{ mode === 'login' ? '没有账号？创建一个' : '已有账号？返回登录' }}
          </button>

          <p v-if="error" class="login-feedback danger">{{ error }}</p>
          <p v-if="message" class="login-feedback success">{{ message }}</p>
        </form>
      </div>
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

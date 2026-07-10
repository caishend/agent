<template>
  <AppShell>
    <div class="account-page">
      <header class="account-hero">
        <div>
          <div class="workspace-kicker">Account Center</div>
          <h1>我的账号</h1>
          <p>查看当前登录身份，管理本地会话，并快速回到 SkyGuard 工作台。</p>
        </div>
        <button class="ghost-button" type="button" @click="refreshProfile">刷新账号信息</button>
      </header>

      <section class="account-layout">
        <article class="account-profile-card">
          <div class="account-profile-avatar">{{ userStore.initials }}</div>
          <div>
            <h2>{{ userStore.displayName }}</h2>
            <p>{{ userStore.userInfo?.email || '暂无邮箱信息' }}</p>
          </div>
          <dl class="account-facts">
            <div>
              <dt>账号 ID</dt>
              <dd>{{ userStore.userInfo?.user_id || '未同步' }}</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{{ formattedCreateTime }}</dd>
            </div>
            <div>
              <dt>会话状态</dt>
              <dd>{{ userStore.token ? '已登录' : '未登录' }}</dd>
            </div>
          </dl>
        </article>

        <aside class="account-actions-card">
          <div class="rail-title">账号操作</div>
          <RouterLink class="account-action-button" to="/dashboard">进入态势总览</RouterLink>
          <RouterLink class="account-action-button" to="/tasks">查看任务与会话</RouterLink>
          <button class="account-action-button danger" type="button" @click="logout">退出登录</button>
          <p v-if="message" class="account-message">{{ message }}</p>
        </aside>
      </section>
    </div>
  </AppShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const message = ref('')

const formattedCreateTime = computed(() => {
  const value = userStore.userInfo?.create_time
  if (!value) return '未同步'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
})

async function refreshProfile() {
  message.value = ''
  try {
    await userStore.fetchProfile()
    message.value = '账号信息已刷新。'
  } catch {
    message.value = '账号信息刷新失败，请重新登录。'
  }
}

function logout() {
  userStore.logout()
  router.push('/login')
}
</script>

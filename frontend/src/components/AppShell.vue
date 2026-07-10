<template>
  <div class="chat-shell">
    <aside class="chat-sidebar">
      <RouterLink class="side-brand" to="/tasks">
        <span class="side-logo">SG</span>
        <span>
          <strong>SkyGuard</strong>
          <small>灾害智能分析 Agent</small>
        </span>
      </RouterLink>

      <div class="side-actions">
        <RouterLink class="side-link" to="/tasks">任务与会话</RouterLink>
        <RouterLink class="side-link" to="/dashboard">态势总览</RouterLink>
        <RouterLink class="side-link" to="/account">我的账号</RouterLink>
      </div>

      <section class="conversation-list">
        <div class="side-section-title">最近会话</div>
        <div
          v-for="task in taskStore.tasks"
          :key="task.task_id"
          class="conversation-row"
          :class="{ active: String(route.params.id || '') === String(task.task_id) }"
        >
          <RouterLink class="conversation-item" :to="`/tasks/${task.task_id}`">
            <span class="conversation-name">{{ task.task_name }}</span>
            <small>{{ task.disaster_type || '自由问答' }} · {{ task.location || '未指定区域' }}</small>
          </RouterLink>
          <button class="conversation-delete" title="删除会话" @click="deleteTask(task)">×</button>
        </div>
        <div v-if="!taskStore.tasks.length" class="side-empty">暂无会话，请在任务与会话中创建任务。</div>
      </section>

      <footer class="account-footer">
        <button class="account-card" type="button" @click="accountMenuOpen = !accountMenuOpen">
          <span class="account-avatar">{{ userStore.initials }}</span>
          <span class="account-copy">
            <strong>{{ userStore.displayName }}</strong>
            <small>{{ userStore.userInfo?.email || '本地登录会话' }}</small>
          </span>
          <span class="account-caret">⌄</span>
        </button>

        <div v-if="accountMenuOpen" class="account-menu">
          <RouterLink class="account-menu-item" to="/account" @click="accountMenuOpen = false">账号中心</RouterLink>
          <RouterLink class="account-menu-item" to="/tasks" @click="accountMenuOpen = false">任务列表</RouterLink>
          <button class="account-menu-item danger" type="button" @click="logout">退出登录</button>
        </div>
      </footer>
    </aside>

    <main class="chat-main">
      <slot />
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useUserStore } from '../stores/user'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const userStore = useUserStore()
const accountMenuOpen = ref(false)

onMounted(async () => {
  taskStore.fetchTasks()
  if (userStore.token && !userStore.userInfo) {
    try {
      await userStore.fetchProfile()
    } catch {
      userStore.logout()
      router.push('/login')
    }
  }
})

watch(() => route.fullPath, () => {
  accountMenuOpen.value = false
})

async function deleteTask(task) {
  const confirmed = window.confirm(`确定删除会话「${task.task_name}」吗？`)
  if (!confirmed) return

  await taskStore.removeTask(task.task_id)
  if (String(route.params.id || '') === String(task.task_id)) {
    router.push('/tasks')
  }
}

function logout() {
  userStore.logout()
  router.push('/login')
}
</script>

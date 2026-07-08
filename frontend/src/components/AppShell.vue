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

      <footer class="side-footer">
        <div class="operator-dot" />
        <div>
          <strong>Agent 在线</strong>
          <small>自动识别意图，也可手动指定工具</small>
        </div>
      </footer>
    </aside>

    <main class="chat-main">
      <slot />
    </main>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()

onMounted(() => taskStore.fetchTasks())

async function deleteTask(task) {
  const confirmed = window.confirm(`确定删除会话「${task.task_name}」吗？`)
  if (!confirmed) return

  await taskStore.removeTask(task.task_id)
  if (String(route.params.id || '') === String(task.task_id)) {
    router.push('/tasks')
  }
}
</script>

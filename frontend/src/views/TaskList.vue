<template>
  <AppShell>
    <header class="topbar">
      <div>
        <div class="eyebrow">Mission Registry</div>
        <h1 class="page-title">任务与会话</h1>
        <p class="page-desc">统一创建任务、管理会话，并进入 Agent 辅助研判工作台。</p>
      </div>
      <button class="btn" @click="createVisible = !createVisible">
        {{ createVisible ? '收起任务建档' : '任务建档' }}
      </button>
    </header>

    <section class="task-registry-layout" :class="{ collapsed: !createVisible }">
      <form v-if="createVisible" class="panel panel-pad stack task-create-card" @submit.prevent="create">
        <div>
          <div class="eyebrow">New Mission</div>
          <h2 class="section-title">任务建档</h2>
        </div>
        <label>
          <span class="field-label">任务名称</span>
          <input v-model="form.task_name" class="field" required placeholder="例如：成都暴雨洪涝风险研判" />
        </label>
        <label>
          <span class="field-label">灾害类型</span>
          <input v-model="form.disaster_type" class="field" placeholder="暴雨洪涝 / 台风 / 地震..." />
        </label>
        <label>
          <span class="field-label">影响区域</span>
          <input v-model="form.location" class="field" placeholder="成都" />
        </label>
        <button class="btn">创建并进入</button>
      </form>

      <div class="panel panel-pad task-queue-card">
        <div class="row-between">
          <div>
            <div class="eyebrow">Task Queue</div>
            <h2 class="section-title">任务队列</h2>
          </div>
          <button class="btn secondary" @click="taskStore.fetchTasks()">刷新</button>
        </div>
        <div class="divider" />

        <div class="table-list task-queue-list">
          <RouterLink
            v-for="task in taskStore.tasks"
            :key="task.task_id"
            class="task-row"
            :to="`/tasks/${task.task_id}`"
          >
            <div>
              <div class="row task-row-meta">
                <span class="status-pill" :class="{ ok: task.status === 'DONE', warn: task.status === 'RUNNING' }">
                  {{ task.status || 'IDLE' }}
                </span>
                <span class="muted">#{{ task.task_id }}</span>
              </div>
              <h3>{{ task.task_name }}</h3>
              <div class="muted">{{ task.disaster_type || '未指定灾种' }} · {{ task.location || '未指定区域' }}</div>
            </div>
            <div class="muted">进入研判 →</div>
          </RouterLink>

          <div v-if="!taskStore.tasks.length" class="event-card muted">
            暂无任务。建议先创建一个“区域 + 灾种 + 时间”的分析任务。
          </div>
        </div>
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { useTaskStore } from '../stores/task'

const router = useRouter()
const taskStore = useTaskStore()
const createVisible = ref(true)
const form = reactive({ task_name: '', disaster_type: '', location: '' })

onMounted(() => taskStore.fetchTasks())

async function create() {
  const task = await taskStore.addTask({ ...form })
  form.task_name = ''
  form.disaster_type = ''
  form.location = ''
  router.push(`/tasks/${task.task_id}`)
}
</script>

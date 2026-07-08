<template>
  <AppShell>
    <header class="topbar">
      <div>
        <div class="eyebrow">Operational Overview</div>
        <h1 class="page-title">灾害智能研判总览</h1>
        <p class="page-desc">按任务组织证据、工具调用和风险结论，避免普通聊天式信息散落。</p>
      </div>
      <RouterLink class="btn" to="/tasks">进入任务工作台</RouterLink>
    </header>

    <section class="grid-12">
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">任务总数</div>
        <div class="metric-value">{{ tasks.length }}</div>
      </div>
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">运行中</div>
        <div class="metric-value">{{ runningCount }}</div>
      </div>
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">已完成</div>
        <div class="metric-value">{{ doneCount }}</div>
      </div>
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">工具链</div>
        <div class="metric-value">READY</div>
      </div>

      <div class="panel map-surface" style="grid-column:span 8;">
        <div class="map-node" style="left:60%; top:46%;" />
        <div class="map-node" style="left:36%; top:58%; background:var(--danger);" />
        <div class="map-node" style="left:70%; top:30%; background:var(--accent);" />
        <div class="map-label" style="left:62%; top:39%;">华东降雨监测 · ACTIVE</div>
        <div class="map-label" style="left:28%; top:62%;">西南地质灾害 · WATCH</div>
        <div class="map-label" style="right:26px; bottom:24px;">模拟空间态势底图</div>
      </div>

      <div class="panel panel-pad" style="grid-column:span 4;">
        <div class="row-between">
          <div>
            <div class="eyebrow">Recent Tasks</div>
            <h2 style="margin:6px 0 0;">近期任务</h2>
          </div>
          <span class="status-pill">LIVE</span>
        </div>
        <div class="divider" />
        <div class="event-list">
          <RouterLink
            v-for="task in tasks.slice(0, 6)"
            :key="task.task_id"
            class="event-card"
            :to="`/tasks/${task.task_id}`"
          >
            <div class="event-type">{{ task.status || 'IDLE' }}</div>
            <div class="event-content">{{ task.task_name }}</div>
            <div class="muted">{{ task.disaster_type || '未指定灾种' }} · {{ task.location || '未指定区域' }}</div>
          </RouterLink>
          <div v-if="!tasks.length" class="muted">暂无任务，进入任务工作台创建第一个分析任务。</div>
        </div>
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import AppShell from '../components/AppShell.vue'
import { useTaskStore } from '../stores/task'

const taskStore = useTaskStore()
const tasks = computed(() => taskStore.tasks)
const runningCount = computed(() => tasks.value.filter(task => task.status === 'RUNNING').length)
const doneCount = computed(() => tasks.value.filter(task => task.status === 'DONE').length)

onMounted(() => taskStore.fetchTasks())
</script>

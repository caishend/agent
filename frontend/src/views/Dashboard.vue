<template>
  <AppShell>
    <header class="topbar overview-topbar">
      <div>
        <div class="eyebrow">Operational Overview</div>
        <h1 class="page-title">全国灾害态势总览</h1>
      </div>
      <div class="overview-actions">
        <button class="btn secondary" @click="reloadAll">刷新态势</button>
        <RouterLink class="btn" to="/tasks">进入任务工作台</RouterLink>
      </div>
    </header>

    <section class="grid-12">
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">灾害事件</div>
        <div class="metric-value">{{ metrics.event_count || 0 }}</div>
      </div>
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">高风险事件</div>
        <div class="metric-value">{{ metrics.high_risk_count || 0 }}</div>
      </div>
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">涉及省份</div>
        <div class="metric-value">{{ metrics.province_count || 0 }}</div>
      </div>
      <div class="metric" style="grid-column:span 3;">
        <div class="metric-label">估算影响人口</div>
        <div class="metric-value">{{ formatPopulation(metrics.estimated_affected_population || 0) }}</div>
      </div>

      <div class="panel overview-panel" style="grid-column:span 8;">
        <div class="panel-heading">
          <div>
            <div class="eyebrow">China Situation Map</div>
            <h2>灾害点位与人口暴露</h2>
          </div>
          <span class="status-pill">可拖动 / 滚轮缩放</span>
        </div>
        <div ref="mapChartRef" class="overview-map-chart" />
        <div class="map-note">
          底图来自本地中国省界 GeoJSON；人口密度点来自数据库缓存采样；灾害点、风险等级、影响人口来自数据库事件表。
        </div>
      </div>

      <div class="panel overview-panel" style="grid-column:span 4;">
        <div class="panel-heading">
          <div>
            <div class="eyebrow">GraphRAG Context</div>
            <h2>{{ graphTitle }}</h2>
          </div>
          <span class="status-pill">{{ graphStats }}</span>
        </div>
        <div ref="graphChartRef" class="overview-graph-chart" />
        <p class="map-note">
          在下方“灾害事件与影响人口”表格中点击某个任务，右侧图谱会切换到该任务在数据库中的 GraphRAG 实体与关系。
        </p>
      </div>

      <div class="panel overview-panel" style="grid-column:span 12;">
        <div class="panel-heading">
          <div>
            <div class="eyebrow">Disaster Registry</div>
            <h2>灾害事件与影响人口</h2>
          </div>
          <span class="status-pill">{{ selectedEvent ? `当前：${displayEventName(selectedEvent)}` : '点击行切换图谱' }}</span>
        </div>
        <div class="overview-table-wrap">
          <table class="overview-table">
            <thead>
              <tr>
                <th>事件</th>
                <th>地区</th>
                <th>类型</th>
                <th>风险</th>
                <th>人口密度</th>
                <th>影响人口</th>
                <th>报告</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="event in events"
                :key="event.event_id"
                :class="{ active: isSelectedEvent(event) }"
                @click="selectEvent(event)"
              >
                <td class="event-main-cell">
                  <RouterLink v-if="event.task_id" :to="`/tasks/${event.task_id}`" @click.stop>
                    {{ displayEventName(event) }}
                  </RouterLink>
                  <span v-else>{{ displayEventName(event) }}</span>
                  <small>{{ displayEventSummary(event) || '暂无摘要，完成灾害分析后会自动同步。' }}</small>
                </td>
                <td>{{ event.city || event.province || event.location_name || '未定位' }}</td>
                <td>{{ event.disaster_type || '未知' }}</td>
                <td><span class="risk-badge" :class="riskClass(event.risk_level)">{{ displayRiskLevel(event.risk_level) }}</span></td>
                <td class="numeric-cell">{{ event.population_density ? `${Math.round(event.population_density)} 人/km²` : '待匹配' }}</td>
                <td class="numeric-cell highlight">{{ formatPopulation(event.estimated_affected_population || 0) }}</td>
                <td><span class="report-chip" :class="{ ok: event.report_path }">{{ event.report_path ? '已生成' : '未生成' }}</span></td>
              </tr>
              <tr v-if="!events.length">
                <td colspan="7" class="empty-cell">暂无灾害事件。创建任务或完成灾害分析后，这里会从数据库自动出现。</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="metric-explain">
          <div>
            <strong>风险</strong>
            <span>来自灾害分析工具：未运行风险评估时显示“未评估”，完成后写入低/中/高/极高风险。</span>
          </div>
          <div>
            <strong>人口密度</strong>
            <span>优先读取数据库人口缓存，按灾害点附近栅格估算平均密度；缓存缺失时回退本地 GeoTIFF。</span>
          </div>
          <div>
            <strong>影响人口</strong>
            <span>按影响半径内暴露人口 × 风险等级权重估算；完成灾害分析后数值会随事件位置、半径和风险等级更新。</span>
          </div>
        </div>
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import * as echarts from 'echarts'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { getChinaGeoJson, getOverviewSummary, getPopulationHeatmap } from '../api/task'

const overview = ref({
  metrics: {},
  events: [],
  population_density: [],
  population_dataset: {},
  knowledge_graph: { categories: [], nodes: [], links: [] },
})
const populationHeatmap = ref({ points: [], dataset: {} })
const selectedEventTaskId = ref('')
const selectedEventId = ref('')
const chinaGeoJson = ref(null)
const mapChartRef = ref(null)
const graphChartRef = ref(null)
let mapChart = null
let graphChart = null

const metrics = computed(() => overview.value.metrics || {})
const events = computed(() => overview.value.events || [])
const selectedEvent = computed(() => {
  return events.value.find(event => {
    if (selectedEventTaskId.value && String(event.task_id) === selectedEventTaskId.value) return true
    return selectedEventId.value && String(event.event_id) === selectedEventId.value
  })
})
const graphTitle = computed(() => selectedEvent.value ? `任务图谱：${displayEventName(selectedEvent.value)}` : '请选择一个灾害任务')
const graphStats = computed(() => {
  const graph = overview.value.knowledge_graph || { nodes: [], links: [] }
  return `${graph.nodes?.length || 0} 节点 / ${graph.links?.length || 0} 关系`
})

onMounted(async () => {
  await Promise.all([loadGeoData(), reloadAll()])
  window.addEventListener('resize', resizeCharts)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeCharts)
  mapChart?.dispose()
  graphChart?.dispose()
})

watch([overview, populationHeatmap, chinaGeoJson], () => nextTick(renderCharts), { deep: true })

async function loadGeoData() {
  const [geoJson, heatmap] = await Promise.all([getChinaGeoJson(), getPopulationHeatmap()])
  chinaGeoJson.value = geoJson
  populationHeatmap.value = heatmap || { points: [], dataset: {} }
}

async function reloadAll() {
  await loadOverview()
  if (!selectedEvent.value && events.value.length) {
    await selectEvent(events.value[0])
  }
}

async function loadOverview(graphTaskId = selectedEventTaskId.value) {
  const params = graphTaskId
    ? { graph_task_id: graphTaskId, graph_limit: 45 }
    : { graph_task_id: -1, graph_limit: 45 }
  overview.value = await getOverviewSummary(params)
  await nextTick()
  renderCharts()
}

async function selectEvent(event) {
  selectedEventTaskId.value = event.task_id ? String(event.task_id) : ''
  selectedEventId.value = String(event.event_id)
  await loadOverview(selectedEventTaskId.value)
}

function isSelectedEvent(event) {
  if (selectedEventTaskId.value && event.task_id) return String(event.task_id) === selectedEventTaskId.value
  return String(event.event_id) === selectedEventId.value
}

function renderCharts() {
  renderMapChart()
  renderGraphChart()
}

function renderMapChart() {
  if (!mapChartRef.value || !chinaGeoJson.value?.features?.length) return
  mapChart ||= echarts.init(mapChartRef.value)
  echarts.registerMap('china-local', chinaGeoJson.value)

  const heatmapData = populationHeatmap.value.points || []
  const populationLayerData = heatmapData
    .map(item => {
      const density = Number(item[2] || 0)
      return [Number(item[0]), Number(item[1]), Math.log10(density + 1), density]
    })
    .filter(item => Number.isFinite(item[0]) && Number.isFinite(item[1]) && item[3] > 0)
  const maxDensity = populationLayerData.reduce((max, item) => Math.max(max, Number(item[2] || 0)), 0)
  const eventData = events.value
    .filter(item => item.longitude && item.latitude)
    .map(item => ({
      name: displayEventName(item),
      value: [
        Number(item.longitude),
        Number(item.latitude),
        item.estimated_affected_population || 0,
        item.severity_score || 0.4,
        item.population_density || 0,
      ],
      itemStyle: { color: riskColor(item.risk_level) },
      event: item,
    }))

  mapChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      formatter(params) {
        if (params.seriesName === '灾害事件') {
          const event = params.data.event
          return [
            '<strong>' + displayEventName(event) + '</strong>',
            (event.city || event.province || '未定位') + ' · ' + (event.disaster_type || '未知'),
            '风险：' + displayRiskLevel(event.risk_level),
            '人口密度：' + (event.population_density ? Math.round(event.population_density) : '待估') + ' 人/km²',
            '影响人口：' + formatPopulation(event.estimated_affected_population || 0),
          ].join('<br/>')
        }
        if (params.seriesType === 'heatmap' || params.seriesName === '人口密度采样') {
          const density = params.value?.[3] ?? params.value?.[2] ?? 0
          return '人口密度采样<br/>' + Math.round(density) + ' 人/km²'
        }
        return params.name || ''
      },
    },
    visualMap: populationLayerData.length
      ? {
          min: 0,
          max: Math.max(1, maxDensity),
          seriesIndex: [0, 1],
          show: false,
          inRange: { color: ['#dce6e1', '#aacdb8', '#73a982', '#d29147', '#ad3528'] },
        }
      : undefined,
    geo: {
      map: 'china-local',
      roam: true,
      zoom: 1,
      layoutCenter: ['51%', '52%'],
      layoutSize: '92%',
      scaleLimit: { min: 0.75, max: 12 },
      label: { show: false },
      itemStyle: {
        areaColor: '#f3f7f5',
        borderColor: 'rgba(22,63,58,0.35)',
        borderWidth: 0.7,
      },
      emphasis: {
        label: { show: false },
        itemStyle: { areaColor: '#dfe9e5' },
      },
    },
    series: [
      {
        name: '人口密度底色',
        type: 'heatmap',
        coordinateSystem: 'geo',
        data: populationLayerData,
        pointSize: 9,
        blurSize: 12,
        itemStyle: {
          opacity: 0.28,
        },
        progressive: 800,
        zlevel: 1,
        silent: true,
      },
      {
        name: '人口密度采样',
        type: 'scatter',
        coordinateSystem: 'geo',
        data: populationLayerData,
        symbol: 'circle',
        symbolSize: 2.4,
        itemStyle: {
          opacity: 0.62,
        },
        progressive: 800,
        zlevel: 2,
      },
      {
        name: '灾害事件',
        type: 'effectScatter',
        coordinateSystem: 'geo',
        data: eventData,
        symbolSize: data => Math.max(15, Math.min(36, 14 + data[3] * 18)),
        rippleEffect: { brushType: 'stroke', scale: 3.5 },
        label: {
          show: true,
          formatter: '{b}',
          position: 'right',
          color: '#163f3a',
          fontWeight: 700,
        },
        zlevel: 3,
      },
    ],
  }, true)
}

function renderGraphChart() {
  if (!graphChartRef.value) return
  graphChart ||= echarts.init(graphChartRef.value)
  const graph = overview.value.knowledge_graph || { nodes: [], links: [], categories: [] }
  const displayNodes = (graph.nodes || []).slice(0, 45)
  const nodeIds = new Set(displayNodes.map(node => node.id))
  const displayLinks = (graph.links || []).filter(link => nodeIds.has(link.source) && nodeIds.has(link.target)).slice(0, 80)

  graphChart.setOption({
    tooltip: {
      formatter(params) {
        if (params.dataType === 'edge') return params.data.label || params.data.value || ''
        return params.data.description || params.data.name || ''
      },
    },
    color: ['#174a43', '#9f7a28', '#5d7f78', '#b85f4d', '#718879', '#444'],
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        data: displayNodes.map(node => ({
          ...node,
          symbolSize: node.category === '灾害事件' ? 48 : node.category === '人口影响' ? 38 : 30,
        })),
        links: displayLinks.map(link => ({ ...link, value: link.label || link.value })),
        categories: (graph.categories || []).map(name => ({ name })),
        label: { show: true, color: '#1c2724', fontSize: 11 },
        edgeLabel: { show: true, formatter: '{c}', color: '#7a8581', fontSize: 10 },
        lineStyle: { color: 'source', curveness: 0.18, opacity: 0.45 },
        force: { repulsion: 120, edgeLength: 72 },
      },
    ],
  }, true)
}

function resizeCharts() {
  mapChart?.resize()
  graphChart?.resize()
}

function riskColor(level) {
  if (level === '极高风险') return '#9f2d22'
  if (level === '高风险') return '#c45f45'
  if (level === '中风险') return '#af8e3d'
  if (level === '低风险') return '#3f7f6c'
  return '#6d7f7a'
}

function riskClass(level) {
  if (level === '极高风险') return 'critical'
  if (level === '高风险') return 'high'
  if (level === '中风险') return 'medium'
  if (level === '低风险') return 'low'
  return 'pending'
}

function displayRiskLevel(level) {
  if (!level || level === '待评估') return '未评估'
  return level
}

function displayEventName(event) {
  return cleanRegistryText(event?.event_name) || '未命名灾害事件'
}

function displayEventSummary(event) {
  return cleanRegistryText(event?.summary)
}

function cleanRegistryText(value) {
  let text = String(value || '').trim()
  const replacements = {
    待确认时间: '',
    待确认区域: '',
    待确认灾害类型: '灾害',
    待确认灾害: '灾害',
    待补充时间: '',
    待补充区域: '',
    待补充灾害类型: '灾害',
    未识别时间: '',
    未识别区域: '',
    未识别灾害类型: '灾害',
    分析任务草稿: '分析任务',
    任务草稿: '任务',
    灾害态势库: '灾害事件登记表',
    文害态势库: '灾害事件登记表',
    已进入: '已同步到',
    已确认灾害类型: '识别灾害类型',
    已确认影响区域: '识别影响区域',
    已确认时间范围: '识别时间范围',
    待评估: '未评估',
    待定位区域: '未定位'
  }
  Object.entries(replacements).forEach(([from, to]) => {
    text = text.replaceAll(from, to)
  })
  return text.replace(/\s{2,}/g, ' ').replace(/[，,；;。]+$/g, '').trim()
}

function formatPopulation(value) {
  const number = Number(value || 0)
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`
  return number.toLocaleString('zh-CN')
}
</script>

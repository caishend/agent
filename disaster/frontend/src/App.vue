<script setup>
import { computed, ref } from "vue";
import { checkHealth, fetchHistory, predictImage, predictVideoStream, resultUrl } from "./api.js";

const navItems = [
  { key: "dashboard", label: "项目概览", desc: "功能概览与检测流程" },
  { key: "detect", label: "智能检测", desc: "上传图片或视频进行识别" },
  { key: "analysis", label: "AI解析", desc: "生成识别结果说明" },
];

const activePage = ref("dashboard");
const activeTab = ref("image");
const isAuthenticated = ref(
  sessionStorage.getItem("model_pipeline_logged_in") === "1"
);
const loginForm = ref({ username: "", password: "" });
const loginError = ref("");

const health = ref(null);
const imgInput = ref(null);
const batchInput = ref(null);
const videoInput = ref(null);

const imageFile = ref(null);
const imagePreview = ref("");
const imageLoading = ref(false);
const imageError = ref("");
const imageResult = ref(null);

const batchItems = ref([]);
const batchLoading = ref(false);
const batchError = ref("");

const videoFile = ref(null);
const videoLoading = ref(false);
const videoError = ref("");
const videoResult = ref(null);
const videoStreamFrame = ref("");
const videoProgress = ref({ current: 0, total: 0 });
const videoLive = ref(null);

const gateThreshold = ref(0.5);
const historyItems = ref([]);
const historyLoading = ref(false);
const previewDialog = ref(false);
const previewItem = ref(null);

const analysisTarget = ref("image");
const analysisLoading = ref(false);
const analysisError = ref("");
const analysisText = ref("");

const moduleNameMap = {
  group1_od: "目标定位模块",
  group2_seg1: "区域分析模块 A",
  group3_seg2: "区域分析模块 B",
};

const gateList = computed(() => {
  const gate = imageResult.value?.gate;
  if (!gate?.probabilities) return [];
  return Object.keys(gate.probabilities).map((key) => ({
    key,
    label: moduleNameMap[key] || key,
    prob: gate.probabilities[key],
    active: Boolean(gate.decisions?.[key]),
  }));
});

const resultImageUrl = computed(() => resultUrl(imageResult.value?.image_path));
const resultVideoUrl = computed(() => resultUrl(videoResult.value?.video_path));
const detections = computed(() => imageResult.value?.detections || []);
const segmentations = computed(() => imageResult.value?.segmentations || []);
const activatedGateCount = computed(
  () => gateList.value.filter((item) => item.active).length
);

const topDetection = computed(() => {
  if (!detections.value.length) return null;
  return [...detections.value].sort((a, b) => b.confidence - a.confidence)[0];
});

const healthText = computed(() => {
  if (health.value === "ok") return "服务已连接";
  if (health.value === "error") return "服务未连接";
  return "检测中";
});

const dashboardCards = computed(() => [
  {
    label: "服务状态",
    value:
      health.value === "ok"
        ? "在线"
        : health.value === "error"
        ? "离线"
        : "检测中",
    tone:
      health.value === "ok"
        ? "good"
        : health.value === "error"
        ? "bad"
        : "wait",
  },
  {
    label: "图像分析",
    value: imageResult.value ? "已完成" : "未开始",
    tone: imageResult.value ? "good" : "wait",
  },
  {
    label: "检测目标",
    value: detections.value.length,
    tone: detections.value.length ? "good" : "wait",
  },
  {
    label: "分割区域",
    value: segmentations.value.length,
    tone: segmentations.value.length ? "good" : "wait",
  },
]);

const imageSummary = computed(() => [
  {
    label: "启用模块",
    value: `${activatedGateCount.value}/${gateList.value.length || 3}`,
  },
  { label: "目标数量", value: detections.value.length },
  { label: "分割区域", value: segmentations.value.length },
]);

const batchSummary = computed(() => {
  const total = batchItems.value.length;
  const done = batchItems.value.filter((item) => item.status === "done").length;
  const failed = batchItems.value.filter(
    (item) => item.status === "error"
  ).length;
  return { total, done, failed };
});

const canAnalyze = computed(() => {
  if (analysisTarget.value === "image") return Boolean(imageResult.value);
  if (analysisTarget.value === "batch") {
    return batchItems.value.some(
      (item) => item.status === "done" && item.result
    );
  }
  return Boolean(videoResult.value);
});

async function check() {
  try {
    const response = await checkHealth();
    health.value = response.status === "ok" ? "ok" : "error";
  } catch {
    health.value = "error";
  }
}

check();
loadHistory();

async function loadHistory() {
  historyLoading.value = true;
  try {
    const data = await fetchHistory();
    historyItems.value = data.items || [];
  } catch {
    historyItems.value = [];
  } finally {
    historyLoading.value = false;
  }
}

function login() {
  loginError.value = "";
  if (
    loginForm.value.username === "123" &&
    loginForm.value.password === "123"
  ) {
    isAuthenticated.value = true;
    sessionStorage.setItem("model_pipeline_logged_in", "1");
    loginForm.value.password = "";
    return;
  }
  loginError.value = "用户名或密码错误";
}

function logout() {
  isAuthenticated.value = false;
  sessionStorage.removeItem("model_pipeline_logged_in");
  loginForm.value = { username: "", password: "" };
  loginError.value = "";
}

function openPage(page) {
  activePage.value = page;
}

function openPreview(item) {
  previewItem.value = item;
  previewDialog.value = true;
}

function formatPercent(value, digits = 1) {
  if (typeof value !== "number") return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

function onImageDrop(event) {
  imageError.value = "";
  imageResult.value = null;
  analysisText.value = "";
  const file = event.dataTransfer?.files?.[0] || event.target?.files?.[0];
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    imageError.value = "请选择图片文件";
    return;
  }
  imageFile.value = file;
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value);
  imagePreview.value = URL.createObjectURL(file);
}

async function runImage() {
  if (!imageFile.value) return;
  imageLoading.value = true;
  imageError.value = "";
  imageResult.value = null;
  analysisText.value = "";
  try {
    imageResult.value = await predictImage(imageFile.value, gateThreshold.value);
    analysisTarget.value = "image";
    loadHistory();
  } catch (error) {
    imageError.value = error.message;
  } finally {
    imageLoading.value = false;
  }
}

function onBatchPick(event) {
  batchError.value = "";
  analysisText.value = "";
  const files = Array.from(
    event.dataTransfer?.files || event.target?.files || []
  );
  const images = files.filter((file) => file.type.startsWith("image/"));
  if (!images.length) {
    batchError.value = "请选择图片文件";
    return;
  }
  batchItems.value.forEach((item) => {
    if (item.preview) URL.revokeObjectURL(item.preview);
  });
  batchItems.value = images.map((file, index) => ({
    id: `${Date.now()}-${index}-${file.name}`,
    file,
    preview: URL.createObjectURL(file),
    status: "pending",
    result: null,
    error: "",
  }));
}

async function runBatchImages() {
  if (!batchItems.value.length || batchLoading.value) return;
  batchLoading.value = true;
  batchError.value = "";
  analysisText.value = "";
  for (const item of batchItems.value) {
    item.status = "running";
    item.error = "";
    item.result = null;
    try {
      item.result = await predictImage(item.file, gateThreshold.value);
      item.status = "done";
    } catch (error) {
      item.status = "error";
      item.error = error.message;
    }
  }
  batchLoading.value = false;
  if (batchItems.value.some((item) => item.status === "done" && item.result)) {
    analysisTarget.value = "batch";
  }
  loadHistory();
}

function onVideoPick(event) {
  videoError.value = "";
  videoResult.value = null;
  videoStreamFrame.value = "";
  videoProgress.value = { current: 0, total: 0 };
  videoLive.value = null;
  analysisText.value = "";
  const file = event.target?.files?.[0];
  if (!file) return;
  if (!file.type.startsWith("video/")) {
    videoError.value = "请选择视频文件";
    return;
  }
  videoFile.value = file;
}

async function runVideo() {
  if (!videoFile.value) return;
  videoLoading.value = true;
  videoError.value = "";
  videoResult.value = null;
  videoStreamFrame.value = "";
  videoProgress.value = { current: 0, total: 0 };
  videoLive.value = null;
  analysisText.value = "";
  try {
    await predictVideoStream(videoFile.value, gateThreshold.value, (event) => {
      if (event.type === "frame") {
        videoStreamFrame.value = event.image;
        videoProgress.value = {
          current: event.frame_idx,
          total: event.total,
        };
        videoLive.value = {
          detections: event.detections || [],
          segmentations: event.segmentations || [],
        };
      } else if (event.type === "done") {
        videoResult.value = {
          video_path: event.video_path,
          frame_count: event.frame_count,
        };
        analysisTarget.value = "video";
        loadHistory();
      } else if (event.type === "error") {
        videoError.value = event.message || "视频推理失败";
      }
    });
  } catch (error) {
    videoError.value = error.message;
  } finally {
    videoLoading.value = false;
  }
}

function buildAnalysisPayload() {
  if (analysisTarget.value === "video") {
    return {
      task: "video_detection_result",
      frame_count: videoResult.value?.frame_count,
      output_video_path: videoResult.value?.video_path,
    };
  }
  if (analysisTarget.value === "batch") {
    const items = batchItems.value
      .filter((item) => item.status === "done" && item.result)
      .map((item) => ({
        file_name: item.file.name,
        gate: item.result.gate,
        detections: (item.result.detections || []).map((detection) => ({
          class_name: detection.class_name,
          confidence: detection.confidence,
          box_xyxy: detection.box_xyxy,
        })),
        segmentations: (item.result.segmentations || []).map(
          (segmentation) => ({
            class_name: segmentation.class_name,
            pixel_count: segmentation.pixel_count,
            pixel_ratio: segmentation.pixel_ratio,
          })
        ),
        output_image_path: item.result.image_path,
      }));

    return {
      task: "batch_image_detection_result",
      image_count: items.length,
      failed_count: batchItems.value.filter((item) => item.status === "error")
        .length,
      items,
    };
  }
  return {
    task: "image_detection_result",
    gate: imageResult.value?.gate,
    detections: detections.value.map((item) => ({
      class_name: item.class_name,
      confidence: item.confidence,
      box_xyxy: item.box_xyxy,
    })),
    segmentations: segmentations.value.map((item) => ({
      class_name: item.class_name,
      pixel_count: item.pixel_count,
      pixel_ratio: item.pixel_ratio,
    })),
    output_image_path: imageResult.value?.image_path,
  };
}

async function runBackendAnalysis() {
  analysisError.value = "";
  analysisText.value = "";
  if (!canAnalyze.value) {
    analysisError.value = "请先在智能检测页面生成识别结果。";
    return;
  }
  analysisLoading.value = true;
  try {
    const response = await fetch("/ai/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target: analysisTarget.value,
        result: buildAnalysisPayload(),
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data?.detail || data?.msg || "AI解析请求失败");
    }
    analysisText.value = data?.content || "未返回解析内容。";
  } catch (error) {
    analysisError.value = error.message.includes("Failed to fetch")
      ? "AI解析请求失败，请确认后端服务已启动。"
      : error.message;
  } finally {
    analysisLoading.value = false;
  }
}
</script>

<template>
  <v-app class="bg-grey-lighten-4">
    <v-main
      v-if="!isAuthenticated"
      class="d-flex align-center justify-center login-bg"
    >
      <v-card
        elevation="8"
        max-width="480"
        width="100%"
        class="pa-8 rounded-xl"
        rounded
      >
        <div class="text-center mb-8">
          <v-avatar color="primary" size="64" class="mb-4 elevation-3">
            <span class="text-h5 font-weight-bold text-white">MP</span>
          </v-avatar>
          <h1 class="text-h4 font-weight-bold mb-2">智能检测平台</h1>
          <p class="text-medium-emphasis">多模型识别与可视化分析系统</p>
        </div>

        <!-- 修改登录表单部分的 v-text-field -->
        <v-form @submit.prevent="login">
          <v-text-field
            v-model.trim="loginForm.username"
            label="用户名"
            prepend-inner-icon="mdi-account-outline"
            variant="outlined"
            bg-color="transparent"
            class="mb-6"
            hide-details="auto"
          ></v-text-field>

          <v-text-field
            v-model="loginForm.password"
            label="密码"
            type="password"
            prepend-inner-icon="mdi-lock-outline"
            variant="outlined"
            bg-color="transparent"
            class="mb-6"
            hide-details="auto"
          ></v-text-field>

          <v-alert
            v-if="loginError"
            type="error"
            variant="tonal"
            class="mb-4"
            density="compact"
          >
            {{ loginError }}
          </v-alert>

          <v-btn
            type="submit"
            color="primary"
            size="x-large"
            block
            elevation="2"
            class="mt-2 rounded-lg"
          >
            安全登录
          </v-btn>
        </v-form>
      </v-card>
    </v-main>

    <template v-else>
      <v-navigation-drawer permanent elevation="2" class="border-0">
        <div class="pa-6 d-flex align-center gap-3">
          <v-avatar color="primary" size="40" class="elevation-2">
            <span class="font-weight-bold text-white">MP</span>
          </v-avatar>
          <div>
            <div class="text-h6 font-weight-bold line-height-1">智能检测</div>
            <div class="text-caption text-medium-emphasis">
              AI Vision Platform
            </div>
          </div>
        </div>

        <v-divider class="mb-2"></v-divider>

        <v-list nav class="px-3">
          <v-list-item
            v-for="item in navItems"
            :key="item.key"
            :active="activePage === item.key"
            @click="openPage(item.key)"
            color="primary"
            class="mb-2 rounded-lg"
            :title="item.label"
            :subtitle="item.desc"
          >
            <template v-slot:prepend>
              <v-icon
                :icon="
                  item.key === 'dashboard'
                    ? 'mdi-view-dashboard'
                    : item.key === 'detect'
                    ? 'mdi-line-scan'
                    : 'mdi-robot-outline'
                "
              ></v-icon>
            </template>
          </v-list-item>
        </v-list>

        <template v-slot:append>
          <div class="pa-4">
            <v-card
              variant="tonal"
              :color="
                health === 'ok'
                  ? 'success'
                  : health === 'error'
                  ? 'error'
                  : 'warning'
              "
              class="mb-4 rounded-lg"
            >
              <div class="d-flex align-center justify-space-between pa-3">
                <div class="d-flex align-center gap-2">
                  <v-badge
                    dot
                    inline
                    :color="
                      health === 'ok'
                        ? 'success'
                        : health === 'error'
                        ? 'error'
                        : 'warning'
                    "
                  ></v-badge>
                  <span class="text-caption font-weight-medium">{{
                    healthText
                  }}</span>
                </div>
                <v-btn
                  variant="text"
                  size="small"
                  density="compact"
                  @click="check"
                  icon="mdi-refresh"
                ></v-btn>
              </div>
            </v-card>
            <v-btn
              block
              color="error"
              variant="tonal"
              class="rounded-lg"
              prepend-icon="mdi-logout"
              @click="logout"
            >
              退出账号
            </v-btn>
          </div>
        </template>
      </v-navigation-drawer>

      <v-app-bar flat class="border-b" color="white">
        <v-app-bar-title>
          <div class="text-h6 font-weight-bold text-grey-darken-3">
            {{ navItems.find((item) => item.key === activePage)?.label }}
          </div>
        </v-app-bar-title>
        <template v-slot:append>
          <v-btn
            color="primary"
            variant="elevated"
            prepend-icon="mdi-plus"
            @click="activePage = 'detect'"
            class="rounded-lg text-none px-4"
          >
            新建检测
          </v-btn>
        </template>
      </v-app-bar>

      <v-main>
        <v-container fluid class="pa-6 pa-md-8 max-w-1440">
          <v-window v-model="activePage">
            <v-window-item
              value="dashboard"
            >
            <v-card
              class="mb-8 rounded-xl bg-gradient-hero"
              elevation="0"
            >
              <v-card-text class="pa-8 pa-md-12">
                <v-row align="center">
                  <v-col cols="12" md="8">
                    <v-chip
                      color="primary"
                      variant="tonal"
                      size="small"
                      class="mb-4"
                      >V 2.0 更新</v-chip
                    >
                    <h2 class="text-h3 font-weight-bold mb-4 line-height-1-2 text-grey-darken-4">
                      多模态智能识别引擎
                    </h2>
                    <p class="text-body-1 mb-8 max-w-600 text-medium-emphasis">
                      上传图片或视频，系统自动完成智能分流、目标定位与分割汇总。支持深度可视化展示，并结合
                      DeepSeek 生成专业的 AI 分析报告。
                    </p>
                    <div class="d-flex gap-4">
                      <v-btn
                        size="large"
                        color="primary"
                        class="rounded-lg font-weight-bold"
                        prepend-icon="mdi-rocket-launch"
                        elevation="1"
                        @click="activePage = 'detect'"
                        >开始检测</v-btn
                      >
                      <v-btn
                        size="large"
                        variant="outlined"
                        class="rounded-lg"
                        prepend-icon="mdi-text-box-search-outline"
                        @click="activePage = 'analysis'"
                        >查看 AI 报告</v-btn
                      >
                    </div>
                  </v-col>
                </v-row>
              </v-card-text>
            </v-card>

            <v-row>
              <v-col cols="12" md="8">
                <v-row class="mb-4">
                  <v-col
                    cols="12"
                    sm="6"
                    md="3"
                    v-for="card in dashboardCards"
                    :key="card.label"
                  >
                    <v-card elevation="1" class="rounded-lg h-100">
                      <v-card-item>
                        <div class="text-overline text-medium-emphasis mb-1">
                          {{ card.label }}
                        </div>
                        <div
                          class="text-h4 font-weight-black"
                          :class="
                            card.tone === 'good'
                              ? 'text-success'
                              : card.tone === 'bad'
                              ? 'text-error'
                              : 'text-primary'
                          "
                        >
                          {{ card.value }}
                        </div>
                      </v-card-item>
                    </v-card>
                  </v-col>
                </v-row>

                <v-card elevation="1" class="rounded-lg">
                  <v-card-title
                    class="font-weight-bold pa-5 border-b d-flex align-center justify-space-between"
                  >
                    最新检测摘要
                    <v-chip
                      size="small"
                      :color="
                        imageResult || videoResult ? 'success' : 'default'
                      "
                    >
                      {{
                        imageResult || videoResult
                          ? "已有识别记录"
                          : "等待首次检测"
                      }}
                    </v-chip>
                  </v-card-title>
                  <v-card-text class="pa-5">
                    <div v-if="imageResult" class="d-flex flex-column gap-3">
                      <v-alert
                        density="compact"
                        variant="tonal"
                        color="primary"
                        icon="mdi-memory"
                      >
                        图片识别已完成，系统调用了
                        <b>{{ activatedGateCount }}</b> 个分析模块。
                      </v-alert>
                      <v-alert
                        v-if="topDetection"
                        density="compact"
                        variant="tonal"
                        color="success"
                        icon="mdi-target"
                      >
                        核心识别目标为 <b>{{ topDetection.class_name }}</b
                        >，置信度
                        <b>{{ formatPercent(topDetection.confidence) }}</b
                        >。
                      </v-alert>
                      <v-alert
                        density="compact"
                        variant="tonal"
                        color="info"
                        icon="mdi-chart-pie"
                      >
                        共识别目标
                        <b>{{ detections.length }}</b> 个，区域分析结果
                        <b>{{ segmentations.length }}</b> 项。
                      </v-alert>
                    </div>
                    <div v-else-if="videoResult">
                      <v-alert
                        density="compact"
                        variant="tonal"
                        color="primary"
                        icon="mdi-video-check"
                      >
                        视频流分析完成，共深度处理
                        <b>{{ videoResult.frame_count }}</b> 帧画面。
                      </v-alert>
                    </div>
                    <div
                      v-else
                      class="text-center pa-8 text-medium-emphasis bg-grey-lighten-4 rounded-lg"
                    >
                      <v-icon size="48" color="grey-lighten-1" class="mb-3"
                        >mdi-chart-box-outline</v-icon
                      >
                      <p>完成检测后，此处将自动萃取并展示核心结论</p>
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" md="4">
                <v-card elevation="1" class="rounded-lg h-100">
                  <v-card-title class="font-weight-bold pa-5 border-b"
                    >标准工作流</v-card-title
                  >
                  <v-card-text class="pa-5">
                    <v-timeline
                      density="compact"
                      align="start"
                      truncate-line="both"
                    >
                      <v-timeline-item dot-color="grey-lighten-2" size="small">
                        <div class="mb-4">
                          <div class="font-weight-bold">上传资料</div>
                          <div class="text-caption text-medium-emphasis">
                            支持多格式图文及视频流
                          </div>
                        </div>
                      </v-timeline-item>
                      <v-timeline-item dot-color="primary" size="small">
                        <div class="mb-4">
                          <div class="font-weight-bold text-primary">
                            智能分流
                          </div>
                          <div class="text-caption text-medium-emphasis">
                            引擎自动匹配最优算法模型
                          </div>
                        </div>
                      </v-timeline-item>
                      <v-timeline-item dot-color="grey-lighten-2" size="small">
                        <div class="mb-4">
                          <div class="font-weight-bold">目标定位与分割</div>
                          <div class="text-caption text-medium-emphasis">
                            精准提取画面内高价值目标
                          </div>
                        </div>
                      </v-timeline-item>
                      <v-timeline-item dot-color="success" size="small">
                        <div>
                          <div class="font-weight-bold text-success">
                            生成报表
                          </div>
                          <div class="text-caption text-medium-emphasis">
                            输出可视化面板与 AI 报告
                          </div>
                        </div>
                      </v-timeline-item>
                    </v-timeline>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <!-- 历史识别记录 -->
            <v-card v-if="historyItems.length" elevation="1" class="rounded-lg mt-8">
              <v-card-title class="font-weight-bold pa-5 border-b d-flex align-center justify-space-between">
                历史识别记录
                <v-btn variant="text" size="small" density="compact" icon="mdi-refresh" @click="loadHistory" :loading="historyLoading"></v-btn>
              </v-card-title>
              <v-card-text class="pa-5">
                <v-row>
                  <v-col
                    v-for="item in historyItems"
                    :key="item.id"
                    cols="12" sm="6" md="4" lg="3"
                  >
                    <v-card
                      variant="outlined"
                      class="rounded-lg overflow-hidden history-card"
                      @click="openPreview(item)"
                    >
                      <div class="d-flex" style="height: 120px">
                        <v-img
                          :src="item.original_url"
                          cover
                          class="w-50 border-e"
                        >
                          <template v-slot:placeholder>
                            <div class="d-flex align-center justify-center w-100 h-100 bg-grey-lighten-3">
                              <v-icon color="grey-lighten-1">mdi-image-outline</v-icon>
                            </div>
                          </template>
                        </v-img>
                        <v-img
                          v-if="item.type === 'image'"
                          :src="item.result_url"
                          cover
                          class="w-50"
                        >
                          <template v-slot:placeholder>
                            <div class="d-flex align-center justify-center w-100 h-100 bg-grey-lighten-3">
                              <v-progress-circular indeterminate size="20" color="grey"></v-progress-circular>
                            </div>
                          </template>
                        </v-img>
                        <video
                          v-else
                          :src="item.result_url"
                          class="w-50"
                          style="object-fit: cover"
                          controlslist="nodownload"
                        ></video>
                      </div>
                      <div class="pa-2 d-flex align-center gap-2">
                        <v-chip size="x-small" :color="item.type === 'video' ? 'info' : 'primary'" variant="flat">
                          {{ item.type === 'video' ? '视频' : '图片' }}
                        </v-chip>
                        <span class="text-caption text-truncate text-medium-emphasis">{{ item.original_name }}</span>
                      </div>
                    </v-card>
                  </v-col>
                </v-row>
              </v-card-text>
            </v-card>
          </v-window-item>

          <v-window-item
              value="detect"
            >
            <v-tabs
              v-model="activeTab"
              color="primary"
              class="mb-6 rounded-lg bg-white elevation-1"
              align-tabs="center"
            >
              <v-tab value="image" prepend-icon="mdi-image-search"
                >单图精识</v-tab
              >
              <v-tab value="batch" prepend-icon="mdi-image-multiple"
                >批量处理</v-tab
              >
              <v-tab value="video" prepend-icon="mdi-video-vintage"
                >视频流分析</v-tab
              >
            </v-tabs>

            <v-row>
              <v-col cols="12" md="8">
                <v-slide-y-transition leave-absolute>
                  <div v-if="activeTab === 'image'">
                    <v-card
                      class="upload-dropzone mb-4 bg-white elevation-1 rounded-xl d-flex flex-column align-center justify-center text-center transition-swing cursor-pointer"
                      :class="{
                        'border-primary bg-primary-lighten-5': imagePreview,
                        'pa-0': imagePreview,
                        'pa-12': !imagePreview,
                      }"
                      min-height="400"
                      @dragover.prevent
                      @drop.prevent="onImageDrop"
                      @click="imgInput?.click()"
                    >
                      <input
                        ref="imgInput"
                        type="file"
                        accept="image/*"
                        hidden
                        @change="onImageDrop"
                      />
                      <v-img
                        v-if="imagePreview"
                        :src="imagePreview"
                        class="w-100 h-100 rounded-xl"
                        cover
                      ></v-img>
                      <div v-else class="text-grey-darken-1">
                        <v-icon
                          size="64"
                          color="primary"
                          class="mb-4 opacity-70"
                          >mdi-cloud-upload-outline</v-icon
                        >
                        <h3 class="text-h6 font-weight-bold mb-2">
                          点击或拖拽上传图片
                        </h3>
                        <p class="text-body-2">支持 JPG, PNG, WebP 格式</p>
                      </div>
                    </v-card>

                    <v-card
                      elevation="1"
                      class="rounded-lg pa-2 d-flex align-center justify-space-between bg-white"
                    >
                      <div class="d-flex align-center pl-4 text-truncate">
                        <v-icon color="grey-darken-1" class="mr-2"
                          >mdi-file-image-outline</v-icon
                        >
                        <span class="text-body-2 text-truncate max-w-300">{{
                          imageFile?.name || "尚未选择文件..."
                        }}</span>
                      </div>
                      <v-btn
                        color="primary"
                        size="large"
                        elevation="2"
                        class="rounded-lg px-6"
                        :loading="imageLoading"
                        :disabled="!imageFile"
                        @click="runImage"
                      >
                        {{ imageLoading ? "云端推理中" : "启动引擎" }}
                      </v-btn>
                    </v-card>
                    <v-alert
                      v-if="imageError"
                      type="error"
                      variant="tonal"
                      class="mt-4"
                      >{{ imageError }}</v-alert
                    >
                  </div>
                </v-slide-y-transition>

                <v-slide-y-transition leave-absolute>
                  <div v-if="activeTab === 'batch'">
                    <v-card
                      class="upload-dropzone mb-4 bg-white elevation-1 rounded-xl d-flex flex-column align-center justify-center text-center cursor-pointer pa-12"
                      min-height="250"
                      @dragover.prevent
                      @drop.prevent="onBatchPick"
                      @click="batchInput?.click()"
                    >
                      <input
                        ref="batchInput"
                        type="file"
                        accept="image/*"
                        multiple
                        hidden
                        @change="onBatchPick"
                      />
                      <div class="text-grey-darken-1">
                        <v-icon
                          size="56"
                          color="primary"
                          class="mb-4 opacity-70"
                          >mdi-folder-upload-outline</v-icon
                        >
                        <h3 class="text-h6 font-weight-bold mb-2">
                          批量导入数据集
                        </h3>
                        <p class="text-body-2">
                          一次性选择多张图片，自动进入分析队列
                        </p>
                      </div>
                    </v-card>

                    <v-card
                      elevation="1"
                      class="rounded-lg pa-2 d-flex align-center justify-space-between bg-white mb-4"
                    >
                      <div class="d-flex align-center pl-4 gap-4">
                        <v-chip color="default" size="small"
                          >总计: {{ batchSummary.total }}</v-chip
                        >
                        <v-chip color="success" size="small"
                          >完成: {{ batchSummary.done }}</v-chip
                        >
                        <v-chip color="error" size="small"
                          >异常: {{ batchSummary.failed }}</v-chip
                        >
                      </div>
                      <v-btn
                        color="primary"
                        size="large"
                        elevation="2"
                        class="rounded-lg px-6"
                        :loading="batchLoading"
                        :disabled="!batchItems.length"
                        @click="runBatchImages"
                      >
                        {{ batchLoading ? "队列执行中" : "开始批量处理" }}
                      </v-btn>
                    </v-card>
                    <v-alert
                      v-if="batchError"
                      type="error"
                      variant="tonal"
                      class="mb-4"
                      >{{ batchError }}</v-alert
                    >

                    <v-row v-if="batchItems.length">
                      <v-col
                        cols="12"
                        sm="6"
                        v-for="item in batchItems"
                        :key="item.id"
                      >
                        <v-card
                          elevation="1"
                          class="rounded-lg d-flex pa-3"
                          :class="
                            item.status === 'done'
                              ? 'border-success bg-green-lighten-5'
                              : item.status === 'error'
                              ? 'border-error bg-red-lighten-5'
                              : ''
                          "
                          variant="outlined"
                        >
                          <v-avatar
                            rounded="lg"
                            size="80"
                            class="bg-grey-lighten-3 mr-4"
                          >
                            <v-img
                              :src="
                                item.result?.image_path
                                  ? resultUrl(item.result.image_path)
                                  : item.preview
                              "
                              cover
                            ></v-img>
                            <div
                              v-if="item.status === 'running'"
                              class="position-absolute d-flex align-center justify-center w-100 h-100 bg-black opacity-50"
                            >
                              <v-progress-circular
                                indeterminate
                                color="white"
                                size="24"
                              ></v-progress-circular>
                            </div>
                            <v-icon
                              v-if="item.status === 'done'"
                              class="position-absolute top-0 right-0 ma-1"
                              color="success"
                              >mdi-check-circle</v-icon
                            >
                          </v-avatar>
                          <div
                            class="flex-grow-1 d-flex flex-column justify-center overflow-hidden"
                          >
                            <div
                              class="text-subtitle-2 font-weight-bold text-truncate mb-1"
                            >
                              {{ item.file.name }}
                            </div>
                            <div v-if="item.result" class="d-flex gap-2 mb-1">
                              <v-chip
                                size="x-small"
                                color="primary"
                                variant="flat"
                                >🎯
                                {{
                                  item.result.detections?.length || 0
                                }}</v-chip
                              >
                              <v-chip size="x-small" color="info" variant="flat"
                                >🧩
                                {{
                                  item.result.segmentations?.length || 0
                                }}</v-chip
                              >
                            </div>
                            <a
                              v-if="item.result?.image_path"
                              :href="resultUrl(item.result.image_path)"
                              target="_blank"
                              class="text-caption text-primary text-decoration-none"
                              >查看大图</a
                            >
                            <div
                              v-if="item.error"
                              class="text-caption text-error text-truncate"
                            >
                              {{ item.error }}
                            </div>
                          </div>
                        </v-card>
                      </v-col>
                    </v-row>
                  </div>
                </v-slide-y-transition>

                <v-slide-y-transition leave-absolute>
                  <div v-if="activeTab === 'video'">
                    <v-card
                      class="upload-dropzone mb-4 bg-white elevation-1 rounded-xl d-flex flex-column align-center justify-center text-center cursor-pointer pa-12"
                      min-height="350"
                      @click="videoInput?.click()"
                    >
                      <input
                        ref="videoInput"
                        type="file"
                        accept="video/*"
                        hidden
                        @change="onVideoPick"
                      />
                      <div class="text-grey-darken-1">
                        <v-icon
                          size="64"
                          color="primary"
                          class="mb-4 opacity-70"
                          >mdi-video-plus-outline</v-icon
                        >
                        <h3 class="text-h6 font-weight-bold mb-2">
                          上传视频流
                        </h3>
                        <p class="text-body-2">支持 MP4 / AVI / MOV</p>
                      </div>
                    </v-card>

                    <v-card
                      elevation="1"
                      class="rounded-lg pa-2 d-flex align-center justify-space-between bg-white"
                    >
                      <div class="d-flex align-center pl-4 text-truncate">
                        <v-icon color="grey-darken-1" class="mr-2"
                          >mdi-filmstrip</v-icon
                        >
                        <span class="text-body-2 text-truncate max-w-300">{{
                          videoFile?.name || "尚未选择视频文件..."
                        }}</span>
                      </div>
                      <v-btn
                        color="primary"
                        size="large"
                        elevation="2"
                        class="rounded-lg px-6"
                        :loading="videoLoading"
                        :disabled="!videoFile"
                        @click="runVideo"
                      >
                        {{ videoLoading ? "逐帧分析中" : "启动视频解析" }}
                      </v-btn>
                    </v-card>
                    <v-alert
                      v-if="videoError"
                      type="error"
                      variant="tonal"
                      class="mt-4"
                      >{{ videoError }}</v-alert
                    >

                    <!-- 实时推理画面 -->
                    <v-card
                      v-if="videoLoading || videoStreamFrame"
                      elevation="1"
                      class="rounded-xl mt-4 pa-4 bg-grey-darken-4"
                    >
                      <div
                        class="d-flex align-center justify-space-between mb-3"
                      >
                        <div class="d-flex align-center gap-2 text-white">
                          <v-icon color="primary"
                            >mdi-motion-play-outline</v-icon
                          >
                          <span class="font-weight-bold">{{
                            videoResult ? "推理完成画面" : "实时推理画面"
                          }}</span>
                        </div>
                        <v-chip size="small" color="primary" variant="flat">
                          {{ videoProgress.current
                          }}<template v-if="videoProgress.total">
                            / {{ videoProgress.total }}</template
                          >
                          帧
                        </v-chip>
                      </div>
                      <v-img
                        v-if="videoStreamFrame"
                        :src="videoStreamFrame"
                        max-height="480"
                        class="rounded-lg"
                        contain
                      ></v-img>
                      <div
                        v-else
                        class="d-flex align-center justify-center"
                        style="height: 240px"
                      >
                        <v-progress-circular
                          indeterminate
                          color="primary"
                        ></v-progress-circular>
                      </div>
                      <v-progress-linear
                        v-if="videoProgress.total"
                        :model-value="
                          (videoProgress.current / videoProgress.total) * 100
                        "
                        color="primary"
                        height="6"
                        rounded
                        class="mt-3"
                      ></v-progress-linear>
                      <v-progress-linear
                        v-else-if="videoLoading"
                        indeterminate
                        color="primary"
                        height="6"
                        rounded
                        class="mt-3"
                      ></v-progress-linear>
                    </v-card>
                  </div>
                </v-slide-y-transition>
              </v-col>

              <v-col cols="12" md="4">
                <v-card elevation="1" class="rounded-lg h-100 bg-white">
                  <v-card-title
                    class="font-weight-bold pa-5 border-b d-flex align-center justify-space-between"
                  >
                    {{ activeTab === "video" ? "渲染结果" : "实时概览" }}
                    <v-chip
                      size="small"
                      :color="
                        (activeTab === 'video' ? videoResult : imageResult)
                          ? 'success'
                          : 'default'
                      "
                    >
                      {{
                        (activeTab === "video" ? videoResult : imageResult)
                          ? "分析完成"
                          : "待命"
                      }}
                    </v-chip>
                  </v-card-title>

                  <v-card-text class="pa-5">
                    <!-- 阈值调节 -->
                    <div class="mb-4 pa-3 bg-blue-lighten-5 rounded-lg">
                      <div class="d-flex align-center justify-space-between mb-1">
                        <span class="text-caption text-medium-emphasis">门控阈值</span>
                        <v-chip size="x-small" color="primary" variant="flat" class="font-weight-bold">{{ gateThreshold.toFixed(2) }}</v-chip>
                      </div>
                      <v-slider
                        v-model="gateThreshold"
                        :min="0"
                        :max="1"
                        :step="0.01"
                        color="primary"
                        density="compact"
                        thumb-label="always"
                        hide-details
                      ></v-slider>
                      <div class="d-flex justify-space-between mt-n1">
                        <span class="text-caption text-grey">宽松</span>
                        <span class="text-caption text-grey">严格</span>
                      </div>
                    </div>

                    <template v-if="activeTab === 'image'">
                      <div class="d-flex flex-column gap-3 mb-6">
                        <div
                          v-for="item in imageSummary"
                          :key="item.label"
                          class="d-flex justify-space-between pa-3 bg-grey-lighten-4 rounded-lg"
                        >
                          <span class="text-medium-emphasis">{{
                            item.label
                          }}</span>
                          <strong class="text-grey-darken-3">{{
                            item.value
                          }}</strong>
                        </div>
                      </div>

                      <v-card
                        v-if="topDetection"
                        color="primary-lighten-5"
                        variant="flat"
                        class="pa-4 rounded-lg text-center border-primary position-relative"
                        style="border-width: 1px; border-style: solid"
                      >
                        <v-icon size="32" color="primary" class="mb-2"
                          >mdi-bullseye-arrow</v-icon
                        >
                        <div class="text-caption text-medium-emphasis mb-1">
                          核心锁定目标
                        </div>
                        <div class="text-h5 font-weight-bold text-primary">
                          {{ topDetection.class_name }}
                        </div>
                        <v-chip
                          color="success"
                          size="small"
                          class="position-absolute top-0 right-0 ma-2 font-weight-bold"
                        >
                          {{ formatPercent(topDetection.confidence) }}
                        </v-chip>
                      </v-card>
                      <div v-else class="text-center pa-6 text-medium-emphasis">
                        <p class="text-caption">
                          引擎启动后，关键指标将在此展示
                        </p>
                      </div>
                    </template>

                    <template v-else-if="activeTab === 'video'">
                      <div v-if="videoResult" class="d-flex flex-column h-100">
                        <div
                          class="d-flex justify-space-between pa-4 bg-grey-lighten-4 rounded-lg mb-4"
                        >
                          <span class="text-medium-emphasis">处理总帧数</span>
                          <strong class="text-h6">{{
                            videoResult.frame_count
                          }}</strong>
                        </div>
                        <video
                          v-if="resultVideoUrl"
                          :src="resultVideoUrl"
                          controls
                          class="w-100 rounded-lg bg-black mb-4"
                        ></video>
                        <v-btn
                          v-if="resultVideoUrl"
                          :href="resultVideoUrl"
                          download
                          block
                          variant="outlined"
                          color="primary"
                          prepend-icon="mdi-download"
                        >
                          下载原画质视频
                        </v-btn>
                      </div>
                      <div
                        v-else-if="videoLoading"
                        class="d-flex flex-column gap-3"
                      >
                        <div
                          class="d-flex justify-space-between pa-4 bg-grey-lighten-4 rounded-lg"
                        >
                          <span class="text-medium-emphasis">已处理帧</span>
                          <strong class="text-h6"
                            >{{ videoProgress.current
                            }}<span
                              v-if="videoProgress.total"
                              class="text-body-2 text-medium-emphasis"
                            >
                              / {{ videoProgress.total }}</span
                            ></strong
                          >
                        </div>
                        <div
                          class="d-flex justify-space-between pa-3 bg-grey-lighten-4 rounded-lg"
                        >
                          <span class="text-medium-emphasis">当前帧目标</span>
                          <strong>{{ videoLive?.detections?.length || 0 }}</strong>
                        </div>
                        <div
                          class="d-flex justify-space-between pa-3 bg-grey-lighten-4 rounded-lg"
                        >
                          <span class="text-medium-emphasis">当前帧分割</span>
                          <strong>{{
                            videoLive?.segmentations?.length || 0
                          }}</strong>
                        </div>
                        <v-alert
                          density="compact"
                          variant="tonal"
                          color="primary"
                          icon="mdi-motion-play-outline"
                        >
                          正在逐帧实时推理，左侧可同步观看推理画面。
                        </v-alert>
                      </div>
                      <div
                        v-else
                        class="text-center pa-10 text-medium-emphasis bg-grey-lighten-4 rounded-lg"
                      >
                        <v-icon size="48" color="grey-lighten-1" class="mb-3"
                          >mdi-filmstrip-off</v-icon
                        >
                        <p class="text-body-2">
                          视频处理完成后可在线预览或下载原片
                        </p>
                      </div>
                    </template>

                    <template v-else>
                      <div
                        class="text-center pa-8 text-medium-emphasis bg-grey-lighten-4 rounded-lg"
                      >
                        <v-icon size="48" color="grey-lighten-1" class="mb-3"
                          >mdi-information-outline</v-icon
                        >
                        <p class="text-body-2">
                          批量模式下，左侧列表将实时更新每张图片的识别进度
                        </p>
                      </div>
                    </template>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <v-slide-y-transition>
              <div v-if="activeTab === 'image' && imageResult" class="mt-8">
                <div class="d-flex align-center gap-2 mb-4">
                  <v-icon color="primary">mdi-text-box-search</v-icon>
                  <h2 class="text-h5 font-weight-bold m-0">深度解析报告</h2>
                </div>

                <v-card
                  v-if="resultImageUrl"
                  elevation="1"
                  class="rounded-xl pa-4 bg-grey-darken-4 mb-6"
                >
                  <v-img
                    :src="resultImageUrl"
                    max-height="600"
                    class="rounded-lg"
                    contain
                  ></v-img>
                </v-card>

                <v-row>
                  <v-col cols="12" md="6">
                    <v-card elevation="1" class="rounded-lg h-100">
                      <v-card-title
                        class="pa-4 border-b d-flex justify-space-between align-center text-body-1 font-weight-bold"
                      >
                        模块路由状态
                        <v-chip size="x-small" color="info" variant="flat"
                          >阈值 {{ imageResult.gate?.threshold ?? "-" }}</v-chip
                        >
                      </v-card-title>
                      <v-card-text class="pa-4">
                        <v-list density="compact" class="bg-transparent pa-0">
                          <v-list-item
                            v-for="gate in gateList"
                            :key="gate.key"
                            class="mb-2 rounded-lg border"
                            :class="
                              gate.active
                                ? 'border-primary bg-primary-lighten-5'
                                : 'border-grey-lighten-2'
                            "
                          >
                            <template v-slot:prepend>
                              <v-icon
                                :color="
                                  gate.active ? 'primary' : 'grey-lighten-1'
                                "
                                size="small"
                                >mdi-circle</v-icon
                              >
                            </template>
                            <v-list-item-title class="font-weight-medium">{{
                              gate.label
                            }}</v-list-item-title>
                            <template v-slot:append>
                              <span
                                class="text-primary font-weight-bold font-mono"
                                >{{ formatPercent(gate.prob) }}</span
                              >
                            </template>
                          </v-list-item>
                        </v-list>
                      </v-card-text>
                    </v-card>
                  </v-col>

                  <v-col cols="12" md="6">
                    <v-card elevation="1" class="rounded-lg h-100">
                      <v-card-title
                        class="pa-4 border-b d-flex justify-space-between align-center text-body-1 font-weight-bold"
                      >
                        目标检测清单
                        <v-chip size="x-small" color="default"
                          >{{ detections.length }} 项</v-chip
                        >
                      </v-card-title>
                      <v-table
                        v-if="detections.length"
                        density="comfortable"
                        hover
                      >
                        <thead>
                          <tr>
                            <th
                              class="text-left text-caption text-grey-darken-1 font-weight-bold"
                            >
                              识别类别
                            </th>
                            <th
                              class="text-left text-caption text-grey-darken-1 font-weight-bold"
                            >
                              置信度
                            </th>
                            <th
                              class="text-left text-caption text-grey-darken-1 font-weight-bold"
                            >
                              边界框坐标 (xyxy)
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="(item, index) in detections" :key="index">
                            <td>
                              <v-chip size="small" variant="outlined">{{
                                item.class_name
                              }}</v-chip>
                            </td>
                            <td>
                              <div class="d-flex align-center gap-2">
                                <v-progress-linear
                                  :model-value="item.confidence * 100"
                                  color="primary"
                                  height="6"
                                  rounded
                                  class="w-50"
                                ></v-progress-linear>
                                <span class="text-caption font-weight-bold">{{
                                  formatPercent(item.confidence)
                                }}</span>
                              </div>
                            </td>
                            <td
                              class="text-caption font-mono text-medium-emphasis"
                            >
                              {{
                                item.box_xyxy
                                  .map((value) => value.toFixed(1))
                                  .join(", ")
                              }}
                            </td>
                          </tr>
                        </tbody>
                      </v-table>
                      <div
                        v-else
                        class="pa-6 text-center text-medium-emphasis text-body-2"
                      >
                        未检测到相关目标
                      </div>
                    </v-card>
                  </v-col>

                  <v-col cols="12">
                    <v-card elevation="1" class="rounded-lg">
                      <v-card-title
                        class="pa-4 border-b d-flex justify-space-between align-center text-body-1 font-weight-bold"
                      >
                        语义分割数据
                        <v-chip size="x-small" color="default"
                          >{{ segmentations.length }} 项</v-chip
                        >
                      </v-card-title>
                      <v-table
                        v-if="segmentations.length"
                        density="comfortable"
                        hover
                      >
                        <thead>
                          <tr>
                            <th
                              class="text-left text-caption text-grey-darken-1 font-weight-bold"
                            >
                              分割类别
                            </th>
                            <th
                              class="text-left text-caption text-grey-darken-1 font-weight-bold"
                            >
                              像素体积
                            </th>
                            <th
                              class="text-left text-caption text-grey-darken-1 font-weight-bold"
                            >
                              画面占比
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr
                            v-for="(item, index) in segmentations"
                            :key="index"
                          >
                            <td>
                              <v-chip
                                size="small"
                                variant="outlined"
                                color="info"
                                >{{ item.class_name }}</v-chip
                              >
                            </td>
                            <td class="font-mono text-body-2">
                              {{ item.pixel_count.toLocaleString() }} px
                            </td>
                            <td class="w-50">
                              <div class="d-flex align-center gap-2">
                                <v-progress-linear
                                  :model-value="item.pixel_ratio * 100"
                                  color="info"
                                  height="6"
                                  rounded
                                ></v-progress-linear>
                                <span
                                  class="text-caption font-weight-bold"
                                  style="min-width: 45px"
                                  >{{
                                    formatPercent(item.pixel_ratio, 2)
                                  }}</span
                                >
                              </div>
                            </td>
                          </tr>
                        </tbody>
                      </v-table>
                      <div
                        v-else
                        class="pa-6 text-center text-medium-emphasis text-body-2"
                      >
                        未提取到有效的分割区域
                      </div>
                    </v-card>
                  </v-col>
                </v-row>
              </div>
            </v-slide-y-transition>
          </v-window-item>

          <v-window-item
              value="analysis"
            >
            <v-row>
              <v-col cols="12" md="8">
                <v-card
                  elevation="2"
                  class="rounded-xl overflow-hidden h-100 border"
                >
                  <div
                    class="bg-blue-lighten-5 pa-6 d-flex align-center gap-4"
                  >
                    <v-avatar
                      color="blue-lighten-1"
                      rounded="lg"
                      size="48"
                    >
                      <v-icon size="28" color="white">mdi-robot-outline</v-icon>
                    </v-avatar>
                    <div>
                      <h2 class="text-h5 font-weight-bold mb-1 text-grey-darken-4">
                        DeepSeek 洞察引擎
                      </h2>
                      <p class="text-caption text-medium-emphasis ma-0">
                        自然语言解析检测结果，一键生成业务价值结论
                      </p>
                    </div>
                  </div>

                  <v-card-text class="pa-6">
                    <v-card
                      variant="tonal"
                      color="grey"
                      class="pa-4 mb-6 rounded-lg d-flex align-center flex-wrap gap-4 bg-grey-lighten-4"
                    >
                      <v-select
                        v-model="analysisTarget"
                        :items="[
                          { title: '单图检测结果', value: 'image' },
                          { title: '批量检测结果', value: 'batch' },
                          { title: '视频流分析结果', value: 'video' },
                        ]"
                        label="选择数据源"
                        variant="outlined"
                        density="comfortable"
                        hide-details
                        bg-color="white"
                        style="max-width: 250px"
                      ></v-select>
                      <v-btn
                        color="primary"
                        size="large"
                        elevation="2"
                        class="rounded-lg font-weight-bold"
                        prepend-icon="mdi-auto-fix"
                        :loading="analysisLoading"
                        :disabled="!canAnalyze"
                        @click="runBackendAnalysis"
                      >
                        生成专业报告
                      </v-btn>
                    </v-card>

                    <v-alert
                      v-if="analysisError"
                      type="error"
                      variant="tonal"
                      class="mb-4"
                      >{{ analysisError }}</v-alert
                    >

                    <v-card
                      v-if="analysisText"
                      variant="outlined"
                      class="rounded-lg border-primary bg-white"
                    >
                      <v-card-text
                        class="pa-6 text-body-1 line-height-1-8 text-grey-darken-3"
                      >
                        <pre class="font-sans whitespace-pre-wrap">{{
                          analysisText
                        }}</pre>
                      </v-card-text>
                    </v-card>

                    <div
                      v-else
                      class="text-center pa-12 text-medium-emphasis border rounded-lg border-dashed"
                    >
                      <v-icon size="64" color="grey-lighten-2" class="mb-4"
                        >mdi-text-box-search-outline</v-icon
                      >
                      <h3 class="text-h6 mb-2">等待执行指令</h3>
                      <p class="text-body-2 max-w-400 mx-auto">
                        请先在【智能检测】中生成识别结果。AI
                        将自动梳理底层数据，生成具备业务价值的总结摘要与复核建议。
                      </p>
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" md="4">
                <v-card elevation="1" class="rounded-lg mb-6 bg-white">
                  <v-card-title class="pa-4 border-b font-weight-bold"
                    >报告结构体系</v-card-title
                  >
                  <v-card-text class="pa-4">
                    <v-list lines="two" bg-color="transparent" class="pa-0">
                      <v-list-item class="px-0">
                        <template v-slot:prepend
                          ><v-avatar
                            color="primary-lighten-5"
                            class="text-primary rounded-lg mr-3"
                            ><v-icon>mdi-text-box-outline</v-icon></v-avatar
                          ></template
                        >
                        <v-list-item-title class="font-weight-bold text-body-2"
                          >执行摘要</v-list-item-title
                        >
                        <v-list-item-subtitle class="text-caption mt-1"
                          >一句话概括核心发现与场景定性</v-list-item-subtitle
                        >
                      </v-list-item>
                      <v-list-item class="px-0 mt-2">
                        <template v-slot:prepend
                          ><v-avatar
                            color="info-lighten-5"
                            class="text-info rounded-lg mr-3"
                            ><v-icon>mdi-chart-bar</v-icon></v-avatar
                          ></template
                        >
                        <v-list-item-title class="font-weight-bold text-body-2"
                          >数据支撑</v-list-item-title
                        >
                        <v-list-item-subtitle class="text-caption mt-1"
                          >置信度、边界坐标及像素占比深度剖析</v-list-item-subtitle
                        >
                      </v-list-item>
                      <v-list-item class="px-0 mt-2">
                        <template v-slot:prepend
                          ><v-avatar
                            color="warning-lighten-5"
                            class="text-warning rounded-lg mr-3"
                            ><v-icon>mdi-shield-check-outline</v-icon></v-avatar
                          ></template
                        >
                        <v-list-item-title class="font-weight-bold text-body-2"
                          >风控建议</v-list-item-title
                        >
                        <v-list-item-subtitle class="text-caption mt-1"
                          >识别边缘情况并提供针对性人工复核建议</v-list-item-subtitle
                        >
                      </v-list-item>
                    </v-list>
                  </v-card-text>
                </v-card>

                <v-card
                  elevation="1"
                  class="rounded-lg bg-blue-lighten-5"
                >
                  <v-card-title
                    class="pa-4 border-b font-weight-bold d-flex gap-2 align-center text-body-2 text-grey-darken-3"
                  >
                    <v-icon size="small" color="blue-darken-1">mdi-code-json</v-icon> 底层 Payload
                    预览
                  </v-card-title>
                  <v-card-text class="pa-0">
                    <pre
                      class="pa-4 ma-0 text-caption text-grey-darken-2 overflow-auto max-h-300"
                      >{{
                        canAnalyze
                          ? JSON.stringify(buildAnalysisPayload(), null, 2)
                          : "// 暂无数据\n// 请先完成一次识别检测"
                      }}</pre
                    >
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>
          </v-window-item>
          </v-window>
        </v-container>
      </v-main>

      <!-- 历史记录预览弹窗 -->
      <v-dialog v-model="previewDialog" max-width="1100" scrollable>
        <v-card v-if="previewItem" class="rounded-xl">
          <v-card-title
            class="d-flex align-center justify-space-between pa-4 border-b"
          >
            <div class="d-flex align-center gap-2 overflow-hidden">
              <v-chip
                size="small"
                :color="previewItem.type === 'video' ? 'info' : 'primary'"
                variant="flat"
              >
                {{ previewItem.type === "video" ? "视频" : "图片" }}
              </v-chip>
              <span class="text-body-1 font-weight-bold text-truncate">{{
                previewItem.original_name
              }}</span>
            </div>
            <v-btn
              icon="mdi-close"
              variant="text"
              density="comfortable"
              @click="previewDialog = false"
            ></v-btn>
          </v-card-title>

          <v-card-text class="pa-4">
            <v-row>
              <v-col cols="12" md="6">
                <div class="text-caption text-medium-emphasis mb-2">
                  原始素材
                </div>
                <video
                  v-if="previewItem.type === 'video'"
                  :src="previewItem.original_url"
                  controls
                  class="w-100 rounded-lg bg-black"
                ></video>
                <v-img
                  v-else
                  :src="previewItem.original_url"
                  max-height="560"
                  class="rounded-lg bg-grey-lighten-3"
                  contain
                ></v-img>
              </v-col>
              <v-col cols="12" md="6">
                <div class="text-caption text-medium-emphasis mb-2">
                  识别结果
                </div>
                <video
                  v-if="previewItem.type === 'video'"
                  :src="previewItem.result_url"
                  controls
                  autoplay
                  class="w-100 rounded-lg bg-black"
                ></video>
                <v-img
                  v-else
                  :src="previewItem.result_url"
                  max-height="560"
                  class="rounded-lg bg-grey-lighten-3"
                  contain
                ></v-img>
              </v-col>
            </v-row>
          </v-card-text>

          <v-card-actions class="pa-4 pt-0">
            <v-spacer></v-spacer>
            <v-btn
              :href="previewItem.result_url"
              download
              variant="outlined"
              color="primary"
              prepend-icon="mdi-download"
            >
              下载结果
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>
    </template>
  </v-app>
</template>

<style scoped>
/* 辅助工具类 & 微调 */
.gap-2 {
  gap: 8px;
}
.gap-3 {
  gap: 12px;
}
.gap-4 {
  gap: 16px;
}
.max-w-300 {
  max-width: 300px;
}
.max-w-400 {
  max-width: 400px;
}
.max-w-600 {
  max-width: 600px;
}
.max-w-1440 {
  max-width: 1440px;
  margin: 0 auto;
}
.line-height-1 {
  line-height: 1;
}
.line-height-1-2 {
  line-height: 1.2;
}
.line-height-1-8 {
  line-height: 1.8;
}
.font-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.font-sans {
  font-family: inherit;
}
.whitespace-pre-wrap {
  white-space: pre-wrap;
}
.max-h-300 {
  max-height: 300px;
}

/* 登录背景渐变 */
.login-bg {
  background: linear-gradient(135deg, #e0e7ff 0%, #ede9fe 100%);
}

/* Dashboard Hero 渐变 — 浅蓝调 */
.bg-gradient-hero {
  background: linear-gradient(135deg, #e3f2fd 0%, #e8eaf6 100%);
  border: 1px solid rgba(66, 165, 245, 0.1);
}

/* 虚线上传区交互效果 */
.upload-dropzone {
  border: 2px dashed #cbd5e1;
  background-color: #f8fafc;
}
.upload-dropzone:hover {
  border-color: #6366f1;
  background-color: #eef2ff;
}

/* 表格样式优化 */
:deep(th) {
  background-color: #f8fafc !important;
}

/* 过渡动画 */
.transition-swing {
  transition: 0.3s cubic-bezier(0.25, 0.8, 0.5, 1) all;
}

/* 历史记录卡片：可点击预览 */
.history-card {
  cursor: pointer;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}
.history-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.18) !important;
}
</style>

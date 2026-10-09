<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { normalizeFilters, stateValues, statusQuery } from '../utils/filters.js'
import { canSelectCandidate, chooseCandidate, matchesCandidateFilters } from '../utils/selection.js'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'SeedRescue' },
  showClose: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
  navKey: { type: String, default: 'main' },
})

const emit = defineEmits(['action', 'close'])
const loading = ref(false)
const operating = ref('')
const error = ref('')
const selectedCandidates = ref({})
const downloadConfirmation = ref(null)
const activeView = ref(props.navKey === 'history' ? 'history' : 'current')
const page = ref(1)
const pageSize = 20
const filterDraft = ref({})
const appliedFilters = ref({})
const filterError = ref('')
const hasFilters = computed(() => Object.keys(appliedFilters.value).length > 0)
const stateOptions = Object.entries(stateValues).map(([value, [title]]) => ({ title, value }))
const status = ref({ enabled: false, selection_mode: 'manual', summary: {}, jobs: [] })
const hostToast = inject('moviepilot:toast', null)
let refreshTimer
let statusRequest = 0
let disposed = false
let lastRefresh = 0

const pluginBase = computed(() => `plugin/${props.pluginId || 'SeedRescue'}`)
const jobs = computed(() => status.value.view === activeView.value ? status.value.jobs || [] : [])
const viewSummary = computed(() => status.value.view === activeView.value ? status.value.view_summary || {} : {})
const pageTitle = computed(() => activeView.value === 'current' ? '当前 RSS 种子' : '历史 RSS 记录')
const scanRunning = computed(() => status.value.scan_status?.state === 'running')
const actionBusy = computed(() => Boolean(operating.value) || status.value.busy || scanRunning.value)
const hasSourceFilters = computed(() => Boolean(appliedFilters.value.source_site_id || appliedFilters.value.source_promotion))
const scanStage = computed(() => ({
  preparing: '准备扫描', reconcile: '核对下载状态', recovery: '恢复待处理任务',
  rss: '拉取 RSS 与种子元数据', matching: 'IYUU 匹配与来源查询', target_stats: '更新原站信息',
}[status.value.scan_status?.stage] || '扫描'))
const scanColor = computed(() => ({
  running: 'info', success: 'success', partial: 'warning', failed: 'error', interrupted: 'warning',
}[status.value.scan_status?.state] || 'info'))

function unwrapResponse(response) {
  const result = response && Object.prototype.hasOwnProperty.call(response, 'success') ? response : response?.data ?? response
  if (result && Object.prototype.hasOwnProperty.call(result, 'success')) {
    if (result.success === false) {
      const err = new Error(result.message || '操作失败')
      err.details = result.data
      throw err
    }
    return result.data
  }
  return result
}

function notify(text, color = 'success') {
  const method = ['error', 'info', 'warning', 'success'].includes(color) ? color : 'success'
  if (typeof hostToast?.[method] === 'function') hostToast[method](text)
  else if (method === 'error') error.value = text
}

function candidateOptions(job) {
  return [...(job.candidates || []), ...(job.target_candidate ? [job.target_candidate] : [])]
}

function canSelect(job, candidate) {
  return canSelectCandidate(job, candidate)
}

function matchesFilters(candidate) {
  return matchesCandidateFilters(candidate, appliedFilters.value)
}

function recommendedId(job) {
  return candidateOptions(job).find(candidate => canSelect(job, candidate) && matchesFilters(candidate))?.candidate_id
}

function syncSelections() {
  for (const job of status.value.jobs || []) {
    selectedCandidates.value[job.target_hash] = chooseCandidate(job, selectedCandidates.value[job.target_hash], appliedFilters.value)
  }
}

function canDownloadSelected(job) {
  return candidateOptions(job).some((candidate) =>
    candidate.candidate_id === selectedCandidates.value[job.target_hash] && canSelect(job, candidate))
}

async function loadStatus() {
  const request = ++statusRequest
  lastRefresh = Date.now()
  loading.value = true
  try {
    const data = unwrapResponse(await props.api.get(
      `${pluginBase.value}/status?${statusQuery(activeView.value, page.value, pageSize, appliedFilters.value)}`))
    if (request !== statusRequest) return
    status.value = data || status.value
    page.value = status.value.pagination?.page || 1
    error.value = ''
    syncSelections()
  } catch (err) {
    if (request === statusRequest) error.value = err?.message || '加载稀缺保种任务失败'
  } finally {
    if (request === statusRequest) loading.value = false
  }
}

function selectView(view) {
  activeView.value = view
  page.value = 1
  loadStatus()
}

function changePage(value) {
  page.value = value
  loadStatus()
}

function applyFilters() {
  try {
    appliedFilters.value = normalizeFilters(filterDraft.value)
    selectedCandidates.value = {}
    filterError.value = ''
    page.value = 1
    loadStatus()
  } catch (err) {
    filterError.value = err.message
  }
}

function resetFilters() {
  filterDraft.value = {}
  applyFilters()
}

watch(() => props.navKey, (value) => selectView(value === 'history' ? 'history' : 'current'))

async function scanNow() {
  operating.value = 'scan'
  try {
    unwrapResponse(await props.api.post(`${pluginBase.value}/scan`, {}))
    await loadStatus()
    notify('已提交后台扫描，可在进度栏查看结果', 'info')
    emit('action')
  } catch (err) {
    notify(err?.message || 'RSS 扫描失败', 'error')
  } finally {
    operating.value = ''
  }
}

async function runJobAction(job, action, body = {}) {
  operating.value = `${job.target_hash}:${action}`
  try {
    unwrapResponse(await props.api.post(`${pluginBase.value}/jobs/${job.target_hash}/${action}`, body))
    await loadStatus()
    notify(action === 'download' ? '所选种子已提交下载' : action === 'retry' ? '重新匹配完成' : '任务已忽略')
    emit('action')
  } catch (err) {
    if (action === 'download' && err?.details?.confirmation_required) {
      downloadConfirmation.value = { ...err.details, target_hash: job.target_hash, skip_future_risk_confirmation: false }
    } else {
      notify(err?.message || '操作失败', 'error')
    }
  } finally {
    operating.value = ''
  }
}

function downloadSelected(job) {
  const candidateId = selectedCandidates.value[job.target_hash]
  if (!candidateId) {
    notify('请先选择一个来源种子', 'warning')
    return
  }
  runJobAction(job, 'download', { candidate_id: candidateId })
}

function confirmDownload() {
  const selection = downloadConfirmation.value
  if (!selection) return
  downloadConfirmation.value = null
  runJobAction({ target_hash: selection.target_hash }, 'download', {
    candidate_id: selection.candidate_id,
    confirmed_download_factor: selection.promotion === 'non_free' ? selection.download_factor : null,
    confirm_unknown: selection.promotion === 'unknown',
    skip_future_risk_confirmation: selection.skip_future_risk_confirmation === true,
  })
}

function stateMeta(state) {
  const value = stateValues[state] || [state || '未知', 'secondary']
  return { text: value[0], color: value[1] }
}

function promotionText(candidate) {
  if (candidate.promotion === 'free') return '免费'
  if (candidate.promotion === 'unknown') return '促销未知'
  if (candidate.download_factor !== null && candidate.download_factor !== undefined) {
    return `${Math.round(Number(candidate.download_factor) * 100)}% 下载`
  }
  return '非免费'
}

function matchedProbeCount(job) {
  return (job.probes || []).filter((probe) => probe.matched).length
}

function unmatchedProbes(job) {
  return (job.probes || []).filter((probe) => !probe.matched && !(job.candidates || []).some(
    (candidate) => String(candidate.site_id) === String(probe.site_id)
      && String(candidate.torrent_id) === String(probe.torrent_id),
  ))
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`
}

function canRetry(job) {
  return !['SOURCE_SUBMITTING', 'SOURCE_DOWNLOADING', 'TARGET_DOWNLOADING', 'WAITING_IYUU', 'TARGET_RECHECKING', 'TARGET_SEEDING', 'TARGET_COMPLETE', 'TARGET_PAUSED', 'TARGET_ERROR'].includes(job.state)
}

function formatTime(value) {
  if (!value) return '尚未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await loadStatus()
  if (disposed) return
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !operating.value && !loading.value &&
        (scanRunning.value || Date.now() - lastRefresh >= 15000)) loadStatus()
  }, 5000)
})

onUnmounted(() => {
  disposed = true
  statusRequest += 1
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="seed-rescue" :class="{ 'seed-rescue--compact': compact }">
    <header class="seed-rescue__header">
      <div>
        <div class="d-flex align-center ga-2">
          <VIcon icon="mdi-seed-outline" color="primary" size="30" />
          <h1>稀缺保种 · {{ pageTitle }}</h1>
        </div>
        <p v-if="activeView === 'current'">最新成功拉取的 RSS 中仍在列出的种子，可选择跨站来源或原种直下。</p>
        <p v-else>已移出 RSS 的种子保留在这里，下载进度和保种任务继续跟踪。</p>
      </div>
      <div class="d-flex ga-2">
        <VBtn variant="tonal" prepend-icon="mdi-refresh" :loading="loading" @click="loadStatus">刷新</VBtn>
        <VBtn color="primary" prepend-icon="mdi-rss" :loading="operating === 'scan' || scanRunning" :disabled="actionBusy" @click="scanNow">扫描 RSS</VBtn>
        <VBtn v-if="showClose" icon="mdi-close" variant="text" @click="emit('close')" />
      </div>
    </header>

    <div v-if="status.confirm_download_risk === false" class="text-caption text-medium-emphasis mb-4">
      下载流量风险提醒已关闭，可在插件配置中重新开启“下载前提醒流量风险”。
    </div>

    <VAlert v-if="status.scan_status?.state && status.scan_status.state !== 'idle'" :type="scanColor" variant="tonal" class="mb-4">
      <template v-if="scanRunning">
        后台扫描中 · {{ scanStage }}
        <span v-if="status.scan_status.total">（{{ status.scan_status.completed || 0 }} / {{ status.scan_status.total }}）</span>
        <VProgressLinear class="mt-2" color="primary" :indeterminate="!status.scan_status.total"
          :model-value="status.scan_status.total ? 100 * (status.scan_status.completed || 0) / status.scan_status.total : 0" />
        <div class="text-caption mt-2">可继续筛选和浏览；下载、重试、忽略暂时禁用，避免任务冲突。开始于 {{ formatTime(status.scan_status.started_at) }}</div>
      </template>
      <template v-else>{{ status.scan_status.message }} · {{ formatTime(status.scan_status.finished_at) }}</template>
      <div v-for="issue in status.scan_status.issues || []" :key="issue" class="text-caption mt-1">{{ issue }}</div>
    </VAlert>

    <VTabs :model-value="activeView" color="primary" class="mb-4" @update:model-value="selectView">
      <VTab value="current" prepend-icon="mdi-rss">当前 RSS <VChip size="x-small" class="ml-2">{{ status.summary.current || 0 }}</VChip></VTab>
      <VTab value="history" prepend-icon="mdi-history">历史记录 <VChip size="x-small" class="ml-2">{{ status.summary.history || 0 }}</VChip></VTab>
    </VTabs>

    <VCard variant="outlined" class="mb-4">
      <VCardText>
        <form @submit.prevent="applyFilters">
          <VRow>
            <VCol cols="12" sm="6" md="4"><VSelect v-model="filterDraft.state" label="任务状态" :items="stateOptions" clearable hide-details /></VCol>
            <VCol cols="12" sm="6" md="4">
              <VSelect v-model="filterDraft.promotion" label="原站促销" clearable hide-details
                :items="[{ title: '免费', value: 'free' }, { title: '非免费', value: 'non_free' }, { title: '未知', value: 'unknown' }]" />
            </VCol>
            <VCol cols="12" sm="6" md="4">
              <VSelect v-model="filterDraft.source_promotion" label="跨站促销" clearable hide-details
                :items="[{ title: '免费', value: 'free' }, { title: '非免费', value: 'non_free' }, { title: '未知', value: 'unknown' }]" />
            </VCol>
            <VCol cols="12" md="6">
              <VSelect v-model="filterDraft.source_site_id" label="跨站候选站点" :items="status.filter_options?.source_sites || []" clearable hide-details />
            </VCol>
            <VCol cols="6" md="3"><VTextField v-model="filterDraft.min_seeders" type="number" min="0" step="1" label="原站做种人数 ≥" clearable hide-details /></VCol>
            <VCol cols="6" md="3"><VTextField v-model="filterDraft.max_seeders" type="number" min="0" step="1" label="原站做种人数 ≤" clearable hide-details /></VCol>
          </VRow>
          <div class="text-caption text-medium-emphasis mt-3">条件留空表示不限；人数范围中的 0 表示零人，未知人数不符合范围条件。切换当前 / 历史保留已应用条件，仅筛选展示，不影响下载规则。</div>
          <div class="text-caption text-medium-emphasis mt-1">跨站筛选依据已有候选；同时选择站点和促销时，须由同一个跨站候选满足。</div>
          <VAlert v-if="filterError" type="error" variant="tonal" class="mt-3">{{ filterError }}</VAlert>
          <div class="d-flex flex-wrap align-center ga-2 mt-3">
            <VBtn type="submit" color="primary" prepend-icon="mdi-filter-outline">筛选</VBtn>
            <VBtn variant="text" @click="resetFilters">重置</VBtn>
            <span class="text-caption text-medium-emphasis">{{ hasFilters ? '筛选结果' : '全部记录' }}：{{ viewSummary.total || 0 }} / {{ status.view === activeView ? status.view_total || 0 : 0 }} 条</span>
          </div>
        </form>
      </VCardText>
    </VCard>

    <VAlert v-if="error" type="error" variant="tonal" class="mb-4" closable @click:close="error = ''">
      {{ error }}
    </VAlert>
    <VAlert v-if="!status.enabled" type="warning" variant="tonal" class="mb-4">
      插件当前未启用，请先完成配置。
    </VAlert>
    <VAlert v-if="status.rss_status?.failed_feeds" type="warning" variant="tonal" class="mb-4">
      {{ status.rss_status.failed_feeds }} 个 RSS 最近拉取失败，当前列表保留它们上次成功拉取的内容。
    </VAlert>
    <VAlert v-if="status.summary.unclassified" type="info" variant="tonal" class="mb-4">
      {{ status.summary.unclassified }} 条旧记录暂列历史，下一次成功扫描 RSS 后会确认当前归属。
    </VAlert>
    <div class="text-caption text-medium-emphasis mb-3">
      最近成功拉取：{{ formatTime(status.rss_status?.last_success_at) }}
    </div>

    <section class="seed-rescue__summary">
      <VCard variant="tonal"><VCardText><strong>{{ viewSummary.total || 0 }}</strong><span>{{ hasFilters ? '筛选结果' : activeView === 'current' ? '当前 RSS 种子' : '历史记录' }}</span></VCardText></VCard>
      <VCard variant="tonal"><VCardText><strong>{{ viewSummary.awaiting_selection || 0 }}</strong><span>等待选择</span></VCardText></VCard>
      <VCard variant="tonal"><VCardText><strong>{{ viewSummary.downloading || 0 }}</strong><span>正在下载</span></VCardText></VCard>
      <VCard variant="tonal"><VCardText><strong>{{ viewSummary.target_seeding || 0 }}</strong><span>保种成功</span></VCardText></VCard>
    </section>

    <VProgressLinear v-if="loading" indeterminate color="primary" class="mb-3" />
    <VEmptyState
      v-if="!jobs.length && !loading"
      icon="mdi-rss-off"
      :title="hasFilters ? '没有符合筛选条件的记录' : activeView === 'current' ? '当前 RSS 暂无种子记录' : '暂无历史 RSS 记录'"
      :text="hasFilters ? '请调整条件或点击“重置”查看本列表全部记录。' : activeView === 'current' ? '点击“扫描 RSS”拉取最新列表；以往记录可在历史页查看。' : '种子移出 RSS 后会在这里保留，供查看和继续操作。'"
    />

    <VExpansionPanels v-else :key="`${activeView}:${page}`" multiple variant="accordion" class="seed-rescue__jobs">
      <VExpansionPanel v-for="job in jobs" :key="job.target_hash">
        <VExpansionPanelTitle>
          <div class="seed-rescue__job-title">
            <span>{{ job.title }}</span>
            <VChip :color="stateMeta(job.state).color" size="small" variant="tonal">
              {{ stateMeta(job.state).text }}
            </VChip>
            <span v-if="job.candidates?.length" class="text-medium-emphasis">{{ job.candidates.length }} 个跨站来源 · {{ job.candidates.filter(candidate => candidate.eligible !== false).length }} 个通过下载规则</span>
            <span v-else-if="matchedProbeCount(job)" class="text-medium-emphasis">
              {{ matchedProbeCount(job) }} 个已匹配（被筛选）
            </span>
          </div>
        </VExpansionPanelTitle>
        <VExpansionPanelText>
          <div class="text-caption text-medium-emphasis mb-3">
            首次发现：{{ formatTime(job.created_at) }} · 最近 RSS 出现：{{ formatTime(job.rss_last_seen_at) }}
            <span v-if="job.rss_archived_at"> · 移入历史：{{ formatTime(job.rss_archived_at) }}</span>
            <span v-else-if="job.rss_current === undefined"> · 等待 RSS 扫描确认</span>
          </div>
          <VCard variant="tonal" class="seed-rescue__target mb-3">
            <VCardText class="d-flex align-center flex-wrap ga-2">
              <VBtn
                v-if="job.target_page_url"
                :href="job.target_page_url"
                target="_blank"
                rel="noopener noreferrer"
                variant="text"
                size="small"
                prepend-icon="mdi-open-in-new"
              >{{ job.target_site_name || '目标站详情' }}</VBtn>
              <span v-else class="text-body-2">{{ job.target_site_name || '目标站' }}</span>
              <VChip size="small" color="success" variant="tonal">做种 {{ job.target_seeders ?? '未知' }}</VChip>
              <VChip size="small" color="info" variant="tonal">下载 {{ job.target_peers ?? '未知' }}</VChip>
              <VChip size="small" variant="tonal">完成 {{ job.target_grabs ?? '未知' }}</VChip>
              <VChip size="small" variant="tonal">大小 {{ formatBytes(job.target_size) }}</VChip>
            </VCardText>
          </VCard>

          <VAlert v-if="job.reason" type="info" variant="tonal" density="compact" class="mb-3">
            {{ job.reason }}
            <div v-if="job.next_retry_at" class="text-caption mt-1">连续失败 {{ job.retry_count || 0 }} 次；{{ formatTime(job.next_retry_at) }} 后的扫描可自动重试。</div>
          </VAlert>

          <VRadioGroup v-if="candidateOptions(job).length" v-model="selectedCandidates[job.target_hash]" hide-details>
            <VTable density="comfortable" class="seed-rescue__table">
              <thead><tr><th></th><th>来源站</th><th>做种</th><th>下载</th><th>完成</th><th>大小</th><th>促销</th><th></th></tr></thead>
              <tbody>
                <tr v-for="candidate in candidateOptions(job)" :key="candidate.candidate_id"
                  :class="{ 'seed-rescue__matched': hasSourceFilters && matchesFilters(candidate) }">
                  <td><VRadio :value="candidate.candidate_id" :disabled="!canSelect(job, candidate) || actionBusy" /></td>
                  <td>
                    <a
                      v-if="candidate.page_url"
                      :href="candidate.page_url"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="seed-rescue__link"
                      :title="candidate.title || candidate.site_name"
                    >{{ candidate.site_name }} <VIcon icon="mdi-open-in-new" size="x-small" /></a>
                    <span v-else>{{ candidate.site_name }}</span>
                    <span v-if="candidate.is_target" class="text-caption text-medium-emphasis ml-2">保种站点</span>
                    <div v-else class="text-caption text-medium-emphasis mt-1">
                      ID {{ candidate.torrent_id }} · {{ candidate.metadata_status === 'unavailable' ? 'IYUU 已收录 · 详情未获取' : candidate.lookup_method === 'detail' ? '按 ID 查详情' : candidate.lookup_method === 'search' ? '搜索补全' : 'IYUU 同源' }}
                    </div>
                  </td>
                  <td><strong>{{ candidate.seeders ?? '未知' }}</strong></td>
                  <td>{{ candidate.leechers ?? '-' }}</td>
                  <td>{{ candidate.grabs ?? '-' }}</td>
                  <td>{{ formatBytes(candidate.size) }}</td>
                  <td>
                    <VChip size="x-small" :color="candidate.promotion === 'free' ? 'success' : 'default'">{{ promotionText(candidate) }}</VChip>
                    <div v-if="candidate.is_target && candidate.promotion_updated_at" class="text-caption text-medium-emphasis mt-1">
                      最近确认：{{ formatTime(candidate.promotion_updated_at) }}
                    </div>
                    <div v-if="candidate.promotion_note" class="text-caption text-warning mt-1">{{ candidate.promotion_note }}</div>
                  </td>
                  <td>
                    <VChip v-if="candidate.is_target" size="x-small" color="info" variant="tonal">原种直下</VChip>
                    <VChip v-else-if="candidate.eligible === false" size="x-small" color="warning" variant="tonal">不可下载</VChip>
                    <VChip v-else-if="candidate.candidate_id === recommendedId(job)" size="x-small" color="primary" variant="tonal">推荐</VChip>
                    <VChip v-if="hasSourceFilters && matchesFilters(candidate)" size="x-small" color="success" variant="tonal" class="ml-1">符合页面筛选</VChip>
                    <div v-if="candidate.exclusion_reason" class="text-caption text-warning mt-1">{{ candidate.exclusion_reason }}</div>
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VRadioGroup>

          <div v-if="job.target_candidate?.selectable" class="text-caption text-medium-emphasis mt-2 mb-3">
            保种站点原种可手动下载，不受跨站来源的做种人数和促销筛选限制；实际速度取决于原站做种情况，下载计费以站点为准。
          </div>

          <div v-if="unmatchedProbes(job).length" class="seed-rescue__probes mb-3">
            <div class="text-caption text-medium-emphasis mb-2">尚未命中的来源（不代表站点没有资源）</div>
            <div class="d-flex flex-wrap ga-2">
              <VChip
                v-for="(probe, index) in unmatchedProbes(job)"
                :key="`${probe.site_id}-${index}`"
                size="small"
                :color="probe.matched ? 'warning' : 'secondary'"
                variant="tonal"
                :href="probe.page_url || undefined"
                :target="probe.page_url ? '_blank' : undefined"
                :rel="probe.page_url ? 'noopener noreferrer' : undefined"
              >
                {{ probe.site_name }} ·
                {{ probe.error || (probe.search_limited ? '已达分页上限，未命中' : '已查范围内未命中') }}
              </VChip>
            </div>
          </div>

          <div v-if="job.source_site_name" class="text-body-2 mb-3">
            已选来源：{{ job.source_site_name }} · {{ job.source_seeders ?? '未知' }} 人做种
          </div>
          <div class="d-flex flex-wrap ga-2 mt-3">
            <VBtn
              v-if="canDownloadSelected(job)"
              color="primary"
              prepend-icon="mdi-download"
              :loading="operating === `${job.target_hash}:download`"
              :disabled="actionBusy"
              @click="downloadSelected(job)"
            >下载所选种子</VBtn>
            <VBtn
              v-if="canRetry(job)"
              variant="tonal"
              prepend-icon="mdi-refresh"
              :loading="operating === `${job.target_hash}:retry`"
              :disabled="actionBusy"
              @click="runJobAction(job, 'retry')"
            >重新匹配</VBtn>
            <VBtn
              v-if="canRetry(job) && job.state !== 'IGNORED'"
              variant="text"
              color="secondary"
              :disabled="actionBusy"
              @click="runJobAction(job, 'ignore')"
            >忽略</VBtn>
          </div>
        </VExpansionPanelText>
      </VExpansionPanel>
    </VExpansionPanels>
    <div v-if="status.pagination?.pages > 1 && status.view === activeView" class="mt-4">
      <div class="text-caption text-medium-emphasis text-center">共 {{ status.pagination.total }} 条，每页 {{ pageSize }} 条</div>
      <VPagination :model-value="page" :length="status.pagination.pages" :total-visible="5" :disabled="loading" @update:model-value="changePage" />
    </div>
    <VDialog :model-value="Boolean(downloadConfirmation)" max-width="520" @update:model-value="value => { if (!value) downloadConfirmation = null }">
      <VCard v-if="downloadConfirmation" title="确认下载流量风险">
        <VCardText>
          <div>{{ downloadConfirmation.title }}</div>
          <div class="mt-2">所选站点：{{ downloadConfirmation.site_name }}</div>
          <VAlert type="warning" variant="tonal" class="mt-3">
            服务端刚确认的促销：{{ promotionText(downloadConfirmation) }}。
            此次下载可能计入站点下载量，以站点规则为准。确认后会再次检查，促销变化时需要重新确认。
          </VAlert>
          <VCheckbox v-model="downloadConfirmation.skip_future_risk_confirmation"
            label="后续不再提示下载流量风险" color="warning" hide-details />
          <div class="text-caption text-medium-emphasis">
            确认下载后保存，对本插件所有手动下载生效（含原站、跨站及促销未知）；可在插件配置中重新开启。
          </div>
        </VCardText>
        <VCardActions>
          <VSpacer />
          <VBtn variant="text" @click="downloadConfirmation = null">取消</VBtn>
          <VBtn color="warning" :disabled="actionBusy" @click="confirmDownload">确认下载</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.seed-rescue {
  padding: 24px;
}

.seed-rescue--compact {
  padding: 8px;
  min-width: min(68rem, 92vw);
}

.seed-rescue__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.seed-rescue__header h1 {
  margin: 0;
  font-size: 1.55rem;
}

.seed-rescue__header p {
  margin: 6px 0 0;
  color: rgb(var(--v-theme-on-surface-variant));
}

.seed-rescue__summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.seed-rescue__summary .v-card-text {
  display: flex;
  flex-direction: column;
}

.seed-rescue__summary strong {
  font-size: 1.6rem;
}

.seed-rescue__job-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 0;
}

.seed-rescue__job-title > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
}

.seed-rescue__table {
  overflow-x: auto;
}

.seed-rescue__matched {
  background: rgba(var(--v-theme-success), 0.06);
}

.seed-rescue__link {
  color: rgb(var(--v-theme-primary));
  text-decoration: none;
}

.seed-rescue__link:hover {
  text-decoration: underline;
}

@media (max-width: 760px) {
  .seed-rescue__header {
    flex-direction: column;
  }

  .seed-rescue__summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

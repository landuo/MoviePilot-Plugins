// 仅使用虚构数据和内存 API，不连接 NAS、站点或下载器。
import { createApp, h, ref } from 'vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import 'vuetify/styles'
import Workbench from '../../../../plugins.v2/seedrescue/src/components/SeedRescueWorkbench.vue'
import Config from '../../../../plugins.v2/seedrescue/src/components/Config.vue'

const downloads = ref(0)
const confirmRisk = ref(true)
const showConfig = ref(false)
const previewRevision = ref(0)
const scan = ref({ state: 'idle' })
const job = {
  target_hash: 'a'.repeat(40), title: '演示资源 · 仅供交互测试', state: 'AWAITING_SELECTION',
  target_site_name: '原站（演示）', target_seeders: 1, target_size: 1073741824,
  target_candidate: { candidate_id: 'target', is_target: true, selectable: true, site_id: 1,
    site_name: '原站（演示）', promotion: 'unknown', seeders: 1, size: 1073741824 },
  candidates: [
    { candidate_id: 'paid', site_id: 7, torrent_id: '42', lookup_method: 'detail', grabs: 125,
      site_name: '收费来源（演示）', promotion: 'non_free', download_factor: 1, seeders: 50, size: 1073741824 },
    { candidate_id: 'free', site_id: 8, site_name: '免费来源（演示）', promotion: 'free', download_factor: 0, seeders: 20, size: 1073741824 },
    { candidate_id: 'low', site_id: 9, site_name: '低做种来源（演示）', promotion: 'free', seeders: 2,
      eligible: false, exclusion_reason: '做种 2 人，少于最低 5 人', size: 1073741824 },
    { candidate_id: 'pending', site_id: 10, torrent_id: '99', site_name: '详情失败（演示）', promotion: 'unknown',
      eligible: false, metadata_status: 'unavailable', exclusion_reason: '详情请求失败，请检查登录状态、网络或站点限流' },
  ],
  probes: [{ site_id: 10, site_name: '未命中来源（演示）', matched: false, search_limited: true }],
}
const api = {
  async get(path) {
    const view = new URLSearchParams(path.split('?')[1]).get('view') || 'current'
    return { success: true, data: {
      enabled: true, busy: scan.value.state === 'running', scan_status: scan.value,
      confirm_download_risk: confirmRisk.value,
      selection_mode: 'manual', view, view_total: 1, summary: { current: 1, history: 1 },
      view_summary: { total: 1, awaiting_selection: downloads.value ? 0 : 1 },
      jobs: [structuredClone(job)], pagination: { page: 1, pages: 1, total: 1 },
      filter_options: { source_sites: [{ title: '收费来源（演示）', value: '7' }, { title: '免费来源（演示）', value: '8' }] },
    } }
  },
  async post(path, body) {
    if (path.endsWith('/scan')) {
      scan.value = { state: 'running', stage: 'matching', completed: 1, total: 2, started_at: new Date().toISOString() }
      setTimeout(() => { scan.value = { ...scan.value, state: 'success', completed: 2, message: '模拟扫描完成', finished_at: new Date().toISOString() } }, 8000)
      return { success: true, data: {} }
    }
    if (path.endsWith('/download')) {
      if (confirmRisk.value && body.candidate_id === 'paid' && body.confirmed_download_factor !== 1) {
        return { success: false, message: '需要确认', data: { confirmation_required: true,
          candidate_id: 'paid', title: job.title, site_name: '收费来源（演示）', promotion: 'non_free', download_factor: 1 } }
      }
      if (body.skip_future_risk_confirmation && body.confirmed_download_factor === 1) confirmRisk.value = false
      downloads.value += 1
      job.state = 'SOURCE_DOWNLOADING'
      job.selected_candidate_id = body.candidate_id
      job.target_candidate.selectable = false
    }
    return { success: true, data: {} }
  },
}

createApp({ setup: () => () => h(components.VApp, {}, () => [
  h('div', { style: 'padding:12px;background:#e0f2fe' }, `本地模拟测试 · 不会真实下载 · 模拟提交次数：${downloads.value}`),
  h(components.VBtn, { onClick: () => { showConfig.value = !showConfig.value } }, () => '切换模拟配置'),
  h(components.VBtn, { onClick: () => {
    job.state = 'AWAITING_SELECTION'
    delete job.selected_candidate_id
    job.target_candidate.selectable = true
    previewRevision.value += 1
  } }, () => '重置演示任务'),
  showConfig.value ? h(Config, { api, initialConfig: { confirm_download_risk: confirmRisk.value },
    onSave: config => { confirmRisk.value = config.confirm_download_risk; showConfig.value = false },
    onClose: () => { showConfig.value = false },
  }) : h(Workbench, { api, key: previewRevision.value }),
]) }).use(createVuetify({ components, directives })).mount('#app')

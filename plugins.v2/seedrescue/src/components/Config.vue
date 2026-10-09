<script setup>
import { onMounted, ref } from 'vue'
import { optionalLimit } from '../utils/config.js'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['save', 'close', 'switch', 'layout'])
const form = ref({
  enabled: false,
  notify: true,
  confirm_download_risk: true,
  onlyonce: false,
  cron: '*/30 * * * *',
  token: '',
  target_site_id: null,
  rss_urls: '',
  source_site_ids: [],
  minimum_seeders: null,
  allowed_promotions: ['free', 'non_free'],
  downloader: '',
  save_path: '',
  max_download_count: null,
  initial_limit: null,
  selection_mode: 'manual',
  ...JSON.parse(JSON.stringify(props.initialConfig || {})),
})
const options = ref({ sites: [], downloaders: [] })
const error = ref('')

function unwrapResponse(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'success')) {
    if (response.success === false) throw new Error(response.message || '操作失败')
    return response.data
  }
  return response?.data ?? response
}

async function loadOptions() {
  try {
    const data = unwrapResponse(await props.api.get('plugin/SeedRescue/status'))
    options.value = data?.options || options.value
  } catch (err) {
    error.value = err?.message || '加载站点和下载器失败'
  }
}

function saveConfig() {
  try {
    const payload = {
      ...form.value,
      target_site_id: Number(form.value.target_site_id || 0),
      source_site_ids: (form.value.source_site_ids || []).map(Number),
      minimum_seeders: optionalLimit(form.value.minimum_seeders, '最少做种人数'),
      max_download_count: optionalLimit(form.value.max_download_count, '同时下载数'),
      initial_limit: optionalLimit(form.value.initial_limit, '每个 RSS 单次处理上限'),
    }
    error.value = ''
    emit('save', payload)
  } catch (err) {
    error.value = err.message
  }
}

onMounted(() => {
  emit('layout', { maxWidth: '72rem' })
  loadOptions()
})
</script>

<template>
  <div class="seed-rescue-config pa-4">
    <VAlert v-if="error" type="error" variant="tonal" class="mb-4" closable @click:close="error = ''">
      {{ error }}
    </VAlert>
    <VRow>
      <VCol cols="12" md="4"><VSwitch v-model="form.enabled" label="启用插件" color="primary" /></VCol>
      <VCol cols="12" md="4"><VSwitch v-model="form.notify" label="发送通知" color="primary" /></VCol>
      <VCol cols="12" md="4"><VSwitch v-model="form.onlyonce" label="保存后立即扫描一次" color="primary" /></VCol>
      <VCol cols="12">
        <VSwitch v-model="form.confirm_download_risk" label="下载前提醒流量风险" color="primary"
          hint="默认开启。关闭后，手动下载非免费或促销未知的原站、跨站种子不再弹窗；仍按站点规则计算下载量。"
          persistent-hint />
      </VCol>
      <VCol cols="12" md="4">
        <VSelect
          v-model="form.selection_mode"
          label="来源选择模式"
          :items="[
            { title: '手动选择', value: 'manual' },
            { title: '自动选择', value: 'auto' },
            { title: '仅一个候选时自动', value: 'hybrid' },
          ]"
        />
      </VCol>
      <VCol cols="12" md="4"><VTextField v-model="form.cron" label="扫描 CRON" /></VCol>
      <VCol cols="12" md="4"><VTextField v-model="form.token" label="IYUU Token" type="password" /></VCol>
      <VCol cols="12" md="6">
        <VSelect v-model="form.target_site_id" label="需要保种的目标站点" :items="options.sites" />
      </VCol>
      <VCol cols="12" md="6">
        <VSelect v-model="form.downloader" label="qBittorrent 下载器" :items="options.downloaders" />
      </VCol>
      <VCol cols="12">
        <VTextarea v-model="form.rss_urls" label="目标站 RSS（每行一个）" rows="3" />
      </VCol>
      <VCol cols="12">
        <VSelect
          v-model="form.source_site_ids"
          label="允许的来源站点"
          :items="options.sites"
          multiple
          chips
          closable-chips
        />
      </VCol>
      <VCol cols="12" md="4">
        <VTextField v-model="form.minimum_seeders" type="number" min="0" step="1" label="最少做种人数"
          clearable hint="留空或 0 表示不限制做种人数" persistent-hint />
      </VCol>
      <VCol cols="12" md="4">
        <VSelect
          v-model="form.allowed_promotions"
          label="允许的促销"
          :items="[{ title: '免费', value: 'free' }, { title: '非免费', value: 'non_free' }]"
          multiple
          chips
        />
        <div class="text-caption text-medium-emphasis mt-n3">
          跨站来源在手动模式下也遵守筛选；保种站点的原种可在工作台单独选择直下，不受此筛选限制。
        </div>
      </VCol>
      <VCol cols="12" md="4">
        <VTextField v-model="form.max_download_count" type="number" min="0" step="1" label="同时下载数"
          clearable hint="留空或 0 表示不限制同时下载数" persistent-hint />
      </VCol>
      <VCol cols="12" md="8"><VTextField v-model="form.save_path" label="来源下载目录" /></VCol>
      <VCol cols="12" md="4">
        <VTextField v-model="form.initial_limit" type="number" min="0" step="1" label="每个 RSS 单次处理上限"
          clearable hint="留空或 0 表示处理全部；原站信息补查也不限制条数，并发限速仍保留" persistent-hint />
      </VCol>
    </VRow>
    <div class="d-flex justify-end ga-2 mt-4">
      <VBtn variant="text" @click="emit('close')">取消</VBtn>
      <VBtn color="primary" variant="flat" @click="saveConfig">保存</VBtn>
    </div>
  </div>
</template>

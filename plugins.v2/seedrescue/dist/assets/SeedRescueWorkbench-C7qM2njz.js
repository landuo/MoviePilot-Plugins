import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const stateValues = {
  MATCHING: ['匹配中', 'info'],
  SOURCE_SUBMITTING: ['下载提交待确认', 'warning'],
  WAITING_SOURCE_RETRY: ['等待来源重试', 'warning'],
  FAILED_MATCHING: ['匹配重试已停止', 'error'],
  AWAITING_SELECTION: ['等待选择', 'warning'],
  SOURCE_DOWNLOADING: ['来源下载中', 'primary'],
  TARGET_DOWNLOADING: ['原种下载中', 'primary'],
  WAITING_CAPACITY: ['等待下载名额', 'warning'],
  WAITING_IYUU: ['等待 IYUU', 'info'],
  WAITING_IYUU_RETRY: ['等待 IYUU 重试', 'warning'],
  TARGET_RECHECKING: ['目标种校验中', 'info'],
  TARGET_SEEDING: ['保种成功', 'success'],
  TARGET_COMPLETE: ['数据完整待做种', 'info'],
  TARGET_PAUSED: ['目标种已暂停', 'warning'],
  TARGET_ERROR: ['目标种异常', 'error'],
  SKIPPED_NO_IYUU_MATCH: ['无跨站匹配', 'secondary'],
  SKIPPED_NO_HEALTHY_SOURCE: ['无符合筛选来源', 'secondary'],
  FAILED_TARGET_TORRENT: ['目标种失败', 'error'],
  FAILED_SOURCE_DOWNLOAD: ['来源下载失败', 'error'],
  IGNORED: ['已忽略', 'secondary'],
};

function normalizeFilters(filters) {
  const result = {};
  for (const key of ['state', 'promotion', 'source_promotion', 'source_site_id']) {
    const value = String(filters[key] ?? '').trim();
    if (value) result[key] = value;
  }
  for (const key of ['min_seeders', 'max_seeders']) {
    const value = filters[key];
    if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) continue
    const number = Number(value);
    if (!['number', 'string'].includes(typeof value) || !Number.isSafeInteger(number) || number < 0) {
      throw new Error('做种人数请填写非负整数，留空表示不限')
    }
    result[key] = number;
  }
  if (result.min_seeders !== undefined && result.max_seeders !== undefined && result.min_seeders > result.max_seeders) {
    throw new Error('最低做种人数不能大于最高做种人数')
  }
  return result
}

function statusQuery(view, page, pageSize, filters) {
  return new URLSearchParams({ view, page, page_size: pageSize, ...filters }).toString()
}

function canSelectCandidate(job, candidate) {
  return candidate.is_target ? candidate.selectable : candidate.eligible !== false && job.state === 'AWAITING_SELECTION'
}

function matchesCandidateFilters(candidate, filters) {
  if (filters.source_site_id || filters.source_promotion) {
    if (candidate.is_target) return false
    if (filters.source_site_id && String(candidate.site_id) !== String(filters.source_site_id)) return false
    if (filters.source_promotion && candidate.promotion !== filters.source_promotion) return false
  }
  return true
}

function chooseCandidate(job, currentId, filters) {
  const options = [...(job.candidates || []), ...(job.target_candidate ? [job.target_candidate] : [])];
  if (job.selected_candidate_id) return job.selected_candidate_id
  // 用户手动改选后，轮询不覆盖；应用新筛选时由页面清空旧选择。
  const current = options.find(candidate => candidate.candidate_id === currentId);
  if (current && canSelectCandidate(job, current)) return currentId
  return options.find(candidate => canSelectCandidate(job, candidate) && matchesCandidateFilters(candidate, filters))?.candidate_id
}

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {resolveComponent:_resolveComponent,createVNode:_createVNode,toDisplayString:_toDisplayString,createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,createBlock:_createBlock,Fragment:_Fragment,renderList:_renderList,unref:_unref,withModifiers:_withModifiers,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "seed-rescue__header" };
const _hoisted_2 = { class: "d-flex align-center ga-2" };
const _hoisted_3 = { key: 0 };
const _hoisted_4 = { key: 1 };
const _hoisted_5 = { class: "d-flex ga-2" };
const _hoisted_6 = {
  key: 0,
  class: "text-caption text-medium-emphasis mb-4"
};
const _hoisted_7 = { key: 0 };
const _hoisted_8 = { class: "text-caption mt-2" };
const _hoisted_9 = { class: "d-flex flex-wrap align-center ga-2 mt-3" };
const _hoisted_10 = { class: "text-caption text-medium-emphasis" };
const _hoisted_11 = { class: "text-caption text-medium-emphasis mb-3" };
const _hoisted_12 = { class: "seed-rescue__summary" };
const _hoisted_13 = { class: "seed-rescue__job-title" };
const _hoisted_14 = {
  key: 0,
  class: "text-medium-emphasis"
};
const _hoisted_15 = {
  key: 1,
  class: "text-medium-emphasis"
};
const _hoisted_16 = { class: "text-caption text-medium-emphasis mb-3" };
const _hoisted_17 = { key: 0 };
const _hoisted_18 = { key: 1 };
const _hoisted_19 = {
  key: 1,
  class: "text-body-2"
};
const _hoisted_20 = {
  key: 0,
  class: "text-caption mt-1"
};
const _hoisted_21 = ["href", "title"];
const _hoisted_22 = { key: 1 };
const _hoisted_23 = {
  key: 2,
  class: "text-caption text-medium-emphasis ml-2"
};
const _hoisted_24 = {
  key: 3,
  class: "text-caption text-medium-emphasis mt-1"
};
const _hoisted_25 = {
  key: 0,
  class: "text-caption text-medium-emphasis mt-1"
};
const _hoisted_26 = {
  key: 1,
  class: "text-caption text-warning mt-1"
};
const _hoisted_27 = {
  key: 4,
  class: "text-caption text-warning mt-1"
};
const _hoisted_28 = {
  key: 2,
  class: "text-caption text-medium-emphasis mt-2 mb-3"
};
const _hoisted_29 = {
  key: 3,
  class: "seed-rescue__probes mb-3"
};
const _hoisted_30 = { class: "d-flex flex-wrap ga-2" };
const _hoisted_31 = {
  key: 4,
  class: "text-body-2 mb-3"
};
const _hoisted_32 = { class: "d-flex flex-wrap ga-2 mt-3" };
const _hoisted_33 = {
  key: 9,
  class: "mt-4"
};
const _hoisted_34 = { class: "text-caption text-medium-emphasis text-center" };
const _hoisted_35 = { class: "mt-2" };

const {computed,inject,onMounted,onUnmounted,ref,watch} = await importShared('vue');

const pageSize = 20;

const _sfc_main = {
  __name: 'SeedRescueWorkbench',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'SeedRescue' },
  showClose: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
  navKey: { type: String, default: 'main' },
},
  emits: ['action', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;
const loading = ref(false);
const operating = ref('');
const error = ref('');
const selectedCandidates = ref({});
const downloadConfirmation = ref(null);
const activeView = ref(props.navKey === 'history' ? 'history' : 'current');
const page = ref(1);
const filterDraft = ref({});
const appliedFilters = ref({});
const filterError = ref('');
const hasFilters = computed(() => Object.keys(appliedFilters.value).length > 0);
const stateOptions = Object.entries(stateValues).map(([value, [title]]) => ({ title, value }));
const status = ref({ enabled: false, selection_mode: 'manual', summary: {}, jobs: [] });
const hostToast = inject('moviepilot:toast', null);
let refreshTimer;
let statusRequest = 0;
let disposed = false;
let lastRefresh = 0;

const pluginBase = computed(() => `plugin/${props.pluginId || 'SeedRescue'}`);
const jobs = computed(() => status.value.view === activeView.value ? status.value.jobs || [] : []);
const viewSummary = computed(() => status.value.view === activeView.value ? status.value.view_summary || {} : {});
const pageTitle = computed(() => activeView.value === 'current' ? '当前 RSS 种子' : '历史 RSS 记录');
const scanRunning = computed(() => status.value.scan_status?.state === 'running');
const actionBusy = computed(() => Boolean(operating.value) || status.value.busy || scanRunning.value);
const hasSourceFilters = computed(() => Boolean(appliedFilters.value.source_site_id || appliedFilters.value.source_promotion));
const scanStage = computed(() => ({
  preparing: '准备扫描', reconcile: '核对下载状态', recovery: '恢复待处理任务',
  rss: '拉取 RSS 与种子元数据', matching: 'IYUU 匹配与来源查询', target_stats: '更新原站信息',
}[status.value.scan_status?.stage] || '扫描'));
const scanColor = computed(() => ({
  running: 'info', success: 'success', partial: 'warning', failed: 'error', interrupted: 'warning',
}[status.value.scan_status?.state] || 'info'));

function unwrapResponse(response) {
  const result = response && Object.prototype.hasOwnProperty.call(response, 'success') ? response : response?.data ?? response;
  if (result && Object.prototype.hasOwnProperty.call(result, 'success')) {
    if (result.success === false) {
      const err = new Error(result.message || '操作失败');
      err.details = result.data;
      throw err
    }
    return result.data
  }
  return result
}

function notify(text, color = 'success') {
  const method = ['error', 'info', 'warning', 'success'].includes(color) ? color : 'success';
  if (typeof hostToast?.[method] === 'function') hostToast[method](text);
  else if (method === 'error') error.value = text;
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
    selectedCandidates.value[job.target_hash] = chooseCandidate(job, selectedCandidates.value[job.target_hash], appliedFilters.value);
  }
}

function canDownloadSelected(job) {
  return candidateOptions(job).some((candidate) =>
    candidate.candidate_id === selectedCandidates.value[job.target_hash] && canSelect(job, candidate))
}

async function loadStatus() {
  const request = ++statusRequest;
  lastRefresh = Date.now();
  loading.value = true;
  try {
    const data = unwrapResponse(await props.api.get(
      `${pluginBase.value}/status?${statusQuery(activeView.value, page.value, pageSize, appliedFilters.value)}`));
    if (request !== statusRequest) return
    status.value = data || status.value;
    page.value = status.value.pagination?.page || 1;
    error.value = '';
    syncSelections();
  } catch (err) {
    if (request === statusRequest) error.value = err?.message || '加载稀缺保种任务失败';
  } finally {
    if (request === statusRequest) loading.value = false;
  }
}

function selectView(view) {
  activeView.value = view;
  page.value = 1;
  loadStatus();
}

function changePage(value) {
  page.value = value;
  loadStatus();
}

function applyFilters() {
  try {
    appliedFilters.value = normalizeFilters(filterDraft.value);
    selectedCandidates.value = {};
    filterError.value = '';
    page.value = 1;
    loadStatus();
  } catch (err) {
    filterError.value = err.message;
  }
}

function resetFilters() {
  filterDraft.value = {};
  applyFilters();
}

watch(() => props.navKey, (value) => selectView(value === 'history' ? 'history' : 'current'));

async function scanNow() {
  operating.value = 'scan';
  try {
    unwrapResponse(await props.api.post(`${pluginBase.value}/scan`, {}));
    await loadStatus();
    notify('已提交后台扫描，可在进度栏查看结果', 'info');
    emit('action');
  } catch (err) {
    notify(err?.message || 'RSS 扫描失败', 'error');
  } finally {
    operating.value = '';
  }
}

async function runJobAction(job, action, body = {}) {
  operating.value = `${job.target_hash}:${action}`;
  try {
    unwrapResponse(await props.api.post(`${pluginBase.value}/jobs/${job.target_hash}/${action}`, body));
    await loadStatus();
    notify(action === 'download' ? '所选种子已提交下载' : action === 'retry' ? '重新匹配完成' : '任务已忽略');
    emit('action');
  } catch (err) {
    if (action === 'download' && err?.details?.confirmation_required) {
      downloadConfirmation.value = { ...err.details, target_hash: job.target_hash, skip_future_risk_confirmation: false };
    } else {
      notify(err?.message || '操作失败', 'error');
    }
  } finally {
    operating.value = '';
  }
}

function downloadSelected(job) {
  const candidateId = selectedCandidates.value[job.target_hash];
  if (!candidateId) {
    notify('请先选择一个来源种子', 'warning');
    return
  }
  runJobAction(job, 'download', { candidate_id: candidateId });
}

function confirmDownload() {
  const selection = downloadConfirmation.value;
  if (!selection) return
  downloadConfirmation.value = null;
  runJobAction({ target_hash: selection.target_hash }, 'download', {
    candidate_id: selection.candidate_id,
    confirmed_download_factor: selection.promotion === 'non_free' ? selection.download_factor : null,
    confirm_unknown: selection.promotion === 'unknown',
    skip_future_risk_confirmation: selection.skip_future_risk_confirmation === true,
  });
}

function stateMeta(state) {
  const value = stateValues[state] || [state || '未知', 'secondary'];
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
  const bytes = Number(value || 0);
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`
}

function canRetry(job) {
  return !['SOURCE_SUBMITTING', 'SOURCE_DOWNLOADING', 'TARGET_DOWNLOADING', 'WAITING_IYUU', 'TARGET_RECHECKING', 'TARGET_SEEDING', 'TARGET_COMPLETE', 'TARGET_PAUSED', 'TARGET_ERROR'].includes(job.state)
}

function formatTime(value) {
  if (!value) return '尚未记录'
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await loadStatus();
  if (disposed) return
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !operating.value && !loading.value &&
        (scanRunning.value || Date.now() - lastRefresh >= 15000)) loadStatus();
  }, 5000);
});

onUnmounted(() => {
  disposed = true;
  statusRequest += 1;
  if (refreshTimer) window.clearInterval(refreshTimer);
});

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VTab = _resolveComponent("VTab");
  const _component_VTabs = _resolveComponent("VTabs");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VEmptyState = _resolveComponent("VEmptyState");
  const _component_VExpansionPanelTitle = _resolveComponent("VExpansionPanelTitle");
  const _component_VRadio = _resolveComponent("VRadio");
  const _component_VTable = _resolveComponent("VTable");
  const _component_VRadioGroup = _resolveComponent("VRadioGroup");
  const _component_VExpansionPanelText = _resolveComponent("VExpansionPanelText");
  const _component_VExpansionPanel = _resolveComponent("VExpansionPanel");
  const _component_VExpansionPanels = _resolveComponent("VExpansionPanels");
  const _component_VPagination = _resolveComponent("VPagination");
  const _component_VCheckbox = _resolveComponent("VCheckbox");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VDialog = _resolveComponent("VDialog");

  return (_openBlock(), _createElementBlock("div", {
    class: _normalizeClass(["seed-rescue", { 'seed-rescue--compact': __props.compact }])
  }, [
    _createElementVNode("header", _hoisted_1, [
      _createElementVNode("div", null, [
        _createElementVNode("div", _hoisted_2, [
          _createVNode(_component_VIcon, {
            icon: "mdi-seed-outline",
            color: "primary",
            size: "30"
          }),
          _createElementVNode("h1", null, "稀缺保种 · " + _toDisplayString(pageTitle.value), 1)
        ]),
        (activeView.value === 'current')
          ? (_openBlock(), _createElementBlock("p", _hoisted_3, "最新成功拉取的 RSS 中仍在列出的种子，可选择跨站来源或原种直下。"))
          : (_openBlock(), _createElementBlock("p", _hoisted_4, "已移出 RSS 的种子保留在这里，下载进度和保种任务继续跟踪。"))
      ]),
      _createElementVNode("div", _hoisted_5, [
        _createVNode(_component_VBtn, {
          variant: "tonal",
          "prepend-icon": "mdi-refresh",
          loading: loading.value,
          onClick: loadStatus
        }, {
          default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
            _createTextVNode("刷新", -1)
          ]))]),
          _: 1
        }, 8, ["loading"]),
        _createVNode(_component_VBtn, {
          color: "primary",
          "prepend-icon": "mdi-rss",
          loading: operating.value === 'scan' || scanRunning.value,
          disabled: actionBusy.value,
          onClick: scanNow
        }, {
          default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
            _createTextVNode("扫描 RSS", -1)
          ]))]),
          _: 1
        }, 8, ["loading", "disabled"]),
        (__props.showClose)
          ? (_openBlock(), _createBlock(_component_VBtn, {
              key: 0,
              icon: "mdi-close",
              variant: "text",
              onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
            }))
          : _createCommentVNode("", true)
      ])
    ]),
    (status.value.confirm_download_risk === false)
      ? (_openBlock(), _createElementBlock("div", _hoisted_6, " 下载流量风险提醒已关闭，可在插件配置中重新开启“下载前提醒流量风险”。 "))
      : _createCommentVNode("", true),
    (status.value.scan_status?.state && status.value.scan_status.state !== 'idle')
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: scanColor.value,
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            (scanRunning.value)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createTextVNode(" 后台扫描中 · " + _toDisplayString(scanStage.value) + " ", 1),
                  (status.value.scan_status.total)
                    ? (_openBlock(), _createElementBlock("span", _hoisted_7, "（" + _toDisplayString(status.value.scan_status.completed || 0) + " / " + _toDisplayString(status.value.scan_status.total) + "）", 1))
                    : _createCommentVNode("", true),
                  _createVNode(_component_VProgressLinear, {
                    class: "mt-2",
                    color: "primary",
                    indeterminate: !status.value.scan_status.total,
                    "model-value": status.value.scan_status.total ? 100 * (status.value.scan_status.completed || 0) / status.value.scan_status.total : 0
                  }, null, 8, ["indeterminate", "model-value"]),
                  _createElementVNode("div", _hoisted_8, "可继续筛选和浏览；下载、重试、忽略暂时禁用，避免任务冲突。开始于 " + _toDisplayString(formatTime(status.value.scan_status.started_at)), 1)
                ], 64))
              : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                  _createTextVNode(_toDisplayString(status.value.scan_status.message) + " · " + _toDisplayString(formatTime(status.value.scan_status.finished_at)), 1)
                ], 64)),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(status.value.scan_status.issues || [], (issue) => {
              return (_openBlock(), _createElementBlock("div", {
                key: issue,
                class: "text-caption mt-1"
              }, _toDisplayString(issue), 1))
            }), 128))
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    _createVNode(_component_VTabs, {
      "model-value": activeView.value,
      color: "primary",
      class: "mb-4",
      "onUpdate:modelValue": selectView
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VTab, {
          value: "current",
          "prepend-icon": "mdi-rss"
        }, {
          default: _withCtx(() => [
            _cache[13] || (_cache[13] = _createTextVNode("当前 RSS ", -1)),
            _createVNode(_component_VChip, {
              size: "x-small",
              class: "ml-2"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(status.value.summary.current || 0), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VTab, {
          value: "history",
          "prepend-icon": "mdi-history"
        }, {
          default: _withCtx(() => [
            _cache[14] || (_cache[14] = _createTextVNode("历史记录 ", -1)),
            _createVNode(_component_VChip, {
              size: "x-small",
              class: "ml-2"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(status.value.summary.history || 0), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["model-value"]),
    _createVNode(_component_VCard, {
      variant: "outlined",
      class: "mb-4"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardText, null, {
          default: _withCtx(() => [
            _createElementVNode("form", {
              onSubmit: _withModifiers(applyFilters, ["prevent"])
            }, [
              _createVNode(_component_VRow, null, {
                default: _withCtx(() => [
                  _createVNode(_component_VCol, {
                    cols: "12",
                    sm: "6",
                    md: "4"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VSelect, {
                        modelValue: filterDraft.value.state,
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((filterDraft.value.state) = $event)),
                        label: "任务状态",
                        items: _unref(stateOptions),
                        clearable: "",
                        "hide-details": ""
                      }, null, 8, ["modelValue", "items"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCol, {
                    cols: "12",
                    sm: "6",
                    md: "4"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VSelect, {
                        modelValue: filterDraft.value.promotion,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((filterDraft.value.promotion) = $event)),
                        label: "原站促销",
                        clearable: "",
                        "hide-details": "",
                        items: [{ title: '免费', value: 'free' }, { title: '非免费', value: 'non_free' }, { title: '未知', value: 'unknown' }]
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCol, {
                    cols: "12",
                    sm: "6",
                    md: "4"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VSelect, {
                        modelValue: filterDraft.value.source_promotion,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((filterDraft.value.source_promotion) = $event)),
                        label: "跨站促销",
                        clearable: "",
                        "hide-details": "",
                        items: [{ title: '免费', value: 'free' }, { title: '非免费', value: 'non_free' }, { title: '未知', value: 'unknown' }]
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCol, {
                    cols: "12",
                    md: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VSelect, {
                        modelValue: filterDraft.value.source_site_id,
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((filterDraft.value.source_site_id) = $event)),
                        label: "跨站候选站点",
                        items: status.value.filter_options?.source_sites || [],
                        clearable: "",
                        "hide-details": ""
                      }, null, 8, ["modelValue", "items"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCol, {
                    cols: "6",
                    md: "3"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VTextField, {
                        modelValue: filterDraft.value.min_seeders,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((filterDraft.value.min_seeders) = $event)),
                        type: "number",
                        min: "0",
                        step: "1",
                        label: "原站做种人数 ≥",
                        clearable: "",
                        "hide-details": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCol, {
                    cols: "6",
                    md: "3"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VTextField, {
                        modelValue: filterDraft.value.max_seeders,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((filterDraft.value.max_seeders) = $event)),
                        type: "number",
                        min: "0",
                        step: "1",
                        label: "原站做种人数 ≤",
                        clearable: "",
                        "hide-details": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _cache[17] || (_cache[17] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-3" }, "条件留空表示不限；人数范围中的 0 表示零人，未知人数不符合范围条件。切换当前 / 历史保留已应用条件，仅筛选展示，不影响下载规则。", -1)),
              _cache[18] || (_cache[18] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-1" }, "跨站筛选依据已有候选；同时选择站点和促销时，须由同一个跨站候选满足。", -1)),
              (filterError.value)
                ? (_openBlock(), _createBlock(_component_VAlert, {
                    key: 0,
                    type: "error",
                    variant: "tonal",
                    class: "mt-3"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(filterError.value), 1)
                    ]),
                    _: 1
                  }))
                : _createCommentVNode("", true),
              _createElementVNode("div", _hoisted_9, [
                _createVNode(_component_VBtn, {
                  type: "submit",
                  color: "primary",
                  "prepend-icon": "mdi-filter-outline"
                }, {
                  default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                    _createTextVNode("筛选", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: resetFilters
                }, {
                  default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                    _createTextVNode("重置", -1)
                  ]))]),
                  _: 1
                }),
                _createElementVNode("span", _hoisted_10, _toDisplayString(hasFilters.value ? '筛选结果' : '全部记录') + "：" + _toDisplayString(viewSummary.value.total || 0) + " / " + _toDisplayString(status.value.view === activeView.value ? status.value.view_total || 0 : 0) + " 条", 1)
              ])
            ], 32)
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    (error.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 2,
          type: "error",
          variant: "tonal",
          class: "mb-4",
          closable: "",
          "onClick:close": _cache[7] || (_cache[7] = $event => (error.value = ''))
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (!status.value.enabled)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 3,
          type: "warning",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
            _createTextVNode(" 插件当前未启用，请先完成配置。 ", -1)
          ]))]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (status.value.rss_status?.failed_feeds)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 4,
          type: "warning",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(status.value.rss_status.failed_feeds) + " 个 RSS 最近拉取失败，当前列表保留它们上次成功拉取的内容。 ", 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (status.value.summary.unclassified)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 5,
          type: "info",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(status.value.summary.unclassified) + " 条旧记录暂列历史，下一次成功扫描 RSS 后会确认当前归属。 ", 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_11, " 最近成功拉取：" + _toDisplayString(formatTime(status.value.rss_status?.last_success_at)), 1),
    _createElementVNode("section", _hoisted_12, [
      _createVNode(_component_VCard, { variant: "tonal" }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              _createElementVNode("strong", null, _toDisplayString(viewSummary.value.total || 0), 1),
              _createElementVNode("span", null, _toDisplayString(hasFilters.value ? '筛选结果' : activeView.value === 'current' ? '当前 RSS 种子' : '历史记录'), 1)
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, { variant: "tonal" }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              _createElementVNode("strong", null, _toDisplayString(viewSummary.value.awaiting_selection || 0), 1),
              _cache[20] || (_cache[20] = _createElementVNode("span", null, "等待选择", -1))
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, { variant: "tonal" }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              _createElementVNode("strong", null, _toDisplayString(viewSummary.value.downloading || 0), 1),
              _cache[21] || (_cache[21] = _createElementVNode("span", null, "正在下载", -1))
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, { variant: "tonal" }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              _createElementVNode("strong", null, _toDisplayString(viewSummary.value.target_seeding || 0), 1),
              _cache[22] || (_cache[22] = _createElementVNode("span", null, "保种成功", -1))
            ]),
            _: 1
          })
        ]),
        _: 1
      })
    ]),
    (loading.value)
      ? (_openBlock(), _createBlock(_component_VProgressLinear, {
          key: 6,
          indeterminate: "",
          color: "primary",
          class: "mb-3"
        }))
      : _createCommentVNode("", true),
    (!jobs.value.length && !loading.value)
      ? (_openBlock(), _createBlock(_component_VEmptyState, {
          key: 7,
          icon: "mdi-rss-off",
          title: hasFilters.value ? '没有符合筛选条件的记录' : activeView.value === 'current' ? '当前 RSS 暂无种子记录' : '暂无历史 RSS 记录',
          text: hasFilters.value ? '请调整条件或点击“重置”查看本列表全部记录。' : activeView.value === 'current' ? '点击“扫描 RSS”拉取最新列表；以往记录可在历史页查看。' : '种子移出 RSS 后会在这里保留，供查看和继续操作。'
        }, null, 8, ["title", "text"]))
      : (_openBlock(), _createBlock(_component_VExpansionPanels, {
          key: `${activeView.value}:${page.value}`,
          multiple: "",
          variant: "accordion",
          class: "seed-rescue__jobs"
        }, {
          default: _withCtx(() => [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(jobs.value, (job) => {
              return (_openBlock(), _createBlock(_component_VExpansionPanel, {
                key: job.target_hash
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VExpansionPanelTitle, null, {
                    default: _withCtx(() => [
                      _createElementVNode("div", _hoisted_13, [
                        _createElementVNode("span", null, _toDisplayString(job.title), 1),
                        _createVNode(_component_VChip, {
                          color: stateMeta(job.state).color,
                          size: "small",
                          variant: "tonal"
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(stateMeta(job.state).text), 1)
                          ]),
                          _: 2
                        }, 1032, ["color"]),
                        (job.candidates?.length)
                          ? (_openBlock(), _createElementBlock("span", _hoisted_14, _toDisplayString(job.candidates.length) + " 个跨站来源 · " + _toDisplayString(job.candidates.filter(candidate => candidate.eligible !== false).length) + " 个通过下载规则", 1))
                          : (matchedProbeCount(job))
                            ? (_openBlock(), _createElementBlock("span", _hoisted_15, _toDisplayString(matchedProbeCount(job)) + " 个已匹配（被筛选） ", 1))
                            : _createCommentVNode("", true)
                      ])
                    ]),
                    _: 2
                  }, 1024),
                  _createVNode(_component_VExpansionPanelText, null, {
                    default: _withCtx(() => [
                      _createElementVNode("div", _hoisted_16, [
                        _createTextVNode(" 首次发现：" + _toDisplayString(formatTime(job.created_at)) + " · 最近 RSS 出现：" + _toDisplayString(formatTime(job.rss_last_seen_at)) + " ", 1),
                        (job.rss_archived_at)
                          ? (_openBlock(), _createElementBlock("span", _hoisted_17, " · 移入历史：" + _toDisplayString(formatTime(job.rss_archived_at)), 1))
                          : (job.rss_current === undefined)
                            ? (_openBlock(), _createElementBlock("span", _hoisted_18, " · 等待 RSS 扫描确认"))
                            : _createCommentVNode("", true)
                      ]),
                      _createVNode(_component_VCard, {
                        variant: "tonal",
                        class: "seed-rescue__target mb-3"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VCardText, { class: "d-flex align-center flex-wrap ga-2" }, {
                            default: _withCtx(() => [
                              (job.target_page_url)
                                ? (_openBlock(), _createBlock(_component_VBtn, {
                                    key: 0,
                                    href: job.target_page_url,
                                    target: "_blank",
                                    rel: "noopener noreferrer",
                                    variant: "text",
                                    size: "small",
                                    "prepend-icon": "mdi-open-in-new"
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(job.target_site_name || '目标站详情'), 1)
                                    ]),
                                    _: 2
                                  }, 1032, ["href"]))
                                : (_openBlock(), _createElementBlock("span", _hoisted_19, _toDisplayString(job.target_site_name || '目标站'), 1)),
                              _createVNode(_component_VChip, {
                                size: "small",
                                color: "success",
                                variant: "tonal"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode("做种 " + _toDisplayString(job.target_seeders ?? '未知'), 1)
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_VChip, {
                                size: "small",
                                color: "info",
                                variant: "tonal"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode("下载 " + _toDisplayString(job.target_peers ?? '未知'), 1)
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_VChip, {
                                size: "small",
                                variant: "tonal"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode("完成 " + _toDisplayString(job.target_grabs ?? '未知'), 1)
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_VChip, {
                                size: "small",
                                variant: "tonal"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode("大小 " + _toDisplayString(formatBytes(job.target_size)), 1)
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1024)
                        ]),
                        _: 2
                      }, 1024),
                      (job.reason)
                        ? (_openBlock(), _createBlock(_component_VAlert, {
                            key: 0,
                            type: "info",
                            variant: "tonal",
                            density: "compact",
                            class: "mb-3"
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(job.reason) + " ", 1),
                              (job.next_retry_at)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_20, "连续失败 " + _toDisplayString(job.retry_count || 0) + " 次；" + _toDisplayString(formatTime(job.next_retry_at)) + " 后的扫描可自动重试。", 1))
                                : _createCommentVNode("", true)
                            ]),
                            _: 2
                          }, 1024))
                        : _createCommentVNode("", true),
                      (candidateOptions(job).length)
                        ? (_openBlock(), _createBlock(_component_VRadioGroup, {
                            key: 1,
                            modelValue: selectedCandidates.value[job.target_hash],
                            "onUpdate:modelValue": $event => ((selectedCandidates.value[job.target_hash]) = $event),
                            "hide-details": ""
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_VTable, {
                                density: "comfortable",
                                class: "seed-rescue__table"
                              }, {
                                default: _withCtx(() => [
                                  _cache[27] || (_cache[27] = _createElementVNode("thead", null, [
                                    _createElementVNode("tr", null, [
                                      _createElementVNode("th"),
                                      _createElementVNode("th", null, "来源站"),
                                      _createElementVNode("th", null, "做种"),
                                      _createElementVNode("th", null, "下载"),
                                      _createElementVNode("th", null, "完成"),
                                      _createElementVNode("th", null, "大小"),
                                      _createElementVNode("th", null, "促销"),
                                      _createElementVNode("th")
                                    ])
                                  ], -1)),
                                  _createElementVNode("tbody", null, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(candidateOptions(job), (candidate) => {
                                      return (_openBlock(), _createElementBlock("tr", {
                                        key: candidate.candidate_id,
                                        class: _normalizeClass({ 'seed-rescue__matched': hasSourceFilters.value && matchesFilters(candidate) })
                                      }, [
                                        _createElementVNode("td", null, [
                                          _createVNode(_component_VRadio, {
                                            value: candidate.candidate_id,
                                            disabled: !canSelect(job, candidate) || actionBusy.value
                                          }, null, 8, ["value", "disabled"])
                                        ]),
                                        _createElementVNode("td", null, [
                                          (candidate.page_url)
                                            ? (_openBlock(), _createElementBlock("a", {
                                                key: 0,
                                                href: candidate.page_url,
                                                target: "_blank",
                                                rel: "noopener noreferrer",
                                                class: "seed-rescue__link",
                                                title: candidate.title || candidate.site_name
                                              }, [
                                                _createTextVNode(_toDisplayString(candidate.site_name) + " ", 1),
                                                _createVNode(_component_VIcon, {
                                                  icon: "mdi-open-in-new",
                                                  size: "x-small"
                                                })
                                              ], 8, _hoisted_21))
                                            : (_openBlock(), _createElementBlock("span", _hoisted_22, _toDisplayString(candidate.site_name), 1)),
                                          (candidate.is_target)
                                            ? (_openBlock(), _createElementBlock("span", _hoisted_23, "保种站点"))
                                            : (_openBlock(), _createElementBlock("div", _hoisted_24, " ID " + _toDisplayString(candidate.torrent_id) + " · " + _toDisplayString(candidate.metadata_status === 'unavailable' ? 'IYUU 已收录 · 详情未获取' : candidate.lookup_method === 'detail' ? '按 ID 查详情' : candidate.lookup_method === 'search' ? '搜索补全' : 'IYUU 同源'), 1))
                                        ]),
                                        _createElementVNode("td", null, [
                                          _createElementVNode("strong", null, _toDisplayString(candidate.seeders ?? '未知'), 1)
                                        ]),
                                        _createElementVNode("td", null, _toDisplayString(candidate.leechers ?? '-'), 1),
                                        _createElementVNode("td", null, _toDisplayString(candidate.grabs ?? '-'), 1),
                                        _createElementVNode("td", null, _toDisplayString(formatBytes(candidate.size)), 1),
                                        _createElementVNode("td", null, [
                                          _createVNode(_component_VChip, {
                                            size: "x-small",
                                            color: candidate.promotion === 'free' ? 'success' : 'default'
                                          }, {
                                            default: _withCtx(() => [
                                              _createTextVNode(_toDisplayString(promotionText(candidate)), 1)
                                            ]),
                                            _: 2
                                          }, 1032, ["color"]),
                                          (candidate.is_target && candidate.promotion_updated_at)
                                            ? (_openBlock(), _createElementBlock("div", _hoisted_25, " 最近确认：" + _toDisplayString(formatTime(candidate.promotion_updated_at)), 1))
                                            : _createCommentVNode("", true),
                                          (candidate.promotion_note)
                                            ? (_openBlock(), _createElementBlock("div", _hoisted_26, _toDisplayString(candidate.promotion_note), 1))
                                            : _createCommentVNode("", true)
                                        ]),
                                        _createElementVNode("td", null, [
                                          (candidate.is_target)
                                            ? (_openBlock(), _createBlock(_component_VChip, {
                                                key: 0,
                                                size: "x-small",
                                                color: "info",
                                                variant: "tonal"
                                              }, {
                                                default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                                                  _createTextVNode("原种直下", -1)
                                                ]))]),
                                                _: 1
                                              }))
                                            : (candidate.eligible === false)
                                              ? (_openBlock(), _createBlock(_component_VChip, {
                                                  key: 1,
                                                  size: "x-small",
                                                  color: "warning",
                                                  variant: "tonal"
                                                }, {
                                                  default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                                                    _createTextVNode("不可下载", -1)
                                                  ]))]),
                                                  _: 1
                                                }))
                                              : (candidate.candidate_id === recommendedId(job))
                                                ? (_openBlock(), _createBlock(_component_VChip, {
                                                    key: 2,
                                                    size: "x-small",
                                                    color: "primary",
                                                    variant: "tonal"
                                                  }, {
                                                    default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                                                      _createTextVNode("推荐", -1)
                                                    ]))]),
                                                    _: 1
                                                  }))
                                                : _createCommentVNode("", true),
                                          (hasSourceFilters.value && matchesFilters(candidate))
                                            ? (_openBlock(), _createBlock(_component_VChip, {
                                                key: 3,
                                                size: "x-small",
                                                color: "success",
                                                variant: "tonal",
                                                class: "ml-1"
                                              }, {
                                                default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                                                  _createTextVNode("符合页面筛选", -1)
                                                ]))]),
                                                _: 1
                                              }))
                                            : _createCommentVNode("", true),
                                          (candidate.exclusion_reason)
                                            ? (_openBlock(), _createElementBlock("div", _hoisted_27, _toDisplayString(candidate.exclusion_reason), 1))
                                            : _createCommentVNode("", true)
                                        ])
                                      ], 2))
                                    }), 128))
                                  ])
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1032, ["modelValue", "onUpdate:modelValue"]))
                        : _createCommentVNode("", true),
                      (job.target_candidate?.selectable)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_28, " 保种站点原种可手动下载，不受跨站来源的做种人数和促销筛选限制；实际速度取决于原站做种情况，下载计费以站点为准。 "))
                        : _createCommentVNode("", true),
                      (unmatchedProbes(job).length)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_29, [
                            _cache[28] || (_cache[28] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, "尚未命中的来源（不代表站点没有资源）", -1)),
                            _createElementVNode("div", _hoisted_30, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(unmatchedProbes(job), (probe, index) => {
                                return (_openBlock(), _createBlock(_component_VChip, {
                                  key: `${probe.site_id}-${index}`,
                                  size: "small",
                                  color: probe.matched ? 'warning' : 'secondary',
                                  variant: "tonal",
                                  href: probe.page_url || undefined,
                                  target: probe.page_url ? '_blank' : undefined,
                                  rel: probe.page_url ? 'noopener noreferrer' : undefined
                                }, {
                                  default: _withCtx(() => [
                                    _createTextVNode(_toDisplayString(probe.site_name) + " · " + _toDisplayString(probe.error || (probe.search_limited ? '已达分页上限，未命中' : '已查范围内未命中')), 1)
                                  ]),
                                  _: 2
                                }, 1032, ["color", "href", "target", "rel"]))
                              }), 128))
                            ])
                          ]))
                        : _createCommentVNode("", true),
                      (job.source_site_name)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_31, " 已选来源：" + _toDisplayString(job.source_site_name) + " · " + _toDisplayString(job.source_seeders ?? '未知') + " 人做种 ", 1))
                        : _createCommentVNode("", true),
                      _createElementVNode("div", _hoisted_32, [
                        (canDownloadSelected(job))
                          ? (_openBlock(), _createBlock(_component_VBtn, {
                              key: 0,
                              color: "primary",
                              "prepend-icon": "mdi-download",
                              loading: operating.value === `${job.target_hash}:download`,
                              disabled: actionBusy.value,
                              onClick: $event => (downloadSelected(job))
                            }, {
                              default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                                _createTextVNode("下载所选种子", -1)
                              ]))]),
                              _: 1
                            }, 8, ["loading", "disabled", "onClick"]))
                          : _createCommentVNode("", true),
                        (canRetry(job))
                          ? (_openBlock(), _createBlock(_component_VBtn, {
                              key: 1,
                              variant: "tonal",
                              "prepend-icon": "mdi-refresh",
                              loading: operating.value === `${job.target_hash}:retry`,
                              disabled: actionBusy.value,
                              onClick: $event => (runJobAction(job, 'retry'))
                            }, {
                              default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
                                _createTextVNode("重新匹配", -1)
                              ]))]),
                              _: 1
                            }, 8, ["loading", "disabled", "onClick"]))
                          : _createCommentVNode("", true),
                        (canRetry(job) && job.state !== 'IGNORED')
                          ? (_openBlock(), _createBlock(_component_VBtn, {
                              key: 2,
                              variant: "text",
                              color: "secondary",
                              disabled: actionBusy.value,
                              onClick: $event => (runJobAction(job, 'ignore'))
                            }, {
                              default: _withCtx(() => [...(_cache[31] || (_cache[31] = [
                                _createTextVNode("忽略", -1)
                              ]))]),
                              _: 1
                            }, 8, ["disabled", "onClick"]))
                          : _createCommentVNode("", true)
                      ])
                    ]),
                    _: 2
                  }, 1024)
                ]),
                _: 2
              }, 1024))
            }), 128))
          ]),
          _: 1
        })),
    (status.value.pagination?.pages > 1 && status.value.view === activeView.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_33, [
          _createElementVNode("div", _hoisted_34, "共 " + _toDisplayString(status.value.pagination.total) + " 条，每页 " + _toDisplayString(pageSize) + " 条", 1),
          _createVNode(_component_VPagination, {
            "model-value": page.value,
            length: status.value.pagination.pages,
            "total-visible": 5,
            disabled: loading.value,
            "onUpdate:modelValue": changePage
          }, null, 8, ["model-value", "length", "disabled"])
        ]))
      : _createCommentVNode("", true),
    _createVNode(_component_VDialog, {
      "model-value": Boolean(downloadConfirmation.value),
      "max-width": "520",
      "onUpdate:modelValue": _cache[10] || (_cache[10] = value => { if (!value) downloadConfirmation.value = null; })
    }, {
      default: _withCtx(() => [
        (downloadConfirmation.value)
          ? (_openBlock(), _createBlock(_component_VCard, {
              key: 0,
              title: "确认下载流量风险"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VCardText, null, {
                  default: _withCtx(() => [
                    _createElementVNode("div", null, _toDisplayString(downloadConfirmation.value.title), 1),
                    _createElementVNode("div", _hoisted_35, "所选站点：" + _toDisplayString(downloadConfirmation.value.site_name), 1),
                    _createVNode(_component_VAlert, {
                      type: "warning",
                      variant: "tonal",
                      class: "mt-3"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(" 服务端刚确认的促销：" + _toDisplayString(promotionText(downloadConfirmation.value)) + "。 此次下载可能计入站点下载量，以站点规则为准。确认后会再次检查，促销变化时需要重新确认。 ", 1)
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCheckbox, {
                      modelValue: downloadConfirmation.value.skip_future_risk_confirmation,
                      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((downloadConfirmation.value.skip_future_risk_confirmation) = $event)),
                      label: "后续不再提示下载流量风险",
                      color: "warning",
                      "hide-details": ""
                    }, null, 8, ["modelValue"]),
                    _cache[32] || (_cache[32] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 确认下载后保存，对本插件所有手动下载生效（含原站、跨站及促销未知）；可在插件配置中重新开启。 ", -1))
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCardActions, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_VSpacer),
                    _createVNode(_component_VBtn, {
                      variant: "text",
                      onClick: _cache[9] || (_cache[9] = $event => (downloadConfirmation.value = null))
                    }, {
                      default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
                        _createTextVNode("取消", -1)
                      ]))]),
                      _: 1
                    }),
                    _createVNode(_component_VBtn, {
                      color: "warning",
                      disabled: actionBusy.value,
                      onClick: confirmDownload
                    }, {
                      default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                        _createTextVNode("确认下载", -1)
                      ]))]),
                      _: 1
                    }, 8, ["disabled"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }))
          : _createCommentVNode("", true)
      ]),
      _: 1
    }, 8, ["model-value"])
  ], 2))
}
}

};
const SeedRescueWorkbench = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-5282e836"]]);

export { SeedRescueWorkbench as S };

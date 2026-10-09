import { importShared } from './__federation_fn_import-JrT3xvdd.js';

function optionalLimit(value, label) {
  if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) return null
  const number = Number(value);
  if (!['number', 'string'].includes(typeof value) || !Number.isSafeInteger(number) || number < 0) {
    throw new Error(`${label}请填写非负整数，留空或 0 表示不限制`)
  }
  return number === 0 ? null : number
}

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,createElementVNode:_createElementVNode,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "seed-rescue-config pa-4" };
const _hoisted_2 = { class: "d-flex justify-end ga-2 mt-4" };

const {onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close', 'switch', 'layout'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;
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
});
const options = ref({ sites: [], downloaders: [] });
const error = ref('');

function unwrapResponse(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'success')) {
    if (response.success === false) throw new Error(response.message || '操作失败')
    return response.data
  }
  return response?.data ?? response
}

async function loadOptions() {
  try {
    const data = unwrapResponse(await props.api.get('plugin/SeedRescue/status'));
    options.value = data?.options || options.value;
  } catch (err) {
    error.value = err?.message || '加载站点和下载器失败';
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
    };
    error.value = '';
    emit('save', payload);
  } catch (err) {
    error.value = err.message;
  }
}

onMounted(() => {
  emit('layout', { maxWidth: '72rem' });
  loadOptions();
});

return (_ctx, _cache) => {
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VTextarea = _resolveComponent("VTextarea");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VBtn = _resolveComponent("VBtn");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (error.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 0,
          type: "error",
          variant: "tonal",
          class: "mb-4",
          closable: "",
          "onClick:close": _cache[0] || (_cache[0] = $event => (error.value = ''))
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_VRow, null, {
      default: _withCtx(() => [
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSwitch, {
              modelValue: form.value.enabled,
              "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((form.value.enabled) = $event)),
              label: "启用插件",
              color: "primary"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSwitch, {
              modelValue: form.value.notify,
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((form.value.notify) = $event)),
              label: "发送通知",
              color: "primary"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSwitch, {
              modelValue: form.value.onlyonce,
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((form.value.onlyonce) = $event)),
              label: "保存后立即扫描一次",
              color: "primary"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VSwitch, {
              modelValue: form.value.confirm_download_risk,
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((form.value.confirm_download_risk) = $event)),
              label: "下载前提醒流量风险",
              color: "primary",
              hint: "默认开启。关闭后，手动下载非免费或促销未知的原站、跨站种子不再弹窗；仍按站点规则计算下载量。",
              "persistent-hint": ""
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSelect, {
              modelValue: form.value.selection_mode,
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((form.value.selection_mode) = $event)),
              label: "来源选择模式",
              items: [
            { title: '手动选择', value: 'manual' },
            { title: '自动选择', value: 'auto' },
            { title: '仅一个候选时自动', value: 'hybrid' },
          ]
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: form.value.cron,
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.value.cron) = $event)),
              label: "扫描 CRON"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: form.value.token,
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.value.token) = $event)),
              label: "IYUU Token",
              type: "password"
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
              modelValue: form.value.target_site_id,
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((form.value.target_site_id) = $event)),
              label: "需要保种的目标站点",
              items: options.value.sites
            }, null, 8, ["modelValue", "items"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "6"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSelect, {
              modelValue: form.value.downloader,
              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((form.value.downloader) = $event)),
              label: "qBittorrent 下载器",
              items: options.value.downloaders
            }, null, 8, ["modelValue", "items"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextarea, {
              modelValue: form.value.rss_urls,
              "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((form.value.rss_urls) = $event)),
              label: "目标站 RSS（每行一个）",
              rows: "3"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, { cols: "12" }, {
          default: _withCtx(() => [
            _createVNode(_component_VSelect, {
              modelValue: form.value.source_site_ids,
              "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((form.value.source_site_ids) = $event)),
              label: "允许的来源站点",
              items: options.value.sites,
              multiple: "",
              chips: "",
              "closable-chips": ""
            }, null, 8, ["modelValue", "items"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: form.value.minimum_seeders,
              "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((form.value.minimum_seeders) = $event)),
              type: "number",
              min: "0",
              step: "1",
              label: "最少做种人数",
              clearable: "",
              hint: "留空或 0 表示不限制做种人数",
              "persistent-hint": ""
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSelect, {
              modelValue: form.value.allowed_promotions,
              "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((form.value.allowed_promotions) = $event)),
              label: "允许的促销",
              items: [{ title: '免费', value: 'free' }, { title: '非免费', value: 'non_free' }],
              multiple: "",
              chips: ""
            }, null, 8, ["modelValue"]),
            _cache[18] || (_cache[18] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-n3" }, " 跨站来源在手动模式下也遵守筛选；保种站点的原种可在工作台单独选择直下，不受此筛选限制。 ", -1))
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: form.value.max_download_count,
              "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((form.value.max_download_count) = $event)),
              type: "number",
              min: "0",
              step: "1",
              label: "同时下载数",
              clearable: "",
              hint: "留空或 0 表示不限制同时下载数",
              "persistent-hint": ""
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "8"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: form.value.save_path,
              "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((form.value.save_path) = $event)),
              label: "来源下载目录"
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          md: "4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VTextField, {
              modelValue: form.value.initial_limit,
              "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((form.value.initial_limit) = $event)),
              type: "number",
              min: "0",
              step: "1",
              label: "每个 RSS 单次处理上限",
              clearable: "",
              hint: "留空或 0 表示处理全部；原站信息补查也不限制条数，并发限速仍保留",
              "persistent-hint": ""
            }, null, 8, ["modelValue"])
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_2, [
      _createVNode(_component_VBtn, {
        variant: "text",
        onClick: _cache[17] || (_cache[17] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
          _createTextVNode("取消", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_VBtn, {
        color: "primary",
        variant: "flat",
        onClick: saveConfig
      }, {
        default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
          _createTextVNode("保存", -1)
        ]))]),
        _: 1
      })
    ])
  ]))
}
}

};

export { _sfc_main as default };

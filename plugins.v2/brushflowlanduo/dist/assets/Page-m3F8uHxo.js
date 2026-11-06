import { a as __mf_19, b as __mf_9 } from './_plugin-vue_export-helper-1_Y3tC5L.js';
import { B as BrushFlowWorkbench } from './BrushFlowWorkbench-Bmyw-FFf.js';

const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
},
  emits: ['action', 'close'],
  setup(__props) {





return (_ctx, _cache) => {
  return (__mf_19(), __mf_9(BrushFlowWorkbench, {
    api: __props.api,
    "plugin-id": "BrushFlowLanduo",
    "show-close": "",
    compact: "",
    onAction: _cache[0] || (_cache[0] = $event => (_ctx.$emit('action'))),
    onClose: _cache[1] || (_cache[1] = $event => (_ctx.$emit('close')))
  }, null, 8, ["api"]))
}
}

};

export { _sfc_main as default };

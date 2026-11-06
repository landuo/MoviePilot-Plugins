import { c as __mf_17, a as __mf_19, b as __mf_9 } from './_plugin-vue_export-helper-1_Y3tC5L.js';
import { B as BrushFlowWorkbench } from './BrushFlowWorkbench-Bmyw-FFf.js';

const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
},
  emits: ['layout', 'close'],
  setup(__props, { emit: __emit }) {



const emit = __emit;

__mf_17(() => {
  emit('layout', { maxWidth: '80rem' });
});

return (_ctx, _cache) => {
  return (__mf_19(), __mf_9(BrushFlowWorkbench, {
    api: __props.api,
    "plugin-id": "BrushFlowLanduo",
    "initial-tab": "config",
    "show-close": "",
    compact: "",
    onClose: _cache[0] || (_cache[0] = $event => (_ctx.$emit('close')))
  }, null, 8, ["api"]))
}
}

};

export { _sfc_main as default };

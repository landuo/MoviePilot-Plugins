<script setup>
import SeedRescueWorkbench from './SeedRescueWorkbench.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
})

defineEmits(['action', 'close'])
</script>

<template>
  <SeedRescueWorkbench
    :api="api"
    plugin-id="SeedRescue"
    show-close
    compact
    @action="$emit('action')"
    @close="$emit('close')"
  />
</template>

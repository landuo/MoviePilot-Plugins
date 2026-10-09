<script setup>
import SeedRescueWorkbench from './SeedRescueWorkbench.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
  navKey: { type: String, default: 'main' },
  pluginId: { type: String, default: 'SeedRescue' },
})

defineEmits(['action'])
</script>

<template>
  <SeedRescueWorkbench :api="api" :plugin-id="pluginId" :nav-key="navKey" @action="$emit('action')" />
</template>

<script setup>
defineProps({
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
})
</script>

<template>
  <VCard variant="tonal">
    <VCardTitle>稀缺保种</VCardTitle>
    <VCardText>选择跨站来源下载后辅种，或直接下载保种站点原种。</VCardText>
  </VCard>
</template>

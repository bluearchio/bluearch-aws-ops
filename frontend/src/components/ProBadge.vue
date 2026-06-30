<template>
  <slot />
</template>

<script setup lang="ts">
defineProps<{
  feature: string
  label?: string
  requiredTier?: string
}>()
</script>

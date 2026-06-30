<template>
  <router-link v-if="resourceId" :to="`/resources/${resourceId}`" class="resource-link">
    <i class="pi pi-box"></i>
    <span class="resource-label">{{ label }}</span>
  </router-link>
  <span v-else class="resource-link-plain">{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  resourceId?: string
  arn?: string
  label?: string
}>()

const label = computed(() => {
  if (props.label) return props.label
  if (props.arn) {
    const parts = props.arn.split('/')
    return parts[parts.length - 1] || props.arn
  }
  return props.resourceId || 'Unknown'
})
</script>

<style scoped>
.resource-link {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: #5a9aff;
  text-decoration: none;
  font-size: 0.82rem;
  transition: color 0.15s;
}
.resource-link:hover { color: #3b82f6; text-decoration: underline; }
.resource-link i { font-size: 0.75rem; }
.resource-link-plain { color: var(--text-color-secondary); font-size: 0.82rem; }
</style>

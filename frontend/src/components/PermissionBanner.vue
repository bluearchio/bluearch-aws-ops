<template>
  <div class="permission-banner" :class="bannerClass">
    <i class="pi banner-icon" :class="iconClass"></i>
    <div class="banner-content">
      <strong>{{ title }}</strong>
      <span>{{ message }}</span>
      <span v-if="detail" class="banner-detail">{{ detail }}</span>
    </div>
    <router-link to="/setup" class="banner-link">View Setup</router-link>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  type: 'partial' | 'unavailable'
  message: string
  detail?: string
}>()

const bannerClass = computed(() => ({
  'banner-partial': props.type === 'partial',
  'banner-unavailable': props.type === 'unavailable',
}))

const iconClass = computed(() => {
  return props.type === 'partial' ? 'pi-exclamation-triangle' : 'pi-times-circle'
})

const title = computed(() => {
  return props.type === 'partial' ? 'Limited Permissions' : 'Feature Unavailable'
})
</script>

<style scoped>
.permission-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.banner-partial {
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.25);
  color: var(--color-warning);
}

.banner-unavailable {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: var(--color-danger);
}

.banner-icon {
  font-size: 1rem;
  flex-shrink: 0;
}

.banner-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.banner-content strong {
  font-size: 0.85rem;
}

.banner-content span {
  font-size: 0.8rem;
  opacity: 0.85;
}

.banner-detail {
  font-size: 0.75rem;
  opacity: 0.7;
  font-style: italic;
}

.banner-link {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--accent-cyan);
  text-decoration: none;
  white-space: nowrap;
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
  border: 1px solid rgba(25, 212, 212, 0.2);
  transition: all 0.2s;
}

.banner-link:hover {
  background: rgba(25, 212, 212, 0.1);
  border-color: rgba(25, 212, 212, 0.4);
}
</style>

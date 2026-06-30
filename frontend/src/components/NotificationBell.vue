<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { NotificationEvent } from '@/types/api'

const open = ref(false)
const loading = ref(false)
const error = ref('')
const notifications = ref<NotificationEvent[]>([])
const root = ref<HTMLElement | null>(null)

const visibleNotifications = computed(() => notifications.value.slice(0, 8))
const hasNotifications = computed(() => notifications.value.length > 0)

function setupLink(notification: NotificationEvent): string {
  const value = notification.payload?.setup_url || notification.payload?.setup_link
  if (typeof value === 'string' && value) return value
  const templates = notification.payload?.templates
  if (Array.isArray(templates)) {
    for (const template of templates) {
      if (
        template
        && typeof template === 'object'
        && 'setup_path' in template
        && typeof template.setup_path === 'string'
      ) {
        return template.setup_path
      }
    }
  }
  return '/setup'
}

async function load(refresh = false) {
  if (loading.value) return
  if (!refresh && notifications.value.length > 0) return
  loading.value = true
  error.value = ''
  try {
    notifications.value = await api.notifications({ limit: 20, refresh })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to load notifications'
  } finally {
    loading.value = false
  }
}

async function toggle() {
  open.value = !open.value
  if (open.value) await load(true)
}

function closeOnOutsideClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) {
    open.value = false
  }
}

onMounted(() => {
  load(false)
  document.addEventListener('click', closeOnOutsideClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeOnOutsideClick)
})
</script>

<template>
  <div ref="root" class="notification-bell">
    <button class="notification-trigger" title="Notifications" @click.stop="toggle">
      <i class="pi pi-bell"></i>
      <span v-if="hasNotifications" class="notification-count">{{ notifications.length }}</span>
    </button>
    <div v-if="open" class="notification-menu">
      <div class="notification-menu__header">
        <span>Notifications</span>
        <button title="Refresh notifications" @click="load(true)">
          <i class="pi pi-refresh" :class="{ 'pi-spin': loading }"></i>
        </button>
      </div>
      <div v-if="error" class="notification-empty notification-empty--error">{{ error }}</div>
      <div v-else-if="loading && !notifications.length" class="notification-empty">Loading...</div>
      <div v-else-if="!notifications.length" class="notification-empty">
        No notifications yet. CloudFormation template warnings appear here.
      </div>
      <template v-else>
        <a
          v-for="notification in visibleNotifications"
          :key="notification.id"
          class="notification-item"
          :href="setupLink(notification)"
        >
          <span class="notification-item__severity">{{ notification.severity }}</span>
          <strong>{{ notification.title }}</strong>
          <span v-if="notification.message">{{ notification.message }}</span>
        </a>
      </template>
    </div>
  </div>
</template>

<style scoped>
.notification-bell {
  position: relative;
}

.notification-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
  color: var(--text-color);
  cursor: pointer;
}

.notification-trigger:hover {
  border-color: rgba(32, 108, 245, 0.45);
  background: var(--surface-card-hover);
}

.notification-count {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--color-warning);
  color: #0a0a0a;
  font: 700 0.68rem var(--font-mono);
  line-height: 18px;
}

.notification-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: min(360px, calc(100vw - 2rem));
  max-height: 420px;
  overflow: auto;
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  background: var(--surface-card);
  box-shadow: var(--glow-blue), 0 10px 24px rgba(0, 0, 0, 0.45);
  z-index: 120;
}

.notification-menu__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 0.9rem;
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color);
  font-family: var(--font-heading);
  font-size: 0.78rem;
  text-transform: uppercase;
}

.notification-menu__header button {
  border: 0;
  background: transparent;
  color: var(--text-color-secondary);
  cursor: pointer;
}

.notification-empty {
  padding: 1rem;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.notification-empty--error {
  color: var(--color-danger);
}

.notification-item {
  display: grid;
  gap: 0.25rem;
  padding: 0.85rem 0.95rem;
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color);
  text-decoration: none;
}

.notification-item:hover {
  background: rgba(32, 108, 245, 0.08);
}

.notification-item__severity {
  color: var(--color-warning);
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
}

.notification-item span:last-child {
  color: var(--text-color-secondary);
  font-size: 0.82rem;
  line-height: 1.35;
}
</style>

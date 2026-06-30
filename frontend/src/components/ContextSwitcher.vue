<template>
  <div class="context-switcher" ref="switcherRef">
    <button class="context-trigger" @click="open = !open" :disabled="contextStore.loading">
      <i class="pi pi-building"></i>
      <span class="context-label">{{ contextStore.currentLabel }}</span>
      <i class="pi pi-chevron-down trigger-chevron"></i>
    </button>
    <div v-if="open" class="context-dropdown">
      <div class="dropdown-header">Account Context</div>
      <div class="dropdown-divider"></div>
      <button
        v-for="ctx in contextStore.all"
        :key="ctx.account_id"
        class="dropdown-item"
        :class="{ current: ctx.is_current }"
        @click="handleSwitch(ctx.account_id!)"
        :disabled="ctx.is_current"
      >
        <div class="ctx-info">
          <span class="ctx-alias">{{ ctx.account_alias || ctx.account_id }}</span>
          <span v-if="ctx.account_alias" class="ctx-id">{{ ctx.account_id }}</span>
        </div>
        <i v-if="ctx.is_current" class="pi pi-check ctx-check"></i>
      </button>
      <div v-if="contextStore.all.length === 0" class="dropdown-empty">
        No accounts registered
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useContextStore } from '@/stores/context'

const contextStore = useContextStore()
const open = ref(false)
const switcherRef = ref<HTMLElement | null>(null)

function handleSwitch(accountId: string) {
  open.value = false
  contextStore.switchTo(accountId)
}

function onClickOutside(e: MouseEvent) {
  if (switcherRef.value && !switcherRef.value.contains(e.target as Node)) {
    open.value = false
  }
}

async function loadContextsIfNeeded() {
  if (contextStore.loading || contextStore.current || contextStore.all.length > 0) return
  await Promise.all([
    contextStore.loadCurrent({ background: true }),
    contextStore.loadAll({ background: true }),
  ])
}

onMounted(() => {
  void loadContextsIfNeeded()
  document.addEventListener('click', onClickOutside)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
})
</script>

<style scoped>
.context-switcher {
  position: relative;
}

.context-trigger {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.65rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
  cursor: pointer;
  font-size: 0.82rem;
  color: var(--text-color);
  transition: all 0.2s;
  font-family: var(--font-body);
}

.context-trigger:hover:not(:disabled) {
  border-color: rgba(32, 108, 245, 0.3);
}

.context-trigger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.context-trigger .pi-building {
  font-size: 0.85rem;
  color: var(--accent-cyan, #19d4d4);
}

.context-label {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.trigger-chevron {
  font-size: 0.6rem;
  opacity: 0.5;
}

.context-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 260px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  z-index: 100;
  overflow: hidden;
}

.dropdown-header {
  padding: 0.55rem 0.85rem;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-color-secondary);
}

.dropdown-divider {
  height: 1px;
  background: var(--surface-border);
}

.dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 0.6rem 0.85rem;
  border: none;
  background: none;
  color: var(--text-color);
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.15s;
  text-align: left;
  font-family: var(--font-body);
}

.dropdown-item:hover:not(:disabled) {
  background: rgba(32, 108, 245, 0.08);
}

.dropdown-item.current {
  background: rgba(32, 108, 245, 0.1);
  cursor: default;
}

.ctx-info {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.ctx-alias {
  font-weight: 500;
}

.ctx-id {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  font-family: var(--font-mono, monospace);
}

.ctx-check {
  font-size: 0.85rem;
  color: var(--color-success, #4ade80);
}

.dropdown-empty {
  padding: 0.85rem;
  text-align: center;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}
</style>

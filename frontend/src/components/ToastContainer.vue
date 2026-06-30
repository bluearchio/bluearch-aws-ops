<template>
  <div class="toast-container">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast-item"
        :class="`toast-${toast.type}`"
      >
        <div class="toast-icon">
          <i :class="iconClass(toast.type)"></i>
        </div>
        <div class="toast-body">
          <div class="toast-title">{{ toast.title }}</div>
          <div v-if="toast.message" class="toast-message">{{ toast.message }}</div>
        </div>
        <button class="toast-close" @click="remove(toast.id)">
          <i class="pi pi-times"></i>
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import { useToast } from '@/composables/useToast'

const { toasts, remove } = useToast()

function iconClass(type: string): string {
  switch (type) {
    case 'error': return 'pi pi-times-circle'
    case 'success': return 'pi pi-check-circle'
    case 'warning': return 'pi pi-exclamation-triangle'
    case 'info': return 'pi pi-info-circle'
    default: return 'pi pi-info-circle'
  }
}
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: 440px;
  width: 100%;
  pointer-events: none;
}

.toast-item {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
  pointer-events: auto;
}

.toast-error {
  border-left: 3px solid var(--color-danger);
}

.toast-success {
  border-left: 3px solid var(--color-success);
}

.toast-warning {
  border-left: 3px solid var(--color-warning);
}

.toast-info {
  border-left: 3px solid var(--primary-color);
}

.toast-icon {
  flex-shrink: 0;
  font-size: 1rem;
  margin-top: 0.1rem;
}

.toast-error .toast-icon { color: #f87171; }
.toast-success .toast-icon { color: #4ade80; }
.toast-warning .toast-icon { color: #facc15; }
.toast-info .toast-icon { color: #60a5fa; }

.toast-body {
  flex: 1;
  min-width: 0;
}

.toast-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-color);
  line-height: 1.3;
}

.toast-message {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-top: 0.2rem;
  line-height: 1.4;
  word-break: break-word;
}

.toast-close {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.15rem;
  font-size: 0.75rem;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.toast-close:hover { opacity: 1; }

/* Transitions — slide in from right */
.toast-enter-active {
  transition: all 0.25s ease-out;
}

.toast-leave-active {
  transition: all 0.2s ease-in;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(40px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(40px);
}
</style>

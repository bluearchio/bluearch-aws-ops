<template>
  <div v-if="visible" class="dialog-overlay" @click.self="cancel">
    <div class="dialog-box">
      <h3 class="dialog-title">{{ title }}</h3>
      <p class="dialog-message">{{ message }}</p>
      <div class="dialog-actions">
        <button class="btn btn-secondary" @click="cancel">Cancel</button>
        <button
          class="btn"
          :class="danger ? 'btn-danger' : 'btn-primary'"
          @click="confirm"
        >
          {{ confirmLabel || 'Confirm' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

function confirm() {
  emit('confirm')
}

function cancel() {
  emit('cancel')
}
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog-box {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.75rem;
  width: 420px;
  max-width: 90vw;
  box-shadow: 0 0 30px rgba(32, 108, 245, 0.3), 0 8px 32px rgba(0, 0, 0, 0.4);
}

.dialog-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.75rem;
}

.dialog-message {
  font-size: 0.9rem;
  color: var(--text-color-secondary);
  margin-bottom: 1.25rem;
  line-height: 1.5;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn {
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
  font-family: var(--font-body);
}

.btn-primary {
  background: var(--primary-color);
  color: white;
}

.btn-primary:hover {
  background: var(--primary-hover);
  box-shadow: 0 0 16px rgba(32, 108, 245, 0.4);
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-card-hover);
}

.btn-danger {
  background: var(--color-danger);
  color: white;
}

.btn-danger:hover {
  background: #dc2626;
  box-shadow: 0 0 16px rgba(239, 68, 68, 0.4);
}
</style>

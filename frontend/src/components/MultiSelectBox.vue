<template>
  <div class="msb" ref="rootEl">
    <div class="msb-trigger" @click="toggleOpen">
      <div class="msb-values">
        <span v-if="!modelValue || !modelValue.length" class="msb-placeholder">
          {{ placeholder }}
        </span>
        <span
          v-for="val in modelValue"
          :key="val"
          class="msb-chip"
          @click.stop="remove(val)"
        >
          {{ val }}
          <i class="pi pi-times"></i>
        </span>
      </div>
      <i class="pi pi-chevron-down msb-caret" :class="{ open }"></i>
    </div>
    <div v-if="open" class="msb-dropdown">
      <input
        v-model="search"
        class="msb-search"
        placeholder="Search..."
        @click.stop
      />
      <div class="msb-list">
        <div v-if="!filteredOptions.length" class="msb-empty">No matches</div>
        <label
          v-for="opt in filteredOptions"
          :key="opt"
          class="msb-item"
          @click.stop
        >
          <input
            type="checkbox"
            :checked="isSelected(opt)"
            @change="toggle(opt)"
          />
          <span>{{ opt }}</span>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  modelValue: string[]
  options: string[]
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const rootEl = ref<HTMLElement | null>(null)
const open = ref(false)
const search = ref('')

const filteredOptions = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((o) => o.toLowerCase().includes(q))
})

function isSelected(opt: string) {
  return (props.modelValue || []).includes(opt)
}

function toggle(opt: string) {
  const current = props.modelValue || []
  if (current.includes(opt)) {
    emit(
      'update:modelValue',
      current.filter((v) => v !== opt),
    )
  } else {
    emit('update:modelValue', [...current, opt])
  }
}

function remove(val: string) {
  emit(
    'update:modelValue',
    (props.modelValue || []).filter((v) => v !== val),
  )
}

function toggleOpen() {
  open.value = !open.value
  if (open.value) search.value = ''
}

function onClickOutside(e: MouseEvent) {
  if (!rootEl.value || !open.value) return
  if (!rootEl.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('click', onClickOutside))
onUnmounted(() => document.removeEventListener('click', onClickOutside))
</script>

<style scoped>
.msb {
  position: relative;
  width: 100%;
}

.msb-trigger {
  display: flex;
  align-items: center;
  min-height: 38px;
  padding: 0.35rem 0.5rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.82rem;
}
.msb-trigger:hover { border-color: var(--primary-color); }

.msb-values {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  min-width: 0;
}

.msb-placeholder {
  color: var(--text-color-secondary);
  opacity: 0.7;
}

.msb-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.15rem 0.5rem;
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  border-radius: 10px;
  font-size: 0.72rem;
  cursor: pointer;
}
.msb-chip:hover { background: rgba(32, 108, 245, 0.25); }
.msb-chip i { font-size: 0.6rem; opacity: 0.7; }

.msb-caret {
  font-size: 0.7rem;
  color: var(--text-color-secondary);
  transition: transform 0.15s;
  flex-shrink: 0;
  margin-left: 0.5rem;
}
.msb-caret.open { transform: rotate(180deg); }

.msb-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
  z-index: 100;
  max-height: 280px;
  display: flex;
  flex-direction: column;
}

.msb-search {
  margin: 0.5rem;
  padding: 0.4rem 0.65rem;
  background: var(--surface-ground);
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  color: var(--text-color);
  font-size: 0.8rem;
}

.msb-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.25rem 0;
}

.msb-empty {
  padding: 0.75rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.msb-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.75rem;
  cursor: pointer;
  font-size: 0.82rem;
  color: var(--text-color);
}
.msb-item:hover { background: var(--surface-card-hover); }
.msb-item input { cursor: pointer; }
</style>

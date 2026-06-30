import { reactive } from 'vue'

export interface Toast {
  id: number
  type: 'error' | 'success' | 'warning' | 'info'
  title: string
  message: string
  duration: number
}

const state = reactive<{ toasts: Toast[] }>({ toasts: [] })
let nextId = 1

function add(type: Toast['type'], title: string, message: string, duration = 5000) {
  const id = nextId++
  state.toasts.push({ id, type, title, message, duration })
  if (duration > 0) {
    setTimeout(() => remove(id), duration)
  }
}

function remove(id: number) {
  const idx = state.toasts.findIndex(t => t.id === id)
  if (idx !== -1) state.toasts.splice(idx, 1)
}

export function useToast() {
  return {
    toasts: state.toasts,
    remove,
    showSuccess(title: string, message = '') { add('success', title, message, 4000) },
    showError(title: string, message = '') { add('error', title, message, 8000) },
    showWarning(title: string, message = '') { add('warning', title, message, 6000) },
    showInfo(title: string, message = '') { add('info', title, message, 5000) },
  }
}

<template>
  <Teleport to="body">
    <Transition name="panel-slide">
      <div v-if="visible" class="scan-panel" :class="{ expanded }">
        <!-- Collapsed pill -->
        <div v-if="!expanded" class="panel-pill" @click="expanded = true">
          <i class="pi pi-spin pi-spinner pill-spinner" v-if="isRunning"></i>
          <i class="pi pi-check-circle pill-done" v-else-if="isCompleted"></i>
          <i class="pi pi-ban pill-cancelled" v-else-if="isCancelled"></i>
          <i class="pi pi-times-circle pill-failed" v-else></i>
          <span class="pill-text">
            {{ pillLabel }}
            <template v-if="scanJob">{{ scanJob.progress ?? 0 }}%</template>
          </span>
          <span v-if="totalResources > 0" class="pill-count">{{ totalResources }} found</span>
        </div>

        <!-- Expanded panel -->
        <div v-else class="panel-expanded">
          <div class="panel-titlebar">
            <span class="panel-title">
              <i class="pi pi-sync"></i>
              Resource Scan
            </span>
            <div class="panel-actions">
              <button
                v-if="isRunning && canStopScan"
                class="panel-btn panel-btn-danger"
                :disabled="isCancelling"
                title="Stop scan"
                @click="stopScan"
              >
                <i class="pi pi-stop-circle"></i>
              </button>
              <button class="panel-btn" title="Minimize" @click="expanded = false">
                <i class="pi pi-minus"></i>
              </button>
              <button class="panel-btn" title="Close" @click="dismiss">
                <i class="pi pi-times"></i>
              </button>
            </div>
          </div>
          <div class="panel-body">
            <JobTracker v-if="scanJob" :job="scanJob" mode="compact" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useJobsStore } from '@/stores/jobs'
import JobTracker from './JobTracker.vue'

const route = useRoute()
const jobsStore = useJobsStore()

const expanded = ref(false)
const dismissed = ref(false)
let autoCollapseTimer: ReturnType<typeof setTimeout> | null = null
let autoDismissTimer: ReturnType<typeof setTimeout> | null = null
let globalPollTimer: ReturnType<typeof setInterval> | null = null

const scanJob = computed(() => jobsStore.currentScanJob)

const isRunning = computed(() => {
  return scanJob.value?.status === 'running' || scanJob.value?.status === 'pending' || scanJob.value?.status === 'cancelling'
})

const isCompleted = computed(() => scanJob.value?.status === 'completed')
const isCancelling = computed(() => scanJob.value?.status === 'cancelling')
const isCancelled = computed(() => scanJob.value?.status === 'cancelled')
const canStopScan = computed(() => !scanJob.value?.source || scanJob.value.source === 'bluearch')
const pillLabel = computed(() => {
  if (isCancelling.value) return 'Stopping...'
  if (isRunning.value) return 'Scanning...'
  if (isCompleted.value) return 'Scan done'
  if (isCancelled.value) return 'Scan stopped'
  return 'Scan failed'
})

const isOnScans = computed(() => route.path === '/scans')

const totalResources = computed(() => {
  if (!scanJob.value) return 0
  if (scanJob.value.progress_data?.total_resources) {
    return scanJob.value.progress_data.total_resources
  }
  if (scanJob.value.result?.total_resources) {
    return scanJob.value.result.total_resources as number
  }
  return 0
})

// Show when active scan exists AND not on /scans page (which has inline tracker)
const visible = computed(() => {
  if (!scanJob.value) return false
  if (dismissed.value) return false
  if (isOnScans.value) return false
  return true
})

// On mount, check for running jobs and start a background poller so the
// panel picks up scans triggered outside the store (e.g. CLI, other app).
onMounted(async () => {
  await jobsStore.fetchJobs()
  if (scanJob.value && isRunning.value) {
    expanded.value = true
  }
  // Global poll detects scans started in other tabs or the CLI without
  // competing with normal route navigation.
  globalPollTimer = setInterval(() => {
    // Only auto-detect when the store has no active job tracked
    if (!jobsStore.currentScanJobId) {
      jobsStore.fetchJobs({ background: true }).catch(() => {})
    }
  }, 10000)
})

onBeforeUnmount(() => {
  if (globalPollTimer) {
    clearInterval(globalPollTimer)
    globalPollTimer = null
  }
  clearTimers()
})

// Watch for scan starting -> expand
watch(
  () => scanJob.value?.status,
  (status, oldStatus) => {
    if (status === 'running' && oldStatus !== 'running') {
      expanded.value = true
      dismissed.value = false
      clearTimers()
    }
    // Auto-collapse after 10s, fully dismiss after 60s
    if (status === 'completed' || status === 'failed' || status === 'cancelled') {
      startAutoDismiss()
    }
  },
)

// Reset dismissed when navigating away from /scans with an active scan
watch(isOnScans, (val) => {
  if (!val && isRunning.value) {
    dismissed.value = false
  }
})

function dismiss() {
  expanded.value = false
  dismissed.value = true
  clearTimers()
}

async function stopScan() {
  await jobsStore.cancelScan().catch(() => {})
}

function startAutoDismiss() {
  clearTimers()
  // Auto-collapse after 10s
  autoCollapseTimer = setTimeout(() => {
    expanded.value = false
  }, 10000)
  // Fully dismiss after 60s
  autoDismissTimer = setTimeout(() => {
    dismissed.value = true
  }, 60000)
}

function clearTimers() {
  if (autoCollapseTimer) {
    clearTimeout(autoCollapseTimer)
    autoCollapseTimer = null
  }
  if (autoDismissTimer) {
    clearTimeout(autoDismissTimer)
    autoDismissTimer = null
  }
}
</script>

<style scoped>
.scan-panel {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 9999;
}

/* Collapsed pill */
.panel-pill {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: #1e293b;
  color: #f1f5f9;
  border-radius: 24px;
  cursor: pointer;
  font-size: 0.8rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  transition: transform 0.15s, box-shadow 0.15s;
  user-select: none;
}

.panel-pill:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28);
}

.pill-spinner {
  font-size: 0.75rem;
  color: #60a5fa;
}

.pill-done {
  font-size: 0.75rem;
  color: #4ade80;
}

.pill-failed {
  font-size: 0.75rem;
  color: #f87171;
}

.pill-cancelled {
  font-size: 0.75rem;
  color: #f59e0b;
}

.pill-text {
  font-weight: 500;
}

.pill-count {
  background: rgba(255, 255, 255, 0.15);
  padding: 0.15rem 0.45rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
}

/* Expanded panel */
.panel-expanded {
  width: 380px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  overflow: hidden;
}

.panel-titlebar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem 0.85rem;
  background: var(--surface-card-hover, var(--surface-ground));
  border-bottom: 1px solid var(--surface-border);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
}

.panel-title i {
  color: var(--primary-color);
  font-size: 0.85rem;
}

.panel-actions {
  display: flex;
  gap: 0.25rem;
}

.panel-btn {
  background: none;
  border: none;
  padding: 0.25rem 0.4rem;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  transition: all 0.15s;
}

.panel-btn-danger {
  color: #f87171;
}

.panel-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.panel-btn:hover {
  background: var(--surface-border);
  color: var(--text-color);
}

.panel-body {
  padding: 0.5rem;
}

/* Transition */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: opacity 0.25s, transform 0.25s;
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
  transform: translateY(16px);
}

/* Spinner */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pi-spin { animation: spin 1s linear infinite; }
</style>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useJobsStore } from '@/stores/jobs'
import type { PermissionErrorDetail, ScanHistoryItem } from '@/types/api'

const router = useRouter()
const jobsStore = useJobsStore()
const history = ref<ScanHistoryItem[]>([])
const lastCompletedJobId = ref<string | null>(null)
const scanRegionOptions = [
  'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
  'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1',
  'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1',
  'sa-east-1', 'ca-central-1',
]
const defaultScanRegions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
const selectedScanRegions = ref<string[]>([...defaultScanRegions])

// Delegate scan state to the store so ScanProgressPanel can see it
const jobs = computed(() => jobsStore.jobs)
const activeJob = computed(() => jobsStore.currentScanJob)
const scanning = computed(
  () => activeJob.value?.status === 'running' || activeJob.value?.status === 'pending' || activeJob.value?.status === 'cancelling',
)
const cancelling = computed(() => activeJob.value?.status === 'cancelling')
const canStopScan = computed(() => !activeJob.value?.source || activeJob.value.source === 'bluearch')
const scanButtonLabel = computed(() => {
  if (cancelling.value) return 'Cancelling...'
  if (scanning.value) return 'Scanning...'
  return `Scan ${selectedScanRegions.value.join(', ')}`
})

const permissionDetails = computed<PermissionErrorDetail[]>(() => {
  const progressDetails = activeJob.value?.progress_data?.permission_error_details
  if (Array.isArray(progressDetails) && progressDetails.length) return progressDetails
  const resultDetails = activeJob.value?.result?.permission_error_details
  if (Array.isArray(resultDetails)) return resultDetails as unknown as PermissionErrorDetail[]
  return []
})

const skippedResourceTypes = computed(() => {
  const progressTypes = activeJob.value?.progress_data?.permission_error_resource_types
  if (Array.isArray(progressTypes) && progressTypes.length) return progressTypes
  const resultTypes = activeJob.value?.result?.permission_error_resource_types
  if (Array.isArray(resultTypes)) return resultTypes as string[]
  const types = new Set<string>()
  for (const detail of permissionDetails.value) {
    for (const resourceType of detail.resource_types || []) {
      types.add(resourceType)
    }
  }
  return [...types].sort()
})

const permissionErrorCount = computed(() => {
  const progressCount = activeJob.value?.progress_data?.permission_errors_count
  if (typeof progressCount === 'number') return progressCount
  const resultCount = activeJob.value?.result?.permission_errors
  if (typeof resultCount === 'number') return resultCount
  if (typeof resultCount === 'string') return Number(resultCount) || 0
  return permissionDetails.value.length
})

const visiblePermissionDetails = computed(() => permissionDetails.value.slice(0, 5))

onMounted(async () => {
  await loadData()
  // Sync store with server-side jobs so the panel picks up any running scan
  await jobsStore.fetchJobs()
})

// When a scan completes, refresh history and record the last completed id
watch(
  () => activeJob.value?.status,
  (status) => {
    if (status === 'completed') {
      lastCompletedJobId.value = activeJob.value?.id ?? null
      loadData()
    } else if (status === 'failed') {
      loadData()
    }
  },
)

async function loadData() {
  history.value = await api.scanHistory()
}

async function startScan() {
  lastCompletedJobId.value = null
  try {
    await jobsStore.startScan(undefined, selectedScanRegions.value)
  } catch {
    // Store tracks error state
  }
}

async function stopScan() {
  try {
    await jobsStore.cancelScan()
  } catch {
    // Store tracks error state
  }
}

function useUsRegions() {
  selectedScanRegions.value = [...defaultScanRegions]
}

function useAllListedRegions() {
  selectedScanRegions.value = [...scanRegionOptions]
}

function toggleRegion(region: string) {
  if (selectedScanRegions.value.includes(region)) {
    selectedScanRegions.value = selectedScanRegions.value.filter((r) => r !== region)
  } else {
    selectedScanRegions.value = [...selectedScanRegions.value, region]
  }
}

function viewResources() {
  router.push('/resources')
}

function formatDate(d?: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString()
}
</script>

<template>
  <div class="scans">
    <!-- Scan bar -->
    <div class="scan-bar">
      <div class="scan-bar-info">
        <span v-if="history.length" class="mono" style="font-size: 0.82rem; color: var(--text-color-secondary)">
          Last scan: {{ formatDate(history[0]?.started_at) }} ({{ history[0]?.resources_found }} resources)
        </span>
        <span v-else style="color: var(--text-color-secondary); font-size: 0.85rem">No scans yet</span>
      </div>
      <div class="scan-bar-actions">
        <div class="region-select">
          <div class="region-select-header">
            <span>{{ selectedScanRegions.length }} regions</span>
            <button type="button" @click="useUsRegions">US</button>
            <button type="button" @click="useAllListedRegions">All listed</button>
          </div>
          <div class="region-options">
            <button
              v-for="region in scanRegionOptions"
              :key="region"
              type="button"
              :class="{ active: selectedScanRegions.includes(region) }"
              @click="toggleRegion(region)"
            >
              {{ region }}
            </button>
          </div>
        </div>
        <button
          v-if="lastCompletedJobId"
          class="view-resources-btn"
          @click="viewResources"
        >
          <i class="pi pi-arrow-right"></i> View Resources
        </button>
        <button class="scan-btn" :class="{ 'scan-btn-running': scanning }" :disabled="scanning || selectedScanRegions.length === 0" @click="startScan">
          <i :class="scanning ? 'pi pi-spin pi-spinner' : 'pi pi-play'"></i>
          {{ scanButtonLabel }}
        </button>
        <button v-if="scanning && canStopScan" class="stop-scan-btn" :disabled="cancelling" @click="stopScan">
          <i class="pi pi-stop-circle"></i>
          {{ cancelling ? 'Stopping...' : 'Stop' }}
        </button>
      </div>
    </div>

    <!-- Live Scan Progress -->
    <div v-if="scanning && activeJob" class="progress-card">
      <div class="progress-header">
        <i class="pi pi-spin pi-spinner" style="color: var(--primary-color)"></i>
        <span class="progress-label">{{ activeJob.progress_message || 'Starting scan...' }}</span>
        <span class="progress-pct">{{ activeJob.progress || 0 }}%</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: (activeJob.progress || 0) + '%' }"></div>
      </div>
      <div v-if="activeJob.progress_data" class="progress-stats">
        <div class="progress-stat">
          <span class="progress-stat-value">{{ activeJob.progress_data.total_resources || 0 }}</span>
          <span class="progress-stat-label">Resources Found</span>
        </div>
        <div class="progress-stat">
          <span class="progress-stat-value">{{ activeJob.progress_data.completed_jobs || 0 }}/{{ activeJob.progress_data.total_jobs || 0 }}</span>
          <span class="progress-stat-label">Jobs</span>
        </div>
        <div v-if="activeJob.progress_data.current_service" class="progress-stat">
          <span class="progress-stat-value">{{ activeJob.progress_data.current_service }}</span>
          <span class="progress-stat-label">Service</span>
        </div>
        <div v-if="activeJob.progress_data.current_region" class="progress-stat">
          <span class="progress-stat-value mono">{{ activeJob.progress_data.current_region }}</span>
          <span class="progress-stat-label">Region</span>
        </div>
        <div v-if="activeJob.progress_data.errors_count" class="progress-stat">
          <span class="progress-stat-value" style="color: #f87171">{{ activeJob.progress_data.errors_count }}</span>
          <span class="progress-stat-label">Errors</span>
        </div>
      </div>
      <!-- By-service breakdown during scan -->
      <div v-if="activeJob.progress_data?.by_service && Object.keys(activeJob.progress_data.by_service).length" class="progress-services">
        <span
          v-for="(count, svc) in activeJob.progress_data.by_service"
          :key="svc"
          class="service-chip"
        >{{ svc }}: {{ count }}</span>
      </div>
    </div>

    <!-- Completed scan summary -->
    <div v-if="!scanning && activeJob && activeJob.status === 'completed'" class="progress-card progress-card-done">
      <div class="progress-header">
        <i class="pi pi-check-circle" style="color: #4ade80"></i>
        <span class="progress-label">Scan complete</span>
        <span class="progress-pct" style="color: #4ade80">100%</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill progress-fill-done" style="width: 100%"></div>
      </div>
      <div v-if="activeJob.progress_data" class="progress-stats">
        <div class="progress-stat">
          <span class="progress-stat-value">{{ activeJob.progress_data.total_resources || 0 }}</span>
          <span class="progress-stat-label">Resources Found</span>
        </div>
        <div class="progress-stat">
          <span class="progress-stat-value">{{ activeJob.progress_data.completed_jobs || 0 }}/{{ activeJob.progress_data.total_jobs || 0 }}</span>
          <span class="progress-stat-label">Jobs</span>
        </div>
      </div>
    </div>

    <div v-if="activeJob && permissionErrorCount > 0" class="permission-summary">
      <div class="permission-title">
        <i class="pi pi-lock"></i>
        {{ permissionErrorCount }} permission error{{ permissionErrorCount === 1 ? '' : 's' }}
      </div>
      <div v-if="skippedResourceTypes.length" class="permission-skipped">
        Resource types not collected: {{ skippedResourceTypes.join(', ') }}
      </div>
      <div v-for="(detail, idx) in visiblePermissionDetails" :key="idx" class="permission-item">
        <span v-if="detail.account_id" class="mono">{{ detail.account_id }}</span>
        {{ detail.service || 'Unknown service' }}<span v-if="detail.region">/{{ detail.region }}</span>
        <span v-if="detail.code" class="permission-code">{{ detail.code }}</span>
        <div v-if="detail.resource_name" class="permission-resource">{{ detail.resource_name }}</div>
      </div>
      <div v-if="permissionDetails.length > visiblePermissionDetails.length" class="permission-more">
        {{ permissionDetails.length - visiblePermissionDetails.length }} more permission error{{ permissionDetails.length - visiblePermissionDetails.length === 1 ? '' : 's' }}
      </div>
    </div>

    <!-- Active jobs -->
    <div v-if="jobs.length" class="table-card" style="margin-bottom: 1.5rem">
      <div class="table-info">Recent Jobs</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Message</th>
            <th>Progress</th>
            <th>Started</th>
            <th>Completed</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id" class="table-row">
            <td><span class="state-badge" :class="'state-' + job.status">{{ job.status }}</span></td>
            <td>{{ job.message || job.error || '-' }}</td>
            <td>
              <div v-if="job.status === 'running'" class="mini-progress">
                <div class="mini-progress-fill" :style="{ width: (job.progress || 0) + '%' }"></div>
              </div>
              <span v-else-if="job.status === 'completed'" class="text-muted">100%</span>
              <span v-else-if="job.status === 'cancelled'" class="text-muted">cancelled</span>
              <span v-else class="text-muted">-</span>
            </td>
            <td class="mono">{{ formatDate(job.started_at) }}</td>
            <td class="mono">{{ formatDate(job.completed_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Scan history -->
    <div class="table-card">
      <div class="table-info">Scan History</div>
      <div v-if="!history.length" class="empty-state">
        <i class="pi pi-search" style="font-size: 1.5rem; margin-bottom: 0.5rem"></i>
        <div>No scans yet. Click "Start Scan" to collect resources.</div>
      </div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th>Mode</th>
            <th>Collected By</th>
            <th>Status</th>
            <th>Resources</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="scan in history" :key="scan.id" class="table-row">
            <td><span class="service-badge">{{ scan.scan_mode }}</span></td>
            <td>{{ scan.collected_by }}</td>
            <td><span class="state-badge" :class="'state-' + scan.status">{{ scan.status }}</span></td>
            <td>
              <span
                class="resources-count-link"
                @click="viewResources"
              >
                {{ scan.resources_found }}
              </span>
            </td>
            <td class="mono">{{ formatDate(scan.started_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.scan-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem 1rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.scan-bar-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.region-select {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-width: 560px;
}

.region-select-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--text-color-secondary);
  font-size: 0.76rem;
}

.region-select-header button,
.region-options button {
  border: 1px solid var(--surface-border);
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-family: var(--font-body);
}

.region-select-header button {
  padding: 0.15rem 0.4rem;
}

.region-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.region-options button {
  padding: 0.2rem 0.45rem;
  font-size: 0.72rem;
}

.region-options button.active {
  background: rgba(32, 108, 245, 0.18);
  color: #5a9aff;
  border-color: rgba(32, 108, 245, 0.55);
}

.scan-btn {
  background: var(--gradient-brand-horizontal);
  color: white;
  border: none;
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  cursor: pointer;
  white-space: nowrap;
  font-family: var(--font-body);
  transition: box-shadow 0.15s;
}
.scan-btn:hover { box-shadow: 0 0 14px rgba(32, 108, 245, 0.35); }
.scan-btn:disabled { opacity: 0.8; cursor: default; }
.scan-btn-running { background: rgba(32, 108, 245, 0.2); color: #5a9aff; }

.stop-scan-btn {
  background: rgba(239, 68, 68, 0.14);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.35);
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  cursor: pointer;
  white-space: nowrap;
  font-family: var(--font-body);
}

.stop-scan-btn:disabled {
  opacity: 0.7;
  cursor: default;
}

.view-resources-btn {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
  border: 1px solid rgba(34, 197, 94, 0.3);
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  cursor: pointer;
  white-space: nowrap;
  font-family: var(--font-body);
  transition: all 0.15s;
}

.view-resources-btn:hover {
  background: rgba(34, 197, 94, 0.25);
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.2);
}

/* Live Progress Card */
.progress-card {
  background: rgba(32, 108, 245, 0.06);
  border: 1px solid rgba(32, 108, 245, 0.2);
  border-radius: 10px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
  transition: all 0.3s ease;
}

.progress-card-done {
  background: rgba(34, 197, 94, 0.06);
  border-color: rgba(34, 197, 94, 0.2);
}

.progress-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.65rem;
}

.progress-label {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-color);
  flex: 1;
}

.progress-pct {
  font-size: 0.8rem;
  font-family: var(--font-mono);
  color: var(--accent-cyan);
}

.progress-track {
  height: 6px;
  border-radius: 3px;
  background: var(--surface-border);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--gradient-brand-horizontal);
  box-shadow: 0 0 8px rgba(32, 108, 245, 0.4);
  transition: width 0.4s ease;
}

.progress-fill-done {
  background: linear-gradient(92.87deg, #22c55e 14.71%, #4ade80 87.94%);
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.4);
}

.progress-stats {
  display: flex;
  gap: 1.5rem;
  margin-top: 0.85rem;
  flex-wrap: wrap;
}

.progress-stat {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.progress-stat-value {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-color);
}

.progress-stat-label {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.progress-services {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--surface-border);
}

.service-chip {
  background: rgba(32, 108, 245, 0.12);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 500;
}

.permission-summary {
  padding: 0.85rem 1rem;
  margin-bottom: 1.5rem;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.24);
  border-radius: 10px;
  color: #f87171;
  font-size: 0.82rem;
}

.permission-title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-weight: 600;
  margin-bottom: 0.45rem;
}

.permission-skipped {
  color: var(--text-color);
  margin-bottom: 0.45rem;
  line-height: 1.35;
}

.permission-item {
  padding-top: 0.35rem;
  color: var(--text-color-secondary);
  line-height: 1.35;
}

.permission-code {
  color: #f87171;
  margin-left: 0.25rem;
}

.permission-resource {
  margin-top: 0.2rem;
  color: var(--text-color-secondary);
  font-family: var(--font-mono, monospace);
  word-break: break-word;
}

.permission-more {
  margin-top: 0.35rem;
  color: var(--text-color-secondary);
}

/* Mini progress bar in job table */
.mini-progress {
  height: 4px;
  width: 60px;
  border-radius: 2px;
  background: var(--surface-border);
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--gradient-brand-horizontal);
  transition: width 0.4s ease;
}

.text-muted {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.resources-count-link {
  color: #5a9aff;
  cursor: pointer;
  font-weight: 600;
  transition: all 0.15s;
}

.resources-count-link:hover {
  text-decoration: underline;
}

.table-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.table-info {
  padding: 0.75rem 1rem;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  border-bottom: 1px solid var(--surface-border);
  font-weight: 600;
}

.data-table { width: 100%; border-collapse: collapse; }
.data-table th {
  text-align: left; padding: 0.75rem 1rem; font-size: 0.78rem; font-weight: 600;
  text-transform: uppercase; color: var(--text-color-secondary);
  background: var(--surface-ground); border-bottom: 1px solid var(--surface-border);
}
.data-table td { padding: 0.7rem 1rem; font-size: 0.85rem; border-bottom: 1px solid var(--surface-border); }
.table-row { transition: background 0.1s; }
.table-row:hover { background: rgba(32, 108, 245, 0.05); }

.service-badge {
  background: rgba(32, 108, 245, 0.15); color: #5a9aff;
  padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.78rem; font-weight: 500;
}

.state-badge {
  padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.78rem; font-weight: 500; text-transform: capitalize;
}
.state-running, .state-pending { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.state-completed { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.state-failed { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.state-completed_with_errors { background: rgba(234, 179, 8, 0.15); color: #facc15; }

.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 3rem; color: var(--text-color-secondary); font-size: 0.85rem;
}

/* Spinner */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pi-spin { animation: spin 1s linear infinite; }
</style>

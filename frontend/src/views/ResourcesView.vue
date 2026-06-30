<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useResourcesStore } from '@/stores/resources'
import { useJobsStore } from '@/stores/jobs'
import { useEventTrackingStore } from '@/stores/eventTracking'

const router = useRouter()
const route = useRoute()
const store = useResourcesStore()
const jobsStore = useJobsStore()
const eventTracking = useEventTrackingStore()

const scanJob = computed(() => jobsStore.currentScanJob)
const scanRegionOptions = [
  'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
  'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1',
  'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1',
  'sa-east-1', 'ca-central-1',
]
const defaultScanRegions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
const selectedScanRegions = ref<string[]>([...defaultScanRegions])
const scanning = computed(
  () => scanJob.value?.status === 'running' || scanJob.value?.status === 'pending' || scanJob.value?.status === 'cancelling',
)
const cancellingScan = computed(() => scanJob.value?.status === 'cancelling')
const canStopScan = computed(() => !scanJob.value?.source || scanJob.value.source === 'bluearch')
const scanRegionsLabel = computed(() => selectedScanRegions.value.join(', '))
const scanButtonLabel = computed(() => {
  if (cancellingScan.value) return 'Stopping...'
  if (scanning.value) return scanProgressLabel.value
  return `Scan ${selectedScanRegions.value.length} region${selectedScanRegions.value.length === 1 ? '' : 's'}`
})

// Event-driven sync status summary — shown alongside the scan button so the
// Resources screen is the one place to see and control data-freshness.
const eventStatus = computed(() => {
  const s = eventTracking.status
  if (!s) return { label: 'Loading…', tone: 'neutral' as const, detail: '' }
  if (!s.stackset_exists) {
    return {
      label: 'Not configured',
      tone: 'neutral' as const,
      detail: 'Deploy event-driven sync in Setup to keep resources fresh',
    }
  }
  if (s.service_paused) {
    return {
      label: 'Paused',
      tone: 'warn' as const,
      detail: `${s.active_queues}/${s.total_queues} queues`,
    }
  }
  if (s.service_running) {
    const eventsToday = s.instances.reduce((sum, i) => sum + (i.events_today || 0), 0)
    return {
      label: 'Live',
      tone: 'ok' as const,
      detail: `${s.active_queues}/${s.total_queues} queues • ${eventsToday} events today`,
    }
  }
  return {
    label: 'Stopped',
    tone: 'neutral' as const,
    detail: `${s.active_queues}/${s.total_queues} queues`,
  }
})

async function toggleEventSync() {
  const s = eventTracking.status
  if (!s?.stackset_exists) {
    router.push('/setup')
    return
  }
  const action = s.service_running && !s.service_paused ? 'pause' : 'resume'
  try {
    await eventTracking.controlService(action)
  } catch {
    /* error surfaced via eventTracking.error */
  }
}
const scanProgressLabel = computed(() => `Scanning ${scanJob.value?.progress ?? 0}%`)

async function startScan() {
  if (selectedScanRegions.value.length === 0) return
  try {
    await jobsStore.startScan(undefined, selectedScanRegions.value)
  } catch {
    // error lives on jobsStore.error
  }
}

async function stopScan() {
  try {
    await jobsStore.cancelScan()
  } catch {
    // error lives on jobsStore.error
  }
}

// When a scan completes, refresh the table + summary so the user sees fresh data
watch(
  () => scanJob.value?.status,
  (status) => {
    if (status === 'completed') {
      store.fetchSummary()
      store.fetchItems()
    }
  },
)

// Compute unique services and regions from summary for dropdown options
const serviceOptions = computed(() => {
  if (!store.summary) return []
  return store.summary.by_service.map((s) => s.service_name).sort()
})

const regionOptions = computed(() => {
  if (!store.summary) return []
  return store.summary.by_region.map((r) => r.region).sort()
})

const totalPages = computed(() => Math.ceil(store.total / store.filters.page_size))

const showingFrom = computed(() => {
  if (store.total === 0) return 0
  return (store.filters.page - 1) * store.filters.page_size + 1
})

const showingTo = computed(() => {
  return Math.min(store.filters.page * store.filters.page_size, store.total)
})

function applyFilters() {
  store.filters.page = 1
  store.fetchItems()
}

function clearFilters() {
  store.filters.search = ''
  store.filters.service_name = ''
  store.filters.region = ''
  store.filters.account_id = ''
  store.filters.page = 1
  store.fetchItems()
}

function useUsRegions() {
  selectedScanRegions.value = [...defaultScanRegions]
}

function useAllRegions() {
  selectedScanRegions.value = [...scanRegionOptions]
}

function toggleScanRegion(region: string) {
  if (selectedScanRegions.value.includes(region)) {
    selectedScanRegions.value = selectedScanRegions.value.filter((r) => r !== region)
  } else {
    selectedScanRegions.value = [...selectedScanRegions.value, region]
  }
}

function goToPage(page: number) {
  if (page < 1 || page > totalPages.value) return
  store.filters.page = page
  store.fetchItems()
}

function changePageSize(size: number) {
  store.filters.page_size = size
  store.filters.page = 1
  store.fetchItems()
}

function openResource(resource: { id: string }) {
  router.push({ name: 'resource-detail', params: { id: resource.id } })
}

function tagCount(resource: { current_tags?: Record<string, string>; tags?: Record<string, string> }) {
  const t = resource.current_tags || resource.tags
  if (!t) return 0
  return Object.keys(t).length
}

function shortType(resourceType?: string): string {
  if (!resourceType) return '-'
  const parts = resourceType.split('::')
  return parts[parts.length - 1] || resourceType
}

function resourceState(resource: {
  service_name: string
  resource_type?: string
  metadata_json?: Record<string, unknown>
  attributes?: Record<string, unknown>
}): string {
  const meta = resource.metadata_json || resource.attributes
  if (!meta || typeof meta !== 'object') return '-'

  // Parse if it arrived as a string
  let parsed: Record<string, unknown> = meta as Record<string, unknown>
  if (typeof meta === 'string') {
    try { parsed = JSON.parse(meta as unknown as string) } catch { return '-' }
  }

  const svc = (resource.service_name || '').toLowerCase()
  const rtype = (resource.resource_type || '').toLowerCase()

  // EC2 instances
  if (svc === 'ec2' && (rtype.includes('instance') || rtype.endsWith('::instance'))) {
    return String(parsed.state || parsed.State || '-')
  }
  // EC2 volumes
  if (svc === 'ec2' && rtype.includes('volume')) {
    return String(parsed.state || parsed.State || '-')
  }
  // S3
  if (svc === 's3') {
    return String(parsed.encryption || parsed.Encryption || '-')
  }
  // RDS
  if (svc === 'rds') {
    return String(parsed.status || parsed.Status || parsed.db_instance_status || '-')
  }
  // Lambda
  if (svc === 'lambda') {
    return String(parsed.runtime || parsed.Runtime || '-')
  }

  // Fallback: first non-null metadata value
  for (const val of Object.values(parsed)) {
    if (val !== null && val !== undefined && val !== '') {
      const s = String(val)
      if (s.length <= 30) return s
    }
  }
  return '-'
}

function stateClass(state: string): string {
  const s = state.toLowerCase()
  if (s === 'running' || s === 'available' || s === 'active') return 'state-ok'
  if (s === 'stopped' || s === 'terminated' || s === 'deleted') return 'state-warn'
  if (s === 'in-use') return 'state-ok'
  return ''
}

function formatLastScanned(resource: { last_scanned_at?: string; updated_at?: string }): string {
  const d = resource.last_scanned_at || resource.updated_at
  if (!d) return '-'
  return new Date(d).toLocaleString()
}

// Initialize from query params if present
onMounted(() => {
  if (route.query.service_name) store.filters.service_name = route.query.service_name as string
  if (route.query.region) store.filters.region = route.query.region as string
  if (route.query.account_id) store.filters.account_id = route.query.account_id as string

  store.fetchSummary({ background: true })
  store.fetchItems()
  // Sync scan state so an already-running scan shows progress here too
  jobsStore.fetchJobs({ background: true })
  // Pull event-driven sync status for the header
  eventTracking.fetchStatus()
})
</script>

<template>
  <div class="resources">
    <!-- Data freshness header: scan trigger + event-driven sync status -->
    <div class="freshness-bar">
      <div class="freshness-item">
        <button
          class="btn btn-primary btn-sm scan-btn"
          :disabled="scanning || selectedScanRegions.length === 0"
          @click="startScan"
        >
          <i :class="scanning ? 'pi pi-spin pi-spinner' : 'pi pi-sync'"></i>
          {{ scanButtonLabel }}
        </button>
        <button
          v-if="scanning && canStopScan"
          class="btn btn-danger btn-sm stop-scan-btn"
          :disabled="cancellingScan"
          @click="stopScan"
        >
          <i class="pi pi-stop-circle"></i>
          Stop
        </button>
        <span class="freshness-hint">One-shot collection of all resources + log findings.</span>
        <div class="scan-region-selector">
          <div class="scan-region-summary">
            <span>{{ scanRegionsLabel || 'No regions selected' }}</span>
            <button type="button" @click="useUsRegions">US default</button>
            <button type="button" @click="useAllRegions">All listed</button>
          </div>
          <div class="scan-region-options">
            <button
              v-for="region in scanRegionOptions"
              :key="region"
              type="button"
              :class="{ active: selectedScanRegions.includes(region) }"
              @click="toggleScanRegion(region)"
            >
              {{ region }}
            </button>
          </div>
        </div>
      </div>

      <div class="freshness-divider"></div>

      <div class="freshness-item">
        <div class="event-status">
          <span class="event-status-dot" :class="'tone-' + eventStatus.tone"></span>
          <span class="event-status-label">Event-driven sync: <strong>{{ eventStatus.label }}</strong></span>
          <span v-if="eventStatus.detail" class="event-status-detail">{{ eventStatus.detail }}</span>
        </div>
        <div class="event-actions">
          <button
            v-if="eventTracking.status?.stackset_exists"
            class="btn btn-outline btn-sm"
            @click="toggleEventSync"
            :disabled="eventTracking.loading"
          >
            <i
              :class="
                eventTracking.status.service_running && !eventTracking.status.service_paused
                  ? 'pi pi-pause'
                  : 'pi pi-play'
              "
            ></i>
            {{
              eventTracking.status.service_running && !eventTracking.status.service_paused
                ? 'Pause'
                : 'Resume'
            }}
          </button>
          <router-link to="/setup" class="btn btn-outline btn-sm">
            <i class="pi pi-cog"></i> Manage
          </router-link>
        </div>
      </div>
    </div>

    <!-- Filters bar -->
    <div class="filters-bar">
      <div class="filter-group">
        <div class="filter-input-wrapper">
          <i class="pi pi-search filter-input-icon"></i>
          <input
            type="text"
            v-model="store.filters.search"
            placeholder="Search by ARN or resource ID..."
            class="filter-input"
            @keyup.enter="applyFilters"
          />
        </div>

        <select v-model="store.filters.service_name" class="filter-select" @change="applyFilters">
          <option value="">All Services</option>
          <option v-for="svc in serviceOptions" :key="svc" :value="svc">{{ svc }}</option>
        </select>

        <select v-model="store.filters.region" class="filter-select" @change="applyFilters">
          <option value="">All Regions</option>
          <option v-for="reg in regionOptions" :key="reg" :value="reg">{{ reg }}</option>
        </select>
      </div>

      <div class="filter-actions">
        <button class="btn btn-primary btn-sm" @click="applyFilters">
          <i class="pi pi-search"></i> Search
        </button>
        <button
          v-if="store.filters.search || store.filters.service_name || store.filters.region || store.filters.account_id"
          class="btn btn-secondary btn-sm"
          @click="clearFilters"
        >
          <i class="pi pi-times"></i> Clear
        </button>
      </div>
    </div>

    <!-- Scan progress / error banner -->
    <div v-if="scanning && scanJob" class="scan-progress-banner">
      <i class="pi pi-spin pi-spinner"></i>
      <div class="scan-progress-text">
        <strong>Scanning AWS resources...</strong>
        <span v-if="scanJob.progress_message">{{ scanJob.progress_message }}</span>
      </div>
      <div class="scan-progress-bar">
        <div class="scan-progress-fill" :style="{ width: (scanJob.progress || 0) + '%' }"></div>
      </div>
      <span class="scan-progress-pct">{{ scanJob.progress || 0 }}%</span>
    </div>

    <div v-if="scanJob?.status === 'failed'" class="scan-error-banner">
      <i class="pi pi-times-circle"></i>
      <span>Scan failed: {{ scanJob.error || scanJob.message || 'unknown error' }}</span>
    </div>

    <!-- Loading / Error -->
    <div v-if="store.loading" class="loading-state">
      <i class="pi pi-spin pi-spinner" style="margin-right: 0.5rem"></i> Loading resources...
    </div>
    <div v-else-if="store.error" class="error-state">
      <i class="pi pi-exclamation-circle" style="margin-right: 0.5rem"></i> {{ store.error }}
    </div>

    <!-- Table -->
    <div v-else class="table-card">
      <div class="table-info">
        Showing {{ showingFrom }}-{{ showingTo }} of {{ store.total }} resources
      </div>
      <div v-if="!store.items.length" class="empty-state">
        <i class="pi pi-server" style="font-size: 1.5rem; margin-bottom: 0.5rem"></i>
        <div>No resources found. Run a scan to collect resources.</div>
      </div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th>Service</th>
            <th>Resource ID</th>
            <th>Type</th>
            <th>Region</th>
            <th>Account</th>
            <th>State</th>
            <th>Tags</th>
            <th>Last Scanned</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="resource in store.items"
            :key="resource.id"
            class="table-row clickable-row"
            @click="openResource(resource)"
          >
            <td><span class="service-badge">{{ resource.service_name }}</span></td>
            <td class="resource-id">{{ resource.resource_id }}</td>
            <td><span class="type-badge">{{ shortType(resource.resource_type) }}</span></td>
            <td><span class="mono">{{ resource.region }}</span></td>
            <td class="account-id">{{ resource.account_id }}</td>
            <td>
              <span class="state-value" :class="stateClass(resourceState(resource))">{{ resourceState(resource) }}</span>
            </td>
            <td>
              <span class="tag-count" :class="{ 'tag-count-zero': tagCount(resource) === 0, 'tag-count-has': tagCount(resource) > 0 }">
                {{ tagCount(resource) }}
              </span>
            </td>
            <td class="mono">{{ formatLastScanned(resource) }}</td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
      <div v-if="store.items.length" class="pagination">
        <div class="pagination-info">
          Page {{ store.filters.page }} of {{ totalPages }}
        </div>
        <div class="pagination-controls">
          <select class="filter-select page-size-select" :value="store.filters.page_size" @change="changePageSize(Number(($event.target as HTMLSelectElement).value))">
            <option :value="25">25 / page</option>
            <option :value="50">50 / page</option>
            <option :value="100">100 / page</option>
          </select>
          <button class="btn btn-secondary btn-sm" :disabled="store.filters.page <= 1" @click="goToPage(store.filters.page - 1)">
            <i class="pi pi-chevron-left"></i>
          </button>
          <button class="btn btn-secondary btn-sm" :disabled="store.filters.page >= totalPages" @click="goToPage(store.filters.page + 1)">
            <i class="pi pi-chevron-right"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filters-bar {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1rem;
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.filter-group {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  flex: 1;
  align-items: center;
}

.filter-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.filter-input-wrapper {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.filter-input-icon {
  position: absolute;
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  pointer-events: none;
}

.filter-input {
  width: 100%;
  padding: 0.5rem 0.75rem 0.5rem 2rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-ground);
  color: var(--text-color);
  font-size: 0.85rem;
  font-family: var(--font-body);
  transition: border-color 0.15s;
}

.filter-input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.filter-input::placeholder {
  color: var(--text-color-secondary);
}

.filter-select {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-ground);
  color: var(--text-color);
  font-size: 0.85rem;
  font-family: var(--font-body);
  cursor: pointer;
  min-width: 140px;
}

.filter-select:focus {
  outline: none;
  border-color: var(--primary-color);
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.15s;
  font-family: var(--font-body);
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.btn-primary {
  background: var(--gradient-brand-horizontal);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  box-shadow: 0 0 14px rgba(32, 108, 245, 0.35);
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--surface-card);
}

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
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

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th {
  text-align: left;
  padding: 0.75rem 1rem;
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}

.data-table td {
  padding: 0.7rem 1rem;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--surface-border);
}

.table-row {
  transition: background 0.1s;
}

.table-row:hover {
  background: rgba(32, 108, 245, 0.05);
}

.clickable-row {
  cursor: pointer;
}

.clickable-row:hover {
  background: rgba(32, 108, 245, 0.08);
}

.service-badge {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.resource-id {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-id {
  font-family: var(--font-mono);
  font-size: 0.8rem;
}

.type-badge {
  background: rgba(25, 212, 212, 0.12);
  color: var(--accent-cyan, #19d4d4);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
  white-space: nowrap;
}

.state-value {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  text-transform: lowercase;
}

.state-ok {
  color: #4ade80;
}

.state-warn {
  color: #f87171;
}

.tag-count {
  display: inline-block;
  min-width: 1.5rem;
  text-align: center;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 600;
  background: rgba(107, 114, 128, 0.15);
  color: var(--text-color-secondary);
}

.tag-count-zero {
  background: rgba(107, 114, 128, 0.15);
  color: var(--text-color-secondary);
}

.tag-count-has {
  background: rgba(25, 212, 212, 0.15);
  color: var(--accent-cyan, #19d4d4);
}

.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--surface-border);
}

.pagination-info {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.page-size-select {
  min-width: 100px;
  padding: 0.35rem 0.5rem;
  font-size: 0.8rem;
}

.loading-state {
  color: var(--text-color-secondary);
  padding: 2rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.error-state {
  color: var(--color-danger);
  padding: 1rem;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 8px;
  display: flex;
  align-items: center;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

/* Freshness bar (scan button + event-driven sync status) */
.freshness-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
}

.freshness-item {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
}

.freshness-item:last-child {
  margin-left: auto;
}

.freshness-divider {
  width: 1px;
  align-self: stretch;
  background: var(--surface-border);
}

.freshness-hint {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.scan-region-selector {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  flex-basis: 100%;
}

.scan-region-summary {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  color: var(--text-color-secondary);
  font-size: 0.76rem;
}

.scan-region-summary span {
  color: var(--text-color);
}

.scan-region-summary button,
.scan-region-options button {
  border: 1px solid var(--surface-border);
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-family: var(--font-body);
}

.scan-region-summary button {
  padding: 0.15rem 0.4rem;
}

.scan-region-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.scan-region-options button {
  padding: 0.2rem 0.45rem;
  font-size: 0.72rem;
}

.scan-region-options button.active {
  background: rgba(32, 108, 245, 0.18);
  color: #5a9aff;
  border-color: rgba(32, 108, 245, 0.55);
}

.event-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}

.event-status-label strong {
  color: var(--text-color);
}

.event-status-detail {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  opacity: 0.8;
}

.event-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.event-status-dot.tone-ok   { background: #22c55e; box-shadow: 0 0 0 3px rgba(34,197,94,0.18); }
.event-status-dot.tone-warn { background: #facc15; box-shadow: 0 0 0 3px rgba(250,204,21,0.18); }
.event-status-dot.tone-neutral { background: var(--text-color-secondary); opacity: 0.5; }

.event-actions {
  display: flex;
  gap: 0.4rem;
}

.scan-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.stop-scan-btn {
  background: rgba(239, 68, 68, 0.14);
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.35);
}

.stop-scan-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.scan-progress-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.85rem;
  margin-top: 0.75rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  font-size: 0.85rem;
}

.scan-progress-text {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.scan-progress-text span {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.scan-progress-bar {
  flex: 1;
  height: 6px;
  background: var(--surface-ground);
  border-radius: 3px;
  overflow: hidden;
  min-width: 120px;
}

.scan-progress-fill {
  height: 100%;
  background: var(--primary-color);
  transition: width 0.3s ease;
}

.scan-progress-pct {
  color: var(--text-color-secondary);
  font-variant-numeric: tabular-nums;
  min-width: 3em;
  text-align: right;
}

.scan-error-banner {
  padding: 0.6rem 0.85rem;
  margin-top: 0.75rem;
  background: rgba(220, 38, 38, 0.12);
  color: #fecaca;
  border: 1px solid rgba(220, 38, 38, 0.4);
  border-radius: 6px;
  display: flex;
  gap: 0.5rem;
  align-items: center;
  font-size: 0.85rem;
}
</style>

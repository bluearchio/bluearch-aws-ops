<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useRecommendationsStore } from '@/stores/recommendations'
import { api } from '@/api/client'
import type { PermissionErrorDetail, ScanJob, ScanHistoryItem } from '@/types/api'

const router = useRouter()
const route = useRoute()
const store = useRecommendationsStore()

// --- Sidebar filter types ---
// All known recommendation types (matches recommendations.py registry).
// Shown in the sidebar even when count=0 so users can see the full catalog.
const BUILTIN_TYPES = [
  // EC2
  'unattached_ec2_volumes',
  'previous_gen_ec2_volumes',
  'unencrypted_ec2_volumes',
  'previous_gen_ec2_instances',
  'old_stopped_ec2_instances',
  'underutilized_ec2_instances',
  'idle_ec2_instances',
  'outdated_ebs_snapshots',
  'io_volume_type_non_optimized',
  'expiring_ec2_reserved_instances',
  'unused_security_groups',
  'unattached_elastic_ips',
  // RDS
  'previous_gen_rds_instances',
  'unencrypted_rds_instances',
  'idle_rds_instances',
  'underutilized_rds_instances',
  // ELB
  'idle_application_load_balancers',
  // IAM
  'expired_iam_keys',
  'inactive_iam_roles',
  // ElastiCache
  'old_on_demand_elasticache',
  // AWS services
  'cost_optimization_hub_recommendations',
  // Compute Optimizer — EC2
  'ec2_cpu_overprovisioned',
  'ec2_cpu_underprovisioned',
  'ec2_memory_overprovisioned',
  'ec2_memory_underprovisioned',
  'ec2_network_bandwidth_overprovisioned',
  'ec2_network_bandwidth_underprovisioned',
  'ec2_network_pps_overprovisioned',
  'ec2_network_pps_underprovisioned',
  'ec2_license_not_optimized',
  // Compute Optimizer — EBS
  'ebs_rightsize_volume_type',
  'ebs_rightsize_volume_iops',
  'ebs_rightsize_volume_size',
  // Compute Optimizer — Lambda / ASG / ECS
  'lambda_rightsize_memory',
  'asg_not_optimized',
  'ecs4fargate_cpu_overprovisioned',
  'ecs4fargate_cpu_underprovisioned',
  'ecs4fargate_memory_overprovisioned',
  'ecs4fargate_memory_underprovisioned',
  // Compute Optimizer — RDS
  'rds_cpu_overprovisioned',
  'rds_cpu_underprovisioned',
  'rds_new_engine_version_available',
  'rds_new_generation_instance_class_available',
  'rds_network_bandwidth_overprovisioned',
  'rds_network_bandwidth_underprovisioned',
  'rds_ebs_throughput_overprovisioned',
  'rds_ebs_throughput_underprovisioned',
  'rds_ebs_iops_overprovisioned',
  'rds_ebs_new_generation_storage_type_available',
  'rds_ebs_volume_allocated_storage_underprovisioned',
]

const allTypes = ref<{ type: string; count: number }[]>([])

async function loadTypes() {
  const fetched = await store.fetchTypes()
  // Merge built-in types with API results
  const typeMap = new Map<string, number>()
  for (const bt of BUILTIN_TYPES) {
    typeMap.set(bt, 0)
  }
  for (const t of fetched) {
    typeMap.set(t.type, t.count)
  }
  allTypes.value = Array.from(typeMap.entries())
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count || a.type.localeCompare(b.type))
}

const totalRecommendations = computed(() => {
  return allTypes.value.reduce((sum, t) => sum + t.count, 0)
})

function applyTypeFilter(type: string) {
  store.filters.recommendation_type = store.filters.recommendation_type === type ? '' : type
  store.filters.page = 1
  store.fetchItems()
}

function clearFilters() {
  store.filters.recommendation_type = ''
  store.filters.account_id = ''
  store.filters.region = ''
  store.filters.page = 1
  store.fetchItems()
}

// --- Resource navigation ---
function goToResource(resourceId: string | undefined) {
  if (!resourceId) return
  router.push({ name: 'resource-detail', params: { id: resourceId } })
}

// --- Notes (customer-requested: attach context/action-taken to each rec) ---
import type { RecommendationNote } from '@/types/api'

const expandedRecId = ref<string | null>(null)
const composeBody = ref<Record<string, string>>({})
const submittingRecId = ref<string | null>(null)
const editingNoteId = ref<string | null>(null)
const editingBody = ref('')
const notesError = ref<string | null>(null)

function toggleNotes(recId: string) {
  expandedRecId.value = expandedRecId.value === recId ? null : recId
  // Reset any in-progress edit whenever we change rows so state stays clean.
  editingNoteId.value = null
  editingBody.value = ''
  notesError.value = null
}

async function submitNote(recId: string) {
  const body = (composeBody.value[recId] || '').trim()
  if (!body) return
  submittingRecId.value = recId
  notesError.value = null
  try {
    await store.addNote(recId, body)
    composeBody.value[recId] = ''
  } catch (e) {
    notesError.value = e instanceof Error ? e.message : 'Failed to add note'
  } finally {
    submittingRecId.value = null
  }
}

function startEdit(note: RecommendationNote) {
  editingNoteId.value = note.id
  editingBody.value = note.body
}

function cancelEdit() {
  editingNoteId.value = null
  editingBody.value = ''
}

async function saveEdit(recId: string) {
  if (!editingNoteId.value || !editingBody.value.trim()) return
  notesError.value = null
  try {
    await store.updateNote(recId, editingNoteId.value, editingBody.value.trim())
    editingNoteId.value = null
    editingBody.value = ''
  } catch (e) {
    notesError.value = e instanceof Error ? e.message : 'Failed to save note'
  }
}

async function confirmDelete(recId: string, noteId: string) {
  if (!confirm('Delete this note?')) return
  notesError.value = null
  try {
    await store.deleteNote(recId, noteId)
  } catch (e) {
    notesError.value = e instanceof Error ? e.message : 'Failed to delete note'
  }
}

function formatDateTime(ts?: string | null): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

// --- Pagination ---
const totalPages = computed(() => Math.ceil(store.total / store.filters.page_size))
const showingFrom = computed(() => {
  if (store.total === 0) return 0
  return (store.filters.page - 1) * store.filters.page_size + 1
})
const showingTo = computed(() => Math.min(store.filters.page * store.filters.page_size, store.total))

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

// --- Scan functionality ---
const scanning = ref(false)
const activeJob = ref<ScanJob | null>(null)
const scanHistory = ref<ScanHistoryItem[]>([])
const pollInterval = ref<number | null>(null)
const scanCompleted = ref(false)

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

async function loadScanHistory() {
  try {
    scanHistory.value = await api.scanHistory()
  } catch {
    // ignore
  }
}

async function startScan() {
  scanning.value = true
  scanCompleted.value = false
  activeJob.value = null
  try {
    const result = await api.startScan()
    pollInterval.value = window.setInterval(async () => {
      try {
        const job = await api.getScanJob(result.job_id)
        activeJob.value = job
        if (job.status === 'completed' || job.status === 'failed') {
          if (pollInterval.value) clearInterval(pollInterval.value)
          pollInterval.value = null
          scanning.value = false
          if (job.status === 'completed') {
            scanCompleted.value = true
            // Auto-refresh recommendations data
            await Promise.all([store.fetchItems(), loadTypes(), loadScanHistory()])
          }
        }
      } catch {
        // poll error, keep trying
      }
    }, 2000)
  } catch {
    scanning.value = false
  }
}

function formatDate(d?: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString()
}

function formatTypeName(type: string): string {
  return type.replace(/_/g, ' ')
}

// --- Lifecycle ---
onMounted(async () => {
  if (route.query.recommendation_type) {
    store.filters.recommendation_type = route.query.recommendation_type as string
  }
  if (route.query.account_id) {
    store.filters.account_id = route.query.account_id as string
  }
  if (route.query.region) {
    store.filters.region = route.query.region as string
  }

  await Promise.all([store.fetchItems(), loadTypes(), loadScanHistory()])
})

onBeforeUnmount(() => {
  if (pollInterval.value) clearInterval(pollInterval.value)
})
</script>

<template>
  <div class="recommendations-layout">
    <!-- Left sidebar: type filters -->
    <aside class="type-sidebar">
      <div class="sidebar-header">
        <span class="sidebar-title">Recommendation Types</span>
      </div>
      <div class="type-list">
        <button
          class="type-item"
          :class="{ active: store.filters.recommendation_type === '' }"
          @click="clearFilters"
        >
          <span class="type-item-label">All</span>
          <span class="type-item-count">{{ totalRecommendations }}</span>
        </button>
        <button
          v-for="t in allTypes"
          :key="t.type"
          class="type-item"
          :class="{
            active: store.filters.recommendation_type === t.type,
            'type-item-zero': t.count === 0,
          }"
          @click="applyTypeFilter(t.type)"
        >
          <span class="type-item-label">{{ formatTypeName(t.type) }}</span>
          <span class="type-item-count" :class="{ 'count-zero': t.count === 0 }">{{ t.count }}</span>
        </button>
      </div>
    </aside>

    <!-- Right content: scan bar + table -->
    <div class="main-content">
      <!-- Scan bar -->
      <div class="scan-bar">
        <div class="scan-bar-info">
          <span v-if="scanHistory.length" class="mono" style="font-size: 0.82rem; color: var(--text-color-secondary)">
            Last scan: {{ formatDate(scanHistory[0]?.started_at) }}
            ({{ scanHistory[0]?.resources_found }} resources)
          </span>
          <span v-else style="color: var(--text-color-secondary); font-size: 0.85rem">No scans yet</span>
        </div>
        <div class="scan-bar-actions">
          <button class="scan-btn" :class="{ 'scan-btn-running': scanning }" :disabled="scanning" @click="startScan">
            <i :class="scanning ? 'pi pi-spin pi-spinner' : 'pi pi-play'"></i>
            {{ scanning ? 'Scanning...' : 'Scan Resources' }}
          </button>
        </div>
      </div>

      <!-- Live scan progress -->
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
        <div v-if="activeJob.progress_data?.by_service && Object.keys(activeJob.progress_data.by_service).length" class="progress-services">
          <span
            v-for="(count, svc) in activeJob.progress_data.by_service"
            :key="svc"
            class="service-chip"
          >{{ svc }}: {{ count }}</span>
        </div>
      </div>

      <!-- Completed scan summary -->
      <div v-if="scanCompleted && activeJob && activeJob.status === 'completed'" class="progress-card progress-card-done">
        <div class="progress-header">
          <i class="pi pi-check-circle" style="color: #4ade80"></i>
          <span class="progress-label">Scan complete -- recommendations refreshed</span>
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

      <!-- Table -->
      <div v-if="store.loading" class="loading-state">
        <i class="pi pi-spin pi-spinner" style="margin-right: 0.5rem"></i> Loading recommendations...
      </div>
      <div v-else-if="store.error" class="error-state">
        <i class="pi pi-exclamation-circle" style="margin-right: 0.5rem"></i> {{ store.error }}
      </div>
      <div v-else class="table-card">
        <div class="table-info">
          <span v-if="store.filters.recommendation_type">
            {{ formatTypeName(store.filters.recommendation_type) }} --
          </span>
          Showing {{ showingFrom }}-{{ showingTo }} of {{ store.total }} recommendations
        </div>
        <div v-if="!store.items.length" class="empty-state">
          <i class="pi pi-list" style="font-size: 1.5rem; margin-bottom: 0.5rem"></i>
          <div>No recommendations found for this filter.</div>
        </div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Resource</th>
              <th>Account</th>
              <th>Region</th>
              <th>Rationale</th>
              <th class="notes-col">Notes</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="rec in store.items" :key="rec.id">
              <tr
                class="table-row rec-row"
                :class="{ 'rec-row-open': expandedRecId === rec.id }"
                @click="toggleNotes(rec.id)"
              >
                <td><span class="service-badge">{{ formatTypeName(rec.recommendation_type) }}</span></td>
                <td>
                  <span
                    v-if="rec.resource_id"
                    class="resource-id resource-id-link"
                    @click.stop="goToResource(rec.resource_id)"
                  >
                    {{ rec.attributes?.resource_id || rec.resource_id }}
                  </span>
                  <span v-else class="resource-id">-</span>
                </td>
                <td class="account-id">{{ rec.account_name || rec.account_id }}</td>
                <td><span class="mono">{{ rec.region_name }}</span></td>
                <td>{{ rec.attributes?.ActionRationale || '-' }}</td>
                <td class="notes-col">
                  <span class="notes-chip" :class="{ 'notes-chip-has': (rec.notes?.length ?? 0) > 0 }">
                    <i class="pi pi-comment"></i>
                    {{ rec.notes?.length ?? 0 }}
                  </span>
                </td>
              </tr>
              <tr v-if="expandedRecId === rec.id" class="notes-panel-row">
                <td :colspan="6">
                  <div class="notes-panel">
                    <div class="notes-header">
                      <span>Notes</span>
                      <span class="muted">— why the finding exists / what's being done about it</span>
                    </div>

                    <ul v-if="(rec.notes?.length ?? 0) > 0" class="notes-list">
                      <li v-for="n in rec.notes" :key="n.id" class="note-item">
                        <div v-if="editingNoteId === n.id" class="note-edit">
                          <textarea v-model="editingBody" rows="3"></textarea>
                          <div class="note-edit-actions">
                            <button class="btn btn-sm btn-primary" :disabled="!editingBody.trim()" @click.stop="saveEdit(rec.id)">
                              <i class="pi pi-check"></i> Save
                            </button>
                            <button class="btn btn-sm" @click.stop="cancelEdit">Cancel</button>
                          </div>
                        </div>
                        <template v-else>
                          <div class="note-body">{{ n.body }}</div>
                          <div class="note-meta">
                            <span>{{ n.author || 'unknown' }}</span>
                            <span class="muted">· {{ formatDateTime(n.created_at) }}</span>
                            <span v-if="n.updated_at && n.created_at && n.updated_at !== n.created_at" class="muted">
                              (edited {{ formatDateTime(n.updated_at) }})
                            </span>
                            <span class="note-actions">
                              <button class="btn-icon" title="Edit" @click.stop="startEdit(n)">
                                <i class="pi pi-pencil"></i>
                              </button>
                              <button class="btn-icon" title="Delete" @click.stop="confirmDelete(rec.id, n.id)">
                                <i class="pi pi-trash"></i>
                              </button>
                            </span>
                          </div>
                        </template>
                      </li>
                    </ul>
                    <div v-else class="notes-empty muted">No notes yet.</div>

                    <div class="note-compose">
                      <textarea
                        v-model="composeBody[rec.id]"
                        rows="2"
                        placeholder="Add a note — e.g. 'False positive: app owner confirmed retention policy covers this'"
                        @click.stop
                        @keyup.stop
                      ></textarea>
                      <button
                        class="btn btn-sm btn-primary"
                        :disabled="!composeBody[rec.id] || !composeBody[rec.id].trim() || submittingRecId === rec.id"
                        @click.stop="submitNote(rec.id)"
                      >
                        <i :class="submittingRecId === rec.id ? 'pi pi-spin pi-spinner' : 'pi pi-plus'"></i>
                        Add note
                      </button>
                    </div>
                    <div v-if="notesError" class="notes-error">{{ notesError }}</div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>

        <!-- Pagination -->
        <div v-if="store.items.length" class="pagination">
          <div class="pagination-info">
            Page {{ store.filters.page }} of {{ totalPages }}
          </div>
          <div class="pagination-controls">
            <select
              class="filter-select page-size-select"
              :value="store.filters.page_size"
              @change="changePageSize(Number(($event.target as HTMLSelectElement).value))"
            >
              <option :value="25">25 / page</option>
              <option :value="50">50 / page</option>
              <option :value="100">100 / page</option>
            </select>
            <button
              class="btn btn-secondary btn-sm"
              :disabled="store.filters.page <= 1"
              @click="goToPage(store.filters.page - 1)"
            >
              <i class="pi pi-chevron-left"></i>
            </button>
            <button
              class="btn btn-secondary btn-sm"
              :disabled="store.filters.page >= totalPages"
              @click="goToPage(store.filters.page + 1)"
            >
              <i class="pi pi-chevron-right"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* --- Two-column layout --- */
.recommendations-layout {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

/* --- Left sidebar --- */
.type-sidebar {
  width: 250px;
  min-width: 250px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
  position: sticky;
  top: 1rem;
}

.sidebar-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--surface-border);
}

.sidebar-title {
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  letter-spacing: 0.03em;
}

.type-list {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 160px);
  overflow-y: auto;
}

.type-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 1rem;
  border: none;
  border-bottom: 1px solid var(--surface-border);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: all 0.12s;
  font-family: var(--font-body);
}

.type-item:last-child {
  border-bottom: none;
}

.type-item:hover {
  background: rgba(32, 108, 245, 0.05);
}

.type-item.active {
  background: rgba(32, 108, 245, 0.1);
  border-left: 3px solid #5a9aff;
  padding-left: calc(1rem - 3px);
}

.type-item.type-item-zero {
  opacity: 0.55;
}

.type-item.type-item-zero:hover {
  opacity: 0.8;
}

.type-item-label {
  font-size: 0.82rem;
  color: var(--text-color);
  text-transform: capitalize;
  line-height: 1.3;
  flex: 1;
}

.type-item.active .type-item-label {
  color: #5a9aff;
  font-weight: 500;
}

.type-item-count {
  font-size: 0.72rem;
  font-weight: 600;
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.1rem 0.4rem;
  border-radius: 10px;
  min-width: 1.6rem;
  text-align: center;
}

.type-item-count.count-zero {
  background: rgba(107, 114, 128, 0.12);
  color: var(--text-color-secondary);
}

/* --- Right content --- */
.main-content {
  flex: 1;
  min-width: 0;
}

/* --- Scan bar --- */
.scan-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem 1rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  gap: 1rem;
  margin-bottom: 1rem;
}

.scan-bar-info {
  flex: 1;
}

.scan-bar-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
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
.scan-btn:hover:not(:disabled) { box-shadow: 0 0 14px rgba(32, 108, 245, 0.35); }
.scan-btn:disabled { opacity: 0.8; cursor: default; }
.scan-btn-running { background: rgba(32, 108, 245, 0.2); color: #5a9aff; }

/* --- Progress card --- */
.progress-card {
  background: rgba(32, 108, 245, 0.06);
  border: 1px solid rgba(32, 108, 245, 0.2);
  border-radius: 10px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
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
  margin-bottom: 1rem;
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

/* --- Table --- */
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
.table-row { transition: background 0.1s; }
.table-row:hover { background: rgba(32, 108, 245, 0.05); }

.service-badge {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  text-transform: capitalize;
}

.resource-id { font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-color-secondary); }
.resource-id-link {
  cursor: pointer;
  color: #5a9aff;
  transition: all 0.15s;
}
.resource-id-link:hover {
  text-decoration: underline;
}

.account-id { font-family: var(--font-mono); font-size: 0.8rem; }

/* --- Pagination --- */
.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--surface-border);
}

.pagination-info { font-size: 0.8rem; color: var(--text-color-secondary); }

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
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
}
.filter-select:focus { outline: none; border-color: var(--primary-color); }

.page-size-select {
  min-width: 100px;
  padding: 0.35rem 0.5rem;
  font-size: 0.8rem;
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
.btn:disabled { opacity: 0.5; cursor: default; }
.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}
.btn-secondary:hover:not(:disabled) { background: var(--surface-card); }
.btn-sm { padding: 0.35rem 0.75rem; font-size: 0.8rem; }

/* --- States --- */
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

/* --- Spinner --- */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.pi-spin { animation: spin 1s linear infinite; }

/* --- Notes column + expansion panel --- */
.notes-col {
  width: 1%;
  white-space: nowrap;
  text-align: right;
}
.rec-row { cursor: pointer; }
.rec-row.rec-row-open {
  background: rgba(32, 108, 245, 0.05);
}
.notes-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 2px 9px;
  border-radius: 10px;
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-size: 0.75rem;
}
.notes-chip.notes-chip-has {
  background: rgba(32, 108, 245, 0.15);
  color: var(--primary-color);
}
.notes-chip i { font-size: 0.72rem; }

.notes-panel-row td {
  padding: 0 !important;
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}
.notes-panel {
  padding: 0.85rem 1rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.notes-header {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-color-secondary);
}
.notes-header .muted { text-transform: none; letter-spacing: 0; opacity: 0.75; }
.notes-empty { font-size: 0.85rem; padding: 0.3rem 0; }
.notes-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.note-item {
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-card);
}
.note-body {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.87rem;
  line-height: 1.45;
  color: var(--text-color);
}
.note-meta {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.3rem;
  font-size: 0.72rem;
  color: var(--text-color-secondary);
}
.note-meta .muted { opacity: 0.7; }
.note-actions { margin-left: auto; display: flex; gap: 0.25rem; }
.btn-icon {
  background: transparent;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 2px 5px;
  border-radius: 4px;
}
.btn-icon:hover { background: rgba(32, 108, 245, 0.1); color: var(--text-color); }

.note-compose {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
}
.note-compose textarea {
  flex: 1;
  min-height: 56px;
  resize: vertical;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  padding: 0.45rem 0.6rem;
  color: var(--text-color);
  font-family: inherit;
  font-size: 0.85rem;
}
.note-compose button { align-self: flex-end; }

.note-edit textarea {
  width: 100%;
  resize: vertical;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  padding: 0.45rem 0.6rem;
  color: var(--text-color);
  font-family: inherit;
  font-size: 0.85rem;
}
.note-edit-actions { display: flex; gap: 0.4rem; margin-top: 0.4rem; }

.notes-error {
  color: #fecaca;
  background: rgba(220, 38, 38, 0.12);
  border: 1px solid rgba(220, 38, 38, 0.4);
  padding: 0.4rem 0.65rem;
  border-radius: 5px;
  font-size: 0.8rem;
}
</style>

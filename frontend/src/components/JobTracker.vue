<template>
  <div v-if="job" class="job-tracker" :class="[statusClass, modeClass]">
    <div class="job-header">
      <div class="job-info">
        <i :class="typeIcon"></i>
        <span class="job-type">{{ typeLabel }}</span>
      </div>
      <div class="job-header-right">
        <span v-if="elapsedTime" class="job-elapsed">{{ elapsedTime }}</span>
        <span class="job-status-badge">
          <i v-if="job.status === 'running' || job.status === 'cancelling'" class="pi pi-spin pi-spinner"></i>
          <i v-else-if="job.status === 'completed'" class="pi pi-check-circle"></i>
          <i v-else-if="job.status === 'failed'" class="pi pi-times-circle"></i>
          <i v-else-if="job.status === 'cancelled'" class="pi pi-ban"></i>
          <i v-else class="pi pi-clock"></i>
          {{ statusLabel }}
        </span>
      </div>
    </div>

    <template v-if="(job.status === 'running' || job.status === 'cancelling') && pd">
      <div class="stats-bar">
        <div class="stat-box" v-if="pd.account_id">
          <span class="stat-val stat-acct">{{ pd.account_id }}</span>
          <span class="stat-lbl">Account</span>
        </div>
        <div class="stat-box">
          <span class="stat-val">{{ pd.total_resources ?? 0 }}</span>
          <span class="stat-lbl">Resources</span>
        </div>
        <div class="stat-box">
          <span class="stat-val">{{ pd.completed_jobs ?? 0 }}/{{ pd.total_jobs ?? 0 }}</span>
          <span class="stat-lbl">Services</span>
        </div>
        <div class="stat-box" v-if="(pd.errors_count ?? 0) > 0">
          <span class="stat-val stat-err">{{ pd.errors_count }}</span>
          <span class="stat-lbl">Errors</span>
        </div>
        <div class="stat-box" v-if="permissionErrorCount > 0">
          <span class="stat-val stat-err">{{ permissionErrorCount }}</span>
          <span class="stat-lbl">Denied</span>
        </div>
        <div class="stat-box" v-if="(pd.warnings_count ?? 0) > 0">
          <span class="stat-val stat-warn">{{ pd.warnings_count }}</span>
          <span class="stat-lbl">Warnings</span>
        </div>
      </div>
      <div class="progress-track">
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" :style="{ width: job.progress + '%' }"></div>
        </div>
        <span class="progress-pct">{{ job.progress }}%</span>
      </div>
      <div v-if="pd.current_service" class="active-scan">
        <i class="pi pi-spin pi-spinner"></i>
        Scanning {{ pd.current_service }}<span v-if="pd.current_region">/{{ pd.current_region }}</span>...
      </div>
    </template>

    <template v-else-if="job.status === 'running' || job.status === 'cancelling'">
      <div class="progress-track">
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" :style="{ width: job.progress + '%' }"></div>
        </div>
        <span class="progress-pct">{{ job.progress }}%</span>
      </div>
      <div class="active-scan">
        <i class="pi pi-spin pi-spinner"></i>
        {{ job.progress_message || 'Processing...' }}
      </div>
    </template>

    <div v-if="job.status === 'completed' && job.result" class="job-result">
      <div v-if="job.job_type === 'scan'" class="stats-bar">
        <div class="stat-box">
          <span class="stat-val stat-ok">{{ job.result.total_resources ?? 0 }}</span>
          <span class="stat-lbl">Resources</span>
        </div>
        <div class="stat-box">
          <span class="stat-val stat-ok">{{ Object.keys(job.result.by_service || {}).length }}</span>
          <span class="stat-lbl">Services</span>
        </div>
        <div class="stat-box">
          <span class="stat-val stat-ok">{{ Object.keys(job.result.by_region || {}).length }}</span>
          <span class="stat-lbl">Regions</span>
        </div>
        <div class="stat-box" v-if="permissionErrorCount > 0">
          <span class="stat-val stat-err">{{ permissionErrorCount }}</span>
          <span class="stat-lbl">Denied</span>
        </div>
      </div>
      <div v-else-if="job.job_type === 'delete'" class="stats-bar">
        <div class="stat-box">
          <span class="stat-val stat-ok">{{ job.result.deleted ?? 0 }}</span>
          <span class="stat-lbl">Deleted</span>
        </div>
      </div>
      <div v-else class="result-text">Completed successfully</div>
    </div>

    <div v-if="permissionErrorCount > 0" class="job-permissions">
      <div class="permission-title">
        <i class="pi pi-lock"></i>
        {{ permissionErrorCount }} permission error{{ permissionErrorCount === 1 ? '' : 's' }}
      </div>
      <div v-if="skippedResourceTypes.length" class="permission-skipped">
        Not collected: {{ skippedResourceTypes.join(', ') }}
      </div>
      <div v-for="(detail, idx) in visiblePermissionDetails" :key="idx" class="permission-item">
        <div class="permission-message">
          <span v-if="detail.account_id" class="permission-account">{{ detail.account_id }}</span>
          {{ detail.service || 'Unknown service' }}<span v-if="detail.region">/{{ detail.region }}</span>
          <span v-if="detail.code" class="permission-code">{{ detail.code }}</span>
        </div>
        <div v-if="detail.resource_name" class="permission-types">{{ detail.resource_name }}</div>
        <div v-if="detail.message" class="permission-suggestion">{{ detail.message }}</div>
        <div v-if="detail.resource_types?.length" class="permission-types">
          {{ detail.resource_types.join(', ') }}
        </div>
        <div v-if="detail.suggestion" class="permission-suggestion">{{ detail.suggestion }}</div>
      </div>
      <div v-if="permissionDetails.length > visiblePermissionDetails.length" class="permission-more">
        {{ permissionDetails.length - visiblePermissionDetails.length }} more permission error{{ permissionDetails.length - visiblePermissionDetails.length === 1 ? '' : 's' }}
      </div>
    </div>

    <div v-if="scanWarnings.length" class="job-warnings">
      <div class="warning-title">
        <i class="pi pi-exclamation-triangle"></i>
        {{ scanWarnings.length }} scan warning{{ scanWarnings.length === 1 ? '' : 's' }}
      </div>
      <div v-for="(warning, idx) in visibleWarnings" :key="idx" class="warning-item">
        <div class="warning-message">{{ warning.message }}</div>
        <div v-if="warning.suggestion" class="warning-suggestion">{{ warning.suggestion }}</div>
        <RouterLink
          v-if="warning.action_route"
          class="warning-action"
          :to="warning.action_route"
        >
          {{ warning.action_label || 'Open' }}
        </RouterLink>
      </div>
      <div v-if="scanWarnings.length > visibleWarnings.length" class="warning-more">
        {{ scanWarnings.length - visibleWarnings.length }} more warning{{ scanWarnings.length - visibleWarnings.length === 1 ? '' : 's' }}
      </div>
    </div>

    <div v-if="job.status === 'failed'" class="job-error">
      <i class="pi pi-exclamation-triangle"></i>
      {{ job.error || 'Job failed' }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PermissionErrorDetail, ScanJob, ScanWarning } from '@/types/api'

const props = withDefaults(defineProps<{
  job: ScanJob | null
  mode?: 'inline' | 'compact'
}>(), { mode: 'inline' })

const pd = computed(() => {
  if (!props.job || (props.job.status !== 'running' && props.job.status !== 'cancelling')) return null
  return props.job.progress_data ?? null
})

const modeClass = computed(() => props.mode === 'compact' ? 'tracker-compact' : '')
const statusClass = computed(() => props.job ? `status-${props.job.status}` : '')

const typeIcon = computed(() => {
  switch (props.job?.status) {
    case 'running': return 'pi pi-sync'
    default: return 'pi pi-cog'
  }
})

const typeLabel = computed(() => {
  switch (props.job?.status) {
    default: return 'Resource Scan'
  }
})

const statusLabel = computed(() => {
  switch (props.job?.status) {
    case 'pending': return 'Queued'
    case 'running': return 'Running'
    case 'cancelling': return 'Stopping'
    case 'completed': return 'Completed'
    case 'failed': return 'Failed'
    case 'cancelled': return 'Cancelled'
    default: return props.job?.status ?? ''
  }
})

const elapsedTime = computed(() => {
  if (!props.job) return null
  const start = props.job.started_at ? new Date(props.job.started_at) : new Date(props.job.created_at)
  const end = props.job.completed_at ? new Date(props.job.completed_at) : new Date()
  if (props.job.status === 'pending') return null
  const seconds = Math.floor((end.getTime() - start.getTime()) / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${seconds % 60}s`
})

const scanWarnings = computed<ScanWarning[]>(() => {
  const progressWarnings = props.job?.progress_data?.warnings
  if (Array.isArray(progressWarnings) && progressWarnings.length) return progressWarnings
  const resultWarnings = props.job?.result?.warnings
  if (Array.isArray(resultWarnings)) return resultWarnings as unknown as ScanWarning[]
  return []
})

const visibleWarnings = computed(() => scanWarnings.value.slice(0, props.mode === 'compact' ? 2 : 4))

const permissionDetails = computed<PermissionErrorDetail[]>(() => {
  const progressDetails = props.job?.progress_data?.permission_error_details
  if (Array.isArray(progressDetails) && progressDetails.length) return progressDetails
  const resultDetails = props.job?.result?.permission_error_details
  if (Array.isArray(resultDetails)) return resultDetails as unknown as PermissionErrorDetail[]
  return []
})

const skippedResourceTypes = computed(() => {
  const progressTypes = props.job?.progress_data?.permission_error_resource_types
  if (Array.isArray(progressTypes) && progressTypes.length) return progressTypes
  const resultTypes = props.job?.result?.permission_error_resource_types
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
  const progressCount = props.job?.progress_data?.permission_errors_count
  if (typeof progressCount === 'number') return progressCount
  const resultCount = props.job?.result?.permission_errors
  if (typeof resultCount === 'number') return resultCount
  if (typeof resultCount === 'string') return Number(resultCount) || 0
  return permissionDetails.value.length
})

const visiblePermissionDetails = computed(() => permissionDetails.value.slice(0, props.mode === 'compact' ? 2 : 5))
</script>

<style scoped>
.job-tracker { padding: 1rem 1.25rem; border-radius: 10px; border: 1px solid var(--surface-border); background: var(--surface-card); font-size: 0.85rem; }
.tracker-compact { padding: 0.75rem 1rem; font-size: 0.8rem; }
.job-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }
.job-info { display: flex; align-items: center; gap: 0.5rem; }
.job-info i { font-size: 1rem; color: var(--primary-color); }
.job-type { font-weight: 600; }
.job-header-right { display: flex; align-items: center; gap: 0.65rem; }
.job-elapsed { font-size: 0.72rem; color: var(--text-color-secondary); }
.job-status-badge { display: flex; align-items: center; gap: 0.35rem; font-size: 0.78rem; padding: 0.25rem 0.6rem; border-radius: 12px; font-weight: 500; }
.status-pending .job-status-badge { background: var(--surface-ground); color: var(--text-color-secondary); }
.status-running .job-status-badge { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.status-completed .job-status-badge { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.status-failed .job-status-badge { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.stats-bar { display: flex; gap: 1.25rem; margin-bottom: 0.75rem; }
.stat-box { display: flex; flex-direction: column; align-items: center; }
.stat-val { font-size: 1.2rem; font-weight: 700; line-height: 1.2; }
.stat-ok { color: #4ade80; }
.stat-err { color: #ef4444; }
.stat-warn { color: #facc15; }
.stat-acct { color: #5a9aff; font-family: var(--font-mono, monospace); font-size: 0.72rem; }
.stat-lbl { font-size: 0.65rem; text-transform: uppercase; font-weight: 500; color: var(--text-color-secondary); }
.progress-track { display: flex; align-items: center; gap: 0.65rem; margin-bottom: 0.5rem; }
.progress-bar-bg { flex: 1; height: 8px; background: var(--surface-border); border-radius: 4px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #2563eb); transition: width 0.3s ease; border-radius: 4px; }
.progress-pct { font-size: 0.78rem; font-weight: 600; color: var(--primary-color); min-width: 32px; text-align: right; }
.active-scan { display: flex; align-items: center; gap: 0.4rem; font-size: 0.78rem; color: var(--text-color-secondary); margin-bottom: 0.5rem; }
.active-scan i { font-size: 0.72rem; color: var(--primary-color); }
.job-result { background: rgba(34, 197, 94, 0.12); border-radius: 8px; padding: 0.75rem; margin-top: 0.5rem; }
.job-result .stats-bar { margin-bottom: 0; }
.job-result .stat-val { color: #4ade80; }
.result-text { color: #4ade80; font-weight: 500; }
.job-error { display: flex; align-items: flex-start; gap: 0.5rem; padding: 0.75rem; background: rgba(239, 68, 68, 0.1); border-radius: 8px; color: #ef4444; font-size: 0.8rem; margin-top: 0.5rem; }
.job-error i { flex-shrink: 0; margin-top: 0.1rem; }
.job-warnings { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.75rem; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.25); border-radius: 8px; color: #facc15; font-size: 0.8rem; margin-top: 0.5rem; }
.warning-title { display: flex; align-items: center; gap: 0.45rem; font-weight: 600; }
.warning-item { border-top: 1px solid rgba(234, 179, 8, 0.2); padding-top: 0.5rem; }
.warning-message { color: var(--text-color); line-height: 1.35; }
.warning-suggestion { margin-top: 0.25rem; color: var(--text-color-secondary); line-height: 1.35; }
.warning-action { display: inline-flex; margin-top: 0.45rem; color: #5a9aff; text-decoration: none; font-weight: 600; }
.warning-action:hover { text-decoration: underline; }
.warning-more { color: var(--text-color-secondary); font-size: 0.74rem; }
.job-permissions { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.75rem; background: rgba(239, 68, 68, 0.09); border: 1px solid rgba(239, 68, 68, 0.24); border-radius: 8px; color: #f87171; font-size: 0.8rem; margin-top: 0.5rem; }
.permission-title { display: flex; align-items: center; gap: 0.45rem; font-weight: 600; }
.permission-skipped { color: var(--text-color); line-height: 1.35; }
.permission-item { border-top: 1px solid rgba(239, 68, 68, 0.2); padding-top: 0.5rem; }
.permission-message { color: var(--text-color); line-height: 1.35; }
.permission-account { color: #5a9aff; font-family: var(--font-mono, monospace); margin-right: 0.25rem; }
.permission-code { color: #f87171; margin-left: 0.25rem; }
.permission-types, .permission-suggestion, .permission-more { margin-top: 0.25rem; color: var(--text-color-secondary); line-height: 1.35; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.pi-spin { animation: spin 1s linear infinite; }
</style>

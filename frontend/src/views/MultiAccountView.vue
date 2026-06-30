<template>
  <div class="ma-view">
    <ProBadge feature="cross_account" label="Multi-Account Management">
    <!-- Header -->
    <div class="ma-header">
      <div class="ma-header-left">
        <button class="btn-back" @click="router.push('/setup')" title="Back to Setup">
          <i class="pi pi-arrow-left"></i>
        </button>
        <h2 class="ma-title">Multi-Account Management</h2>
      </div>
      <button class="btn btn-primary" :disabled="statusLoading" @click="refresh">
        <i class="pi pi-refresh" :class="{ spin: statusLoading }"></i>
        Refresh
      </button>
    </div>

    <!-- Pre-flight Validation Warning -->
    <div v-if="validation && !validation.can_deploy && !validation.error" class="preflight-warning">
      <div class="preflight-header">
        <i class="pi pi-exclamation-triangle"></i>
        <strong>Cannot deploy from this account</strong>
      </div>
      <p v-if="validation.guidance" class="preflight-guidance">{{ validation.guidance }}</p>
      <div v-if="validation.current_account_id" class="preflight-details">
        <span>Current: {{ validation.current_account_id }}</span>
        <span v-if="validation.management_account_id">Management: {{ validation.management_account_id }}</span>
      </div>
    </div>

    <!-- Pre-flight Error -->
    <div v-if="validation?.error" class="preflight-error">
      <i class="pi pi-times-circle"></i>
      <div>
        <strong>{{ validation.error }}</strong>
        <p v-if="validation.guidance">{{ validation.guidance }}</p>
      </div>
    </div>

    <!-- Job Progress Banner (from jobs store - persists across navigation) -->
    <div v-if="activeJob && activeJob.status === 'running'" class="job-banner">
      <div class="job-banner-body">
        <i class="pi pi-spin pi-spinner"></i>
        <div class="job-banner-text">
          <strong>{{ jobLabel }}</strong>
          <span v-if="activeJob.progress_message">{{ activeJob.progress_message }}</span>
        </div>
      </div>
      <div class="job-progress-bar">
        <div class="job-progress-fill" :style="{ width: (activeJob.progress || 0) + '%' }"></div>
      </div>
    </div>

    <!-- Job Completed Banner -->
    <div v-if="activeJob && activeJob.status === 'completed'" class="result-banner result-success">
      <i class="pi pi-check-circle"></i>
      <span>{{ (activeJob.result?.message as string) || 'Operation completed successfully' }}</span>
      <button class="btn-dismiss" @click="jobsStore.clearCurrentMultiAccount()"><i class="pi pi-times"></i></button>
    </div>

    <!-- Job Failed Banner (enhanced error display) -->
    <div v-if="activeJob && activeJob.status === 'failed'" class="result-banner result-error">
      <div class="error-content">
        <div class="error-header">
          <i class="pi pi-times-circle"></i>
          <strong>{{ jobLabel?.replace('...', '') }} Failed</strong>
          <button class="btn-dismiss" @click="jobsStore.clearCurrentMultiAccount()"><i class="pi pi-times"></i></button>
        </div>
        <p class="error-message">{{ activeJob.error || 'Unknown error' }}</p>
        <div class="error-actions">
          <a
            v-if="cfnConsoleUrl"
            :href="cfnConsoleUrl"
            target="_blank"
            rel="noopener"
            class="btn btn-secondary btn-sm"
          >
            <i class="pi pi-external-link"></i> View in CloudFormation
          </a>
          <button
            v-if="showErrorDetails"
            class="btn btn-secondary btn-sm"
            @click="errorDetailsExpanded = !errorDetailsExpanded"
          >
            {{ errorDetailsExpanded ? 'Hide Details' : 'Show Details' }}
          </button>
        </div>
        <pre v-if="errorDetailsExpanded && activeJob.error" class="error-details">{{ activeJob.error }}</pre>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="statusLoading && !stackSetStatus" class="loading-state">
      <i class="pi pi-spin pi-spinner"></i> Loading StackSet status...
    </div>

    <!-- Error State -->
    <div v-else-if="statusError" class="error-state">
      <i class="pi pi-exclamation-triangle"></i>
      <p>{{ statusError }}</p>
      <button class="btn btn-primary" @click="refresh">Retry</button>
    </div>

    <template v-else-if="stackSetStatus">
      <!-- Status Card -->
      <div class="status-card" :class="statusCardClass">
        <div class="status-card-header">
          <div class="status-badge" :class="statusBadgeClass">
            <i :class="statusBadgeIcon"></i>
            {{ statusBadgeLabel }}
          </div>
          <div v-if="stackSetStatus.exists && stackSetStatus.template_version" class="version-info">
            <span class="version-label">Template:</span>
            <span class="version-value">{{ stackSetStatus.template_version }}</span>
            <span v-if="stackSetStatus.versions_match === false" class="version-outdated">
              (update available: {{ stackSetStatus.local_version }})
            </span>
          </div>
        </div>
        <div class="status-card-body">
          <div v-if="stackSetStatus.exists" class="status-stats">
            <div class="status-stat">
              <span class="status-stat-value">{{ stackSetStatus.instance_count }}</span>
              <span class="status-stat-label">Stack Instances</span>
            </div>
            <div class="status-stat">
              <span class="status-stat-value">{{ currentInstances }}</span>
              <span class="status-stat-label">Current</span>
            </div>
            <div class="status-stat">
              <span class="status-stat-value">{{ failedInstances }}</span>
              <span class="status-stat-label">Failed / Outdated</span>
            </div>
          </div>
          <div v-else class="empty-status">
            <p>No StackSet deployed. Deploy cross-account infrastructure to manage resources across your AWS Organization.</p>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="actions-row">
        <template v-if="!stackSetStatus.exists">
          <button
            class="btn btn-primary"
            :disabled="isJobActive || !canDeploy"
            @click="handleDeploy"
          >
            <i class="pi pi-cloud-upload"></i> Deploy StackSet
          </button>
          <button
            class="btn btn-warning"
            :disabled="isJobActive || !canDeploy"
            @click="confirmClean"
          >
            <i class="pi pi-refresh"></i> Clean &amp; Redeploy
          </button>
        </template>
        <template v-else>
          <button
            class="btn btn-primary"
            :disabled="isJobActive || !canDeploy"
            @click="handleUpdate"
          >
            <i class="pi pi-sync"></i> Update Template
          </button>
          <button
            class="btn btn-warning"
            :disabled="isJobActive || !canDeploy"
            @click="confirmClean"
          >
            <i class="pi pi-refresh"></i> Clean &amp; Redeploy
          </button>
          <button
            class="btn btn-danger"
            :disabled="isJobActive || !canDeploy"
            @click="confirmRemove"
          >
            <i class="pi pi-trash"></i> Remove All
          </button>
        </template>
      </div>

      <!-- Instances Table -->
      <div v-if="stackSetStatus.exists && stackSetStatus.instances.length" class="section-card">
        <div class="section-header">
          <h3 class="section-title">Stack Instances</h3>
          <span class="instance-count">{{ stackSetStatus.instances.length }} instances</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Account ID</th>
                <th>Region</th>
                <th>Status</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="inst in stackSetStatus.instances" :key="inst.account_id + inst.region">
                <td class="mono">{{ inst.account_id }}</td>
                <td>{{ inst.region }}</td>
                <td>
                  <span class="inst-status" :class="'inst-' + inst.status.toLowerCase()">
                    {{ inst.status }}
                  </span>
                </td>
                <td class="status-reason">{{ inst.status_reason || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Tracked Accounts Table -->
      <div v-if="accounts.length" class="section-card">
        <div class="section-header">
          <h3 class="section-title">Tracked Accounts</h3>
          <span class="instance-count">{{ accounts.length }} accounts</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Account ID</th>
                <th>Name</th>
                <th>Discovery</th>
                <th>Access</th>
                <th>Resources</th>
                <th>Last Discovery</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="acc in accounts" :key="acc.account_id">
                <td class="mono">{{ acc.account_id }}</td>
                <td>{{ acc.account_name || '-' }}</td>
                <td>
                  <span class="disc-badge" :class="acc.enabled_for_discovery ? 'disc-on' : 'disc-off'">
                    {{ acc.enabled_for_discovery ? 'Enabled' : 'Disabled' }}
                  </span>
                </td>
                <td>
                  <span v-if="acc.access_check_status" class="access-badge" :class="'access-' + acc.access_check_status">
                    {{ acc.access_check_status }}
                  </span>
                  <span v-else>-</span>
                </td>
                <td>{{ acc.total_resources_discovered ?? '-' }}</td>
                <td>{{ formatDate(acc.last_discovery_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- CloudFormation Templates -->
      <div class="section-card">
        <div class="section-header">
          <h3 class="section-title">CloudFormation Templates</h3>
        </div>
        <div class="template-list">
          <div v-for="tpl in templateNames" :key="tpl" class="template-item">
            <div class="template-item-header">
              <div class="template-item-info">
                <span class="template-name">{{ tpl }}</span>
                <span v-if="templateMeta[tpl]" class="template-desc">{{ templateMeta[tpl].description }}</span>
              </div>
              <div class="template-actions">
                <a
                  v-if="templateMeta[tpl]?.public_url"
                  :href="templateMeta[tpl].public_url"
                  target="_blank"
                  rel="noopener"
                  class="btn btn-secondary btn-sm"
                >
                  <i class="pi pi-download"></i> Download
                </a>
                <button class="btn btn-secondary btn-sm" @click="toggleTemplate(tpl)">
                  <i class="pi" :class="showTemplates[tpl] ? 'pi-eye-slash' : 'pi-eye'"></i>
                  {{ showTemplates[tpl] ? 'Hide' : 'View' }}
                </button>
              </div>
            </div>
            <div v-if="templateLoadingMap[tpl]" class="template-loading">
              <i class="pi pi-spin pi-spinner"></i> Loading template...
            </div>
            <div v-else-if="showTemplates[tpl] && templateContents[tpl]" class="template-content">
              <pre>{{ templateContents[tpl] }}</pre>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Remove Confirmation Dialog -->
    <div v-if="showRemoveConfirm" class="dialog-overlay" @click.self="showRemoveConfirm = false">
      <div class="dialog">
        <h3>Remove All Infrastructure</h3>
        <p>This will delete the BlueArch StackSet, all stack instances in member accounts, and clear tracked account data.</p>
        <p class="dialog-warning">This action cannot be undone.</p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="showRemoveConfirm = false">Cancel</button>
          <button class="btn btn-danger" @click="handleRemove">Remove</button>
        </div>
      </div>
    </div>

    <!-- Clean & Redeploy Confirmation Dialog -->
    <div v-if="showCleanConfirm" class="dialog-overlay" @click.self="showCleanConfirm = false">
      <div class="dialog">
        <h3>Clean &amp; Redeploy</h3>
        <p>This will delete orphaned resources from a previous failed BlueArch deployment (DynamoDB tables, IAM policies, and roles) before redeploying the management stack.</p>
        <p>Use this when a deploy fails due to pre-existing resources from a previous attempt.</p>
        <p class="dialog-warning">Orphaned resources will be permanently deleted.</p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="showCleanConfirm = false">Cancel</button>
          <button class="btn btn-warning" @click="handleClean">Clean &amp; Redeploy</button>
        </div>
      </div>
    </div>
    </ProBadge>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { api } from '@/api/client'
import { useJobsStore } from '@/stores/jobs'
import { useLicenseStore } from '@/stores/license'
import { useMultiAccountStore } from '@/stores/multiAccount'
import ProBadge from '@/components/ProBadge.vue'

const router = useRouter()
const jobsStore = useJobsStore()
const multiAccountStore = useMultiAccountStore()
const {
  accounts,
  stackSetStatus,
  statusError,
  statusLoading,
  validation,
} = storeToRefs(multiAccountStore)

const errorDetailsExpanded = ref(false)

const showRemoveConfirm = ref(false)
const showCleanConfirm = ref(false)
const isCleanDeploy = ref(false)

const templateNames = multiAccountStore.templateNames
const templateMeta = multiAccountStore.templateMeta
const templateContents = reactive<Record<string, string>>({})
const templateLoadingMap = reactive<Record<string, boolean>>({})
const showTemplates = reactive<Record<string, boolean>>({})

// Use jobs store for active job (persists across navigation)
const activeJob = computed(() => jobsStore.currentMultiAccountJob)
const isJobActive = computed(
  () => activeJob.value?.status === 'running' || activeJob.value?.status === 'pending',
)
const canDeploy = computed(() => validation.value?.can_deploy !== false)

// Computed
const currentInstances = computed(
  () => stackSetStatus.value?.instances.filter((i) => i.status === 'CURRENT').length ?? 0,
)

const failedInstances = computed(
  () =>
    stackSetStatus.value?.instances.filter((i) =>
      ['OUTDATED', 'INOPERABLE', 'FAILED'].includes(i.status),
    ).length ?? 0,
)

const statusCardClass = computed(() => {
  if (!stackSetStatus.value?.exists) return 'status-not-deployed'
  if (stackSetStatus.value.status === 'ACTIVE' && failedInstances.value === 0) return 'status-healthy'
  if (failedInstances.value > 0) return 'status-degraded'
  return 'status-unknown'
})

const statusBadgeClass = computed(() => {
  if (!stackSetStatus.value?.exists) return 'badge-neutral'
  if (stackSetStatus.value.status === 'ACTIVE' && failedInstances.value === 0) return 'badge-success'
  if (failedInstances.value > 0) return 'badge-warning'
  return 'badge-neutral'
})

const statusBadgeIcon = computed(() => {
  if (!stackSetStatus.value?.exists) return 'pi pi-minus-circle'
  if (stackSetStatus.value.status === 'ACTIVE' && failedInstances.value === 0) return 'pi pi-check-circle'
  if (failedInstances.value > 0) return 'pi pi-exclamation-triangle'
  return 'pi pi-question-circle'
})

const statusBadgeLabel = computed(() => {
  if (!stackSetStatus.value?.exists) return 'Not Deployed'
  if (stackSetStatus.value.status === 'ACTIVE' && failedInstances.value === 0) return 'Active'
  if (failedInstances.value > 0) return 'Degraded'
  return stackSetStatus.value.status || 'Unknown'
})

const jobLabel = computed(() => {
  if (!activeJob.value) return ''
  switch (activeJob.value.job_type) {
    case 'multi_account_deploy':
      return isCleanDeploy.value ? 'Cleaning & redeploying StackSet...' : 'Deploying StackSet...'
    case 'multi_account_update':
      return 'Updating StackSet...'
    case 'multi_account_remove':
      return 'Removing infrastructure...'
    default:
      return 'Running...'
  }
})

const showErrorDetails = computed(() => {
  return activeJob.value?.error && activeJob.value.error.length > 80
})

const cfnConsoleUrl = computed(() => {
  if (!activeJob.value?.error) return null
  const regionMatch = activeJob.value.error.match(/([a-z]{2}-[a-z]+-\d)/)
  const region = regionMatch?.[1] || 'us-east-1'
  return `https://${region}.console.aws.amazon.com/cloudformation/home?region=${region}#/stacksets`
})

// Watch for job completion to auto-refresh status
watch(activeJob, (job, oldJob) => {
  if (oldJob && job) {
    if (
      (oldJob.status === 'running' || oldJob.status === 'pending') &&
      (job.status === 'completed' || job.status === 'failed')
    ) {
      multiAccountStore.refresh()
    }
  }
})

// Data fetching
async function refresh() {
  await multiAccountStore.refresh()
}

// Actions (use jobs store for cross-page persistence)
async function handleDeploy() {
  isCleanDeploy.value = false
  try {
    await jobsStore.submitMultiAccountJob('deploy', {})
  } catch {
    // Error handled in store
  }
}

async function handleUpdate() {
  try {
    await jobsStore.submitMultiAccountJob('update')
  } catch {
    // Error handled in store
  }
}

function confirmRemove() {
  showRemoveConfirm.value = true
}

function confirmClean() {
  showCleanConfirm.value = true
}

async function handleClean() {
  showCleanConfirm.value = false
  isCleanDeploy.value = true
  try {
    await jobsStore.submitMultiAccountJob('clean')
  } catch {
    // Error handled in store
  }
}

async function handleRemove() {
  showRemoveConfirm.value = false
  try {
    await jobsStore.submitMultiAccountJob('remove')
  } catch {
    // Error handled in store
  }
}

// Template viewer
async function toggleTemplate(name: string) {
  if (showTemplates[name]) {
    showTemplates[name] = false
    return
  }
  if (!templateContents[name]) {
    templateLoadingMap[name] = true
    try {
      const detail = await api.getTemplate(name)
      templateContents[name] = detail.content
      if (!templateMeta[name]) {
        templateMeta[name] = {
          name: detail.name,
          description: detail.description,
          public_url: detail.public_url,
          version: detail.version,
        }
      }
    } catch {
      templateContents[name] = '# Failed to load template'
    } finally {
      templateLoadingMap[name] = false
    }
  }
  showTemplates[name] = true
}

// Helpers
function formatDate(iso?: string | null): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

const licenseStore = useLicenseStore()

onMounted(async () => {
  await licenseStore.load({ background: true })
  if (!licenseStore.isFeatureAllowed('cross_account')) return
  multiAccountStore.load({ background: true })
  multiAccountStore.loadTemplateMeta({ background: true })
  // Recover any in-flight multi-account job after page reload
  jobsStore.fetchMultiAccountJobs({ background: true })
})
</script>

<style scoped>
.ma-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* Header */
.ma-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ma-header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.btn-back {
  background: none;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
  cursor: pointer;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
  transition: all 0.15s;
}

.btn-back:hover {
  background: var(--surface-ground);
  color: var(--text-color);
}

.ma-title {
  font-size: 1.1rem;
  font-weight: 600;
}

/* Pre-flight Warning */
.preflight-warning {
  background: #fefce8;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 1rem 1.25rem;
}

.preflight-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #92400e;
  font-size: 0.88rem;
  margin-bottom: 0.5rem;
}

.preflight-guidance {
  font-size: 0.82rem;
  color: #78350f;
  margin: 0.5rem 0;
  white-space: pre-wrap;
  line-height: 1.5;
  font-family: 'SF Mono', monospace;
  background: #fef3c7;
  padding: 0.75rem;
  border-radius: 6px;
}

.preflight-details {
  display: flex;
  gap: 1.5rem;
  font-size: 0.78rem;
  color: #92400e;
  margin-top: 0.5rem;
}

.preflight-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  padding: 1rem 1.25rem;
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  color: #991b1b;
  font-size: 0.88rem;
}

.preflight-error p {
  margin: 0.25rem 0 0;
  font-size: 0.82rem;
  opacity: 0.8;
}

/* Buttons */
.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  transition: all 0.15s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--primary-color);
  color: white;
}
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}
.btn-secondary:hover:not(:disabled) { background: var(--surface-border); }

.btn-warning {
  background: #f59e0b;
  color: white;
}
.btn-warning:hover:not(:disabled) { background: #d97706; }

.btn-danger {
  background: #ef4444;
  color: white;
}
.btn-danger:hover:not(:disabled) { background: #dc2626; }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Job Banner */
.job-banner {
  background: rgba(32, 108, 245, 0.12);
  border: 1px solid rgba(32, 108, 245, 0.25);
  border-radius: 10px;
  padding: 1rem 1.25rem;
}

.job-banner-body {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  color: #5a9aff;
}

.job-banner-text {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.job-banner-text strong { font-size: 0.88rem; }
.job-banner-text span { font-size: 0.78rem; opacity: 0.8; }

.job-progress-bar {
  height: 6px;
  background: rgba(32, 108, 245, 0.15);
  border-radius: 3px;
  overflow: hidden;
}

.job-progress-fill {
  height: 100%;
  background: var(--primary-color);
  border-radius: 3px;
  transition: width 0.3s ease;
}

/* Result Banner */
.result-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.85rem 1.25rem;
  border-radius: 10px;
  border: 1px solid;
  font-size: 0.88rem;
}

.result-success {
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.25);
  color: #4ade80;
}

.result-error {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.25);
  color: #f87171;
}

.error-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.error-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.error-header strong { flex: 1; }

.error-message {
  margin: 0;
  font-size: 0.82rem;
  opacity: 0.9;
}

.error-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.error-details {
  margin: 0.5rem 0 0;
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 6px;
  font-size: 0.75rem;
  font-family: 'SF Mono', monospace;
  white-space: pre-wrap;
  max-height: 260px;
  overflow: auto;
  color: #fca5a5;
}

.btn-dismiss {
  background: none;
  border: none;
  cursor: pointer;
  opacity: 0.5;
  color: inherit;
  padding: 0.2rem;
}
.btn-dismiss:hover { opacity: 1; }

/* Loading / Error */
.loading-state,
.error-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 3rem 1rem;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}

.error-state {
  flex-direction: column;
  color: #f87171;
}

/* Status Card */
.status-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.status-card.status-healthy { border-color: rgba(34, 197, 94, 0.25); }
.status-card.status-degraded { border-color: rgba(234, 179, 8, 0.25); }
.status-card.status-not-deployed { border-color: var(--surface-border); }

.status-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.75rem;
  border-radius: 20px;
  font-size: 0.82rem;
  font-weight: 600;
}

.badge-success { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.badge-warning { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.badge-neutral { background: var(--surface-card-hover); color: var(--text-color-secondary); }

.version-info {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
}

.version-label { color: var(--text-color-secondary); }
.version-value { font-family: 'SF Mono', monospace; color: var(--text-color); }
.version-outdated { color: #ea580c; font-weight: 500; }

.status-card-body { padding: 1.25rem; }

.status-stats { display: flex; gap: 2rem; }

.status-stat {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.status-stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-color);
}

.status-stat-label {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.empty-status p {
  color: var(--text-color-secondary);
  font-size: 0.88rem;
  margin: 0;
}

/* Actions Row */
.actions-row { display: flex; gap: 0.75rem; }

/* Section Card */
.section-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.section-title { font-size: 0.92rem; font-weight: 600; }

.instance-count {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  padding: 0.2rem 0.5rem;
  border-radius: 10px;
}

/* Table */
.table-wrap { overflow-x: auto; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.data-table th {
  text-align: left;
  padding: 0.65rem 1rem;
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}

.data-table td {
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color);
}

.data-table tbody tr:last-child td { border-bottom: none; }
.data-table tbody tr:hover { background: rgba(32, 108, 245, 0.05); }

.mono {
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
}

.status-reason {
  font-size: 0.76rem;
  color: var(--text-color-secondary);
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Instance Status */
.inst-status {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 600;
}

.inst-current { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.inst-outdated { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.inst-inoperable,
.inst-failed { background: rgba(239, 68, 68, 0.15); color: #f87171; }

/* Discovery Badge */
.disc-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 500;
}

.disc-on { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.disc-off { background: var(--surface-card-hover); color: var(--text-color-secondary); }

/* Access Badge */
.access-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 500;
}

.access-ok,
.access-success { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.access-error,
.access-failed { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.access-unknown { background: var(--surface-card-hover); color: var(--text-color-secondary); }

/* Dialog */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.75rem;
  max-width: 420px;
  width: 90%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

.dialog h3 {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.dialog p {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  margin-bottom: 0.5rem;
  line-height: 1.5;
}

.dialog-warning {
  color: #f87171 !important;
  font-weight: 500;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.25rem;
}

/* Template Viewer */
.template-list { display: flex; flex-direction: column; }
.template-item { border-bottom: 1px solid var(--surface-border); }
.template-item:last-child { border-bottom: none; }

.template-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.25rem;
  gap: 1rem;
}

.template-item-info { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
.template-name { font-family: 'SF Mono', monospace; font-size: 0.82rem; font-weight: 600; color: var(--text-color); }
.template-desc { font-size: 0.75rem; color: var(--text-color-secondary); }
.template-actions { display: flex; gap: 0.5rem; flex-shrink: 0; }
.btn-sm { padding: 0.3rem 0.65rem; font-size: 0.78rem; }

.template-loading {
  padding: 1.5rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
  border-top: 1px solid var(--surface-border);
}

.template-content {
  max-height: 500px;
  overflow: auto;
  background: var(--surface-card-hover);
  padding: 1rem;
  border-top: 1px solid var(--surface-border);
}

.template-content pre {
  margin: 0;
  font-size: 0.78rem;
  font-family: 'SF Mono', monospace;
  white-space: pre;
  line-height: 1.5;
  color: var(--text-color);
}
</style>

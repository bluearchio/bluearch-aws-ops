<template>
  <div class="ar-view">
    <!-- Header -->
    <div class="ar-header">
      <div class="ar-header-left">
        <button class="btn-back" @click="router.push('/setup')" title="Back to Setup">
          <i class="pi pi-arrow-left"></i>
        </button>
        <h2 class="ar-title">Assume Role Configuration</h2>
      </div>
      <button class="btn btn-primary" :disabled="statusLoading" @click="refresh">
        <i class="pi pi-refresh" :class="{ spin: statusLoading }"></i>
        Refresh
      </button>
    </div>

    <!-- Job Progress Banner -->
    <div v-if="activeJob" class="job-banner">
      <div class="job-banner-body">
        <i class="pi pi-spin pi-spinner"></i>
        <div class="job-banner-text">
          <strong>{{ jobLabel }}</strong>
          <span v-if="activeJob.progress_message">{{ activeJob.progress_message }}</span>
        </div>
      </div>
      <div class="job-progress-bar">
        <div class="job-progress-fill" :style="{ width: activeJob.progress + '%' }"></div>
      </div>
    </div>

    <!-- Job Result Banner -->
    <div v-if="jobResult" class="result-banner" :class="jobResult.success ? 'result-success' : 'result-error'">
      <i :class="jobResult.success ? 'pi pi-check-circle' : 'pi pi-times-circle'"></i>
      <span>{{ jobResult.message }}</span>
      <button class="btn-dismiss" @click="jobResult = null"><i class="pi pi-times"></i></button>
    </div>

    <!-- Loading State -->
    <div v-if="statusLoading && !status" class="loading-state">
      <i class="pi pi-spin pi-spinner"></i> Loading assume-role status...
    </div>

    <!-- Error State -->
    <div v-else-if="statusError" class="error-state">
      <i class="pi pi-exclamation-triangle"></i>
      <p>{{ statusError }}</p>
      <button class="btn btn-primary" @click="refresh">Retry</button>
    </div>

    <template v-else-if="status">
      <!-- Status Card -->
      <div class="status-card" :class="statusCardClass">
        <div class="status-card-header">
          <div class="status-badge" :class="statusBadgeClass">
            <i :class="statusBadgeIcon"></i>
            {{ statusBadgeLabel }}
          </div>
          <div v-if="status.stack_status" class="stack-info">
            <span class="stack-label">Stack:</span>
            <span class="stack-value" :class="'stack-' + status.stack_status.toLowerCase().replace(/_/g, '-')">
              {{ status.stack_status }}
            </span>
          </div>
        </div>
        <div class="status-card-body">
          <div v-if="status.configured" class="status-details">
            <div class="detail-grid">
              <div class="detail-item">
                <span class="detail-label">Role ARN</span>
                <span class="detail-value mono">{{ status.role_arn || '-' }}</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">Role Name</span>
                <span class="detail-value">{{ status.role_name || '-' }}</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">Account ID</span>
                <span class="detail-value mono">{{ status.account_id || '-' }}</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">External ID</span>
                <span class="detail-value">
                  <span v-if="status.external_id_configured" class="ext-badge ext-yes">Configured</span>
                  <span v-else class="ext-badge ext-no">Not Set</span>
                </span>
              </div>
              <div class="detail-item">
                <span class="detail-label">Last Used</span>
                <span class="detail-value">{{ formatDate(status.last_used_at) }}</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">Status</span>
                <span class="detail-value">
                  <span v-if="status.enabled" class="ext-badge ext-yes">Enabled</span>
                  <span v-else class="ext-badge ext-no">Disabled</span>
                </span>
              </div>
            </div>
          </div>
          <div v-else class="empty-status">
            <p>No assume-role configuration found. Deploy a CloudFormation stack to create an IAM role for cross-account resource management.</p>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="actions-row">
        <template v-if="!status.configured && !status.stack_exists">
          <button
            class="btn btn-primary"
            :disabled="!!activeJob"
            @click="showDeployDialog = true"
          >
            <i class="pi pi-cloud-upload"></i> Deploy Role
          </button>
        </template>
        <template v-else-if="status.configured && !status.enabled">
          <button
            class="btn btn-primary"
            :disabled="!!activeJob"
            @click="showDeployDialog = true"
          >
            <i class="pi pi-cloud-upload"></i> Re-deploy Role
          </button>
          <button
            v-if="status.stack_exists"
            class="btn btn-danger"
            :disabled="!!activeJob"
            @click="showDeleteConfirm = true"
          >
            <i class="pi pi-trash"></i> Delete Stack
          </button>
        </template>
        <template v-else>
          <button
            class="btn btn-primary"
            :disabled="!!activeJob"
            @click="showDeployDialog = true"
          >
            <i class="pi pi-cloud-upload"></i> Re-deploy
          </button>
          <button
            class="btn btn-warning"
            :disabled="!!activeJob"
            @click="handleDisable(false)"
          >
            <i class="pi pi-power-off"></i> Disable
          </button>
          <button
            class="btn btn-danger"
            :disabled="!!activeJob"
            @click="showDeleteConfirm = true"
          >
            <i class="pi pi-trash"></i> Disable &amp; Delete Stack
          </button>
        </template>
      </div>

      <!-- Configurations Table -->
      <div v-if="configs.length" class="section-card">
        <div class="section-header">
          <h3 class="section-title">Configurations</h3>
          <span class="instance-count">{{ configs.length }} record{{ configs.length !== 1 ? 's' : '' }}</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Account ID</th>
                <th>Role Name</th>
                <th>Role ARN</th>
                <th>Active</th>
                <th>Enabled</th>
                <th>External ID</th>
                <th>Last Used</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="cfg in configs" :key="cfg.id">
                <td class="mono">{{ cfg.account_id }}</td>
                <td>{{ cfg.role_name }}</td>
                <td class="mono arn-cell">{{ cfg.role_arn }}</td>
                <td>
                  <span class="status-pill" :class="cfg.is_active ? 'pill-yes' : 'pill-no'">
                    {{ cfg.is_active ? 'Yes' : 'No' }}
                  </span>
                </td>
                <td>
                  <span class="status-pill" :class="cfg.enabled ? 'pill-yes' : 'pill-no'">
                    {{ cfg.enabled ? 'Yes' : 'No' }}
                  </span>
                </td>
                <td>
                  <span class="status-pill" :class="cfg.external_id_configured ? 'pill-yes' : 'pill-neutral'">
                    {{ cfg.external_id_configured ? 'Set' : 'None' }}
                  </span>
                </td>
                <td>{{ formatDate(cfg.last_used_at) }}</td>
                <td>{{ formatDate(cfg.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- CloudFormation Template -->
      <div class="section-card">
        <div class="section-header">
          <h3 class="section-title">CloudFormation Template</h3>
          <div class="template-actions">
            <a
              v-if="templateMeta?.public_url"
              :href="templateMeta.public_url"
              target="_blank"
              rel="noopener"
              class="btn btn-secondary btn-sm"
            >
              <i class="pi pi-download"></i> Download
            </a>
            <button class="btn btn-secondary btn-sm" @click="toggleTemplate">
              <i class="pi" :class="showTemplate ? 'pi-eye-slash' : 'pi-eye'"></i>
              {{ showTemplate ? 'Hide' : 'View' }}
            </button>
          </div>
        </div>
        <div v-if="templateLoading" class="template-loading">
          <i class="pi pi-spin pi-spinner"></i> Loading template...
        </div>
        <div v-else-if="showTemplate && templateContent" class="template-content">
          <pre>{{ templateContent }}</pre>
        </div>
      </div>
    </template>

    <!-- Deploy Dialog -->
    <div v-if="showDeployDialog" class="dialog-overlay" @click.self="showDeployDialog = false">
      <div class="dialog">
        <h3>Deploy Assume Role</h3>
        <p>This will deploy a CloudFormation stack that creates an IAM role for cross-account resource management.</p>

        <div class="form-group">
          <label class="form-label">Trust Mode</label>
          <select v-model="deployForm.trust_mode" class="form-select">
            <option value="CurrentUser">Current User Only</option>
            <option value="SpecificArn">Specific IAM ARN</option>
            <option value="AnyPrincipal">Any Principal in Account</option>
          </select>
          <span class="form-hint">Controls who can assume this role.</span>
          <span v-if="deployForm.trust_mode === 'AnyPrincipal'" class="form-warning">
            <i class="pi pi-exclamation-triangle"></i>
            Any IAM principal in the account will be able to assume this role. Use a more restrictive mode for production environments.
          </span>
        </div>

        <div v-if="deployForm.trust_mode === 'SpecificArn'" class="form-group">
          <label class="form-label">IAM ARN</label>
          <input
            v-model="deployForm.specific_arn"
            type="text"
            class="form-input"
            placeholder="arn:aws:iam::123456789012:user/name"
          />
        </div>

        <div class="form-group">
          <label class="form-label">External ID (optional)</label>
          <input
            v-model="deployForm.external_id"
            type="text"
            class="form-input"
            placeholder="Auto-retrieved from Secrets Manager if not set"
          />
        </div>

        <div class="form-group">
          <label class="form-label">Role Name</label>
          <input
            v-model="deployForm.role_name"
            type="text"
            class="form-input form-input-disabled"
            disabled
          />
          <span class="form-hint">Role name is fixed to match the CloudFormation template.</span>
        </div>

        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="showDeployDialog = false">Cancel</button>
          <button class="btn btn-primary" @click="handleDeploy">Deploy</button>
        </div>
      </div>
    </div>

    <!-- Delete Stack Confirmation Dialog -->
    <div v-if="showDeleteConfirm" class="dialog-overlay" @click.self="showDeleteConfirm = false">
      <div class="dialog">
        <h3>Delete Stack &amp; Disable</h3>
        <p>This will disable the assume-role configuration and delete the CloudFormation stack, removing the IAM role from your account.</p>
        <p class="dialog-warning">The role will no longer be available for resource management.</p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="showDeleteConfirm = false">Cancel</button>
          <button class="btn btn-danger" @click="handleDisable(true)">Delete Stack</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { AssumeRoleStatusResponse, AssumeRoleConfigRecord, JobResponse, TemplateMetadata } from '@/types/api'

const router = useRouter()

const status = ref<AssumeRoleStatusResponse | null>(null)
const configs = ref<AssumeRoleConfigRecord[]>([])
const statusLoading = ref(false)
const statusError = ref<string | null>(null)

const activeJob = ref<JobResponse | null>(null)
const jobResult = ref<{ success: boolean; message: string } | null>(null)
const showDeployDialog = ref(false)
const showDeleteConfirm = ref(false)

const templateMeta = ref<TemplateMetadata | null>(null)
const templateContent = ref<string | null>(null)
const templateLoading = ref(false)
const showTemplate = ref(false)

const deployForm = reactive({
  trust_mode: 'CurrentUser',
  specific_arn: '',
  external_id: '',
  role_name: 'BlueArchCLIRole',
})

let pollTimer: ReturnType<typeof setInterval> | null = null

// Computed
const statusCardClass = computed(() => {
  if (!status.value?.configured) return 'status-not-configured'
  if (status.value.enabled && status.value.stack_exists) return 'status-healthy'
  if (status.value.configured && !status.value.enabled) return 'status-disabled'
  return 'status-unknown'
})

const statusBadgeClass = computed(() => {
  if (!status.value?.configured) return 'badge-neutral'
  if (status.value.enabled) return 'badge-success'
  return 'badge-warning'
})

const statusBadgeIcon = computed(() => {
  if (!status.value?.configured) return 'pi pi-minus-circle'
  if (status.value.enabled) return 'pi pi-check-circle'
  return 'pi pi-exclamation-triangle'
})

const statusBadgeLabel = computed(() => {
  if (!status.value?.configured) return 'Not Configured'
  if (status.value.enabled) return 'Active'
  return 'Disabled'
})

const jobLabel = computed(() => {
  if (!activeJob.value) return ''
  switch (activeJob.value.job_type) {
    case 'assume_role_deploy': return 'Deploying assume role...'
    case 'assume_role_delete_stack': return 'Deleting CloudFormation stack...'
    default: return 'Running...'
  }
})

// Data fetching
async function loadStatus() {
  statusLoading.value = true
  statusError.value = null
  try {
    const [st, cfgs] = await Promise.all([
      api.assumeRoleStatus(),
      api.assumeRoleConfigs(),
    ])
    status.value = st
    configs.value = cfgs
  } catch (e) {
    statusError.value = e instanceof Error ? e.message : 'Failed to load status'
  } finally {
    statusLoading.value = false
  }
}

async function refresh() {
  await loadStatus()
}

// Job polling
function startPolling(jobId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const job = await api.getJob(jobId)
      activeJob.value = job
      if (job.status === 'completed' || job.status === 'failed') {
        stopPolling()
        activeJob.value = null
        if (job.status === 'completed') {
          jobResult.value = {
            success: true,
            message: job.result?.message as string || 'Operation completed successfully',
          }
        } else {
          jobResult.value = {
            success: false,
            message: job.error || 'Operation failed',
          }
        }
        await loadStatus()
      }
    } catch {
      // ignore polling errors
    }
  }, 1500)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// Actions
async function handleDeploy() {
  showDeployDialog.value = false
  jobResult.value = null
  try {
    const body: Record<string, string | undefined> = {
      trust_mode: deployForm.trust_mode,
      role_name: deployForm.role_name,
    }
    if (deployForm.specific_arn) body.specific_arn = deployForm.specific_arn
    if (deployForm.external_id) body.external_id = deployForm.external_id

    const resp = await api.deployAssumeRole(body)
    activeJob.value = {
      id: resp.job_id,
      job_type: resp.job_type,
      status: 'running',
      progress: 0,
      created_at: new Date().toISOString(),
    }
    startPolling(resp.job_id)
  } catch (e) {
    jobResult.value = { success: false, message: e instanceof Error ? e.message : 'Failed to start deploy' }
  }
}

async function handleDisable(deleteStack: boolean) {
  showDeleteConfirm.value = false
  jobResult.value = null
  try {
    const resp = await api.disableAssumeRole({ delete_stack: deleteStack })
    if (resp.job_id) {
      // Long-running: stack deletion job
      activeJob.value = {
        id: resp.job_id,
        job_type: resp.job_type || 'assume_role_delete_stack',
        status: 'running',
        progress: 0,
        created_at: new Date().toISOString(),
      }
      startPolling(resp.job_id)
    } else {
      // Instant: config disabled only
      jobResult.value = {
        success: resp.success ?? true,
        message: resp.message ?? 'Assume role disabled',
      }
      await loadStatus()
    }
  } catch (e) {
    jobResult.value = { success: false, message: e instanceof Error ? e.message : 'Failed to disable' }
  }
}

// Template viewer
async function loadTemplateMeta() {
  try {
    const list = await api.listTemplates()
    templateMeta.value = list.find(t => t.name === 'single_account_role.yaml') || null
  } catch {
    // non-critical
  }
}

async function toggleTemplate() {
  if (showTemplate.value) {
    showTemplate.value = false
    return
  }
  if (!templateContent.value) {
    templateLoading.value = true
    try {
      const detail = await api.getTemplate('single_account_role.yaml')
      templateContent.value = detail.content
      if (!templateMeta.value) {
        templateMeta.value = { name: detail.name, description: detail.description, public_url: detail.public_url, version: detail.version }
      }
    } catch {
      templateContent.value = '# Failed to load template'
    } finally {
      templateLoading.value = false
    }
  }
  showTemplate.value = true
}

// Helpers
function formatDate(iso?: string | null): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

onMounted(() => {
  loadStatus()
  loadTemplateMeta()
})
onUnmounted(() => stopPolling())
</script>

<style scoped>
.ar-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* Header */
.ar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ar-header-left {
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

.ar-title {
  font-size: 1.1rem;
  font-weight: 600;
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

.job-banner-text strong {
  font-size: 0.88rem;
}

.job-banner-text span {
  font-size: 0.78rem;
  opacity: 0.8;
}

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
  align-items: center;
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

.btn-dismiss {
  margin-left: auto;
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
.status-card.status-disabled { border-color: rgba(234, 179, 8, 0.25); }
.status-card.status-not-configured { border-color: var(--surface-border); }

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

.stack-info {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
}

.stack-label { color: var(--text-color-secondary); }
.stack-value {
  font-family: 'SF Mono', monospace;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.stack-create-complete,
.stack-update-complete { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.stack-delete-in-progress,
.stack-create-in-progress,
.stack-update-in-progress { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.stack-rollback-complete,
.stack-delete-failed,
.stack-create-failed { background: rgba(239, 68, 68, 0.15); color: #f87171; }

.status-card-body {
  padding: 1.25rem;
}

/* Detail Grid */
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.detail-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-color-secondary);
  font-weight: 600;
}

.detail-value {
  font-size: 0.88rem;
  color: var(--text-color);
  overflow-wrap: break-word;
  word-break: break-all;
  min-width: 0;
}

.ext-badge {
  display: inline-block;
  padding: 0.12rem 0.45rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 500;
}

.ext-yes { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.ext-no { background: var(--surface-card-hover); color: var(--text-color-secondary); }

.empty-status p {
  color: var(--text-color-secondary);
  font-size: 0.88rem;
  margin: 0;
}

/* Actions Row */
.actions-row {
  display: flex;
  gap: 0.75rem;
}

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

.section-title {
  font-size: 0.92rem;
  font-weight: 600;
}

.instance-count {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  padding: 0.2rem 0.5rem;
  border-radius: 10px;
}

/* Table */
.table-wrap {
  overflow-x: auto;
}

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

.data-table tbody tr:last-child td {
  border-bottom: none;
}

.data-table tbody tr:hover {
  background: rgba(32, 108, 245, 0.05);
}

.mono {
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
}

.arn-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Status Pill */
.status-pill {
  display: inline-block;
  padding: 0.12rem 0.45rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 500;
}

.pill-yes { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.pill-no { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.pill-neutral { background: var(--surface-card-hover); color: var(--text-color-secondary); }

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
  max-width: 480px;
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

/* Form */
.form-group {
  margin-top: 1rem;
}

.form-label {
  display: block;
  font-size: 0.82rem;
  font-weight: 600;
  margin-bottom: 0.35rem;
  color: var(--text-color);
}

.form-input,
.form-select {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.85rem;
  background: var(--surface-card);
  color: var(--text-color);
  box-sizing: border-box;
}

.form-input-disabled {
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  cursor: not-allowed;
}

.form-input:focus,
.form-select:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

.form-hint {
  display: block;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  margin-top: 0.25rem;
}

.form-warning {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  margin-top: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: rgba(234, 179, 8, 0.15);
  border: 1px solid rgba(234, 179, 8, 0.25);
  border-radius: 6px;
  font-size: 0.78rem;
  color: #facc15;
  line-height: 1.4;
}

.form-warning i {
  margin-top: 0.1rem;
  flex-shrink: 0;
}

/* Template Viewer */
.template-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-sm {
  padding: 0.3rem 0.65rem;
  font-size: 0.78rem;
}

.template-loading {
  padding: 1.5rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
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

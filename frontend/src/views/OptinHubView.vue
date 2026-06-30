<template>
  <div class="optin-view">
    <div class="view-header">
      <div>
        <h2 class="view-title">Opt-In Hub</h2>
        <p class="view-subtitle">
          Enable AWS Organizations trusted services and manage per-account enrollment
          for Compute Optimizer and Cost Optimization Hub.
        </p>
      </div>
      <button class="btn btn-secondary" :disabled="loading" @click="refresh">
        <i class="pi pi-refresh" :class="{ spin: loading }"></i>
        Refresh
      </button>
    </div>

    <!-- Auth banner -->
    <div v-if="auth && !auth.authorized" class="auth-banner">
      <i class="pi pi-exclamation-triangle"></i>
      <div>
        <strong>Not authorized</strong>
        <p>{{ auth.error || 'You must be the management account or a delegated admin.' }}</p>
      </div>
    </div>

    <!-- Result banner -->
    <div v-if="banner" class="result-banner" :class="banner.type">
      <i :class="banner.type === 'success' ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle'"></i>
      <span>{{ banner.message }}</span>
      <button class="btn-dismiss" @click="banner = null"><i class="pi pi-times"></i></button>
    </div>

    <!-- Organizations trusted services -->
    <div class="section-card">
      <div class="section-header">
        <h3 class="section-title">AWS Organizations Trusted Services</h3>
        <span class="section-hint">Enable so services can access data across your org</span>
      </div>
      <div v-if="loading && !services.length" class="loading-state">
        <i class="pi pi-spin pi-spinner"></i> Loading services...
      </div>
      <table v-else class="svc-table">
        <thead>
          <tr>
            <th>Service</th>
            <th>Status</th>
            <th>Description</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in services" :key="s.service_principal">
            <td>
              <div class="svc-name">{{ s.name }}</div>
              <div class="svc-principal">{{ s.service_principal }}</div>
            </td>
            <td>
              <span class="pill" :class="s.enabled ? 'pill-enabled' : 'pill-disabled'">
                {{ s.enabled ? 'Enabled' : 'Disabled' }}
              </span>
              <span v-if="s.supported" class="pill pill-managed">Managed</span>
            </td>
            <td class="desc-cell">
              <div>{{ s.description || '—' }}</div>
              <div v-if="s.toggle_supported === false && s.disabled_reason" class="svc-note">
                {{ s.disabled_reason }}
              </div>
            </td>
            <td class="actions-cell">
              <button
                v-if="auth?.authorized"
                class="btn btn-sm"
                :class="s.enabled ? 'btn-warning' : 'btn-primary'"
                :disabled="togglingPrincipal === s.service_principal || s.toggle_supported === false"
                :title="s.toggle_supported === false ? s.disabled_reason : undefined"
                @click="toggleService(s)"
              >
                <i v-if="togglingPrincipal === s.service_principal" class="pi pi-spin pi-spinner"></i>
                {{ serviceActionLabel(s) }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Per-account enrollment -->
    <div v-for="svc in enrollmentSections" :key="svc.key" class="section-card">
      <div class="section-header">
        <h3 class="section-title">{{ svc.label }}</h3>
        <div class="section-actions">
          <button
            v-if="auth?.authorized"
            class="btn btn-sm btn-primary"
            :disabled="bulkUpdating === svc.key || !enrollmentData[svc.key]?.org_enabled"
            @click="updateOrganizationEnrollment(svc.key, 'Active')"
          >
            <i v-if="bulkUpdating === svc.key" class="pi pi-spin pi-spinner"></i>
            Enable All Accounts
          </button>
          <button class="btn btn-sm btn-secondary" @click="loadEnrollment(svc.key)">
            <i class="pi pi-refresh"></i> Reload
          </button>
        </div>
      </div>
      <div v-if="!enrollmentData[svc.key]" class="loading-state">
        <i class="pi pi-spin pi-spinner"></i> Loading enrollment...
      </div>
      <div v-else>
        <div v-if="!enrollmentData[svc.key]!.org_enabled" class="info-banner">
          <i class="pi pi-info-circle"></i>
          Service-level trusted access is not enabled for this organization.
        </div>
        <table class="svc-table">
          <thead>
            <tr>
              <th>Account</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!enrollmentData[svc.key]!.accounts.length">
              <td colspan="3" class="empty-inline">No accounts found.</td>
            </tr>
            <tr v-else v-for="acct in enrollmentData[svc.key]!.accounts" :key="acct.account_id">
              <td class="mono-sm">{{ acct.account_id }}</td>
              <td>
                <span class="pill" :class="statusPillClass(acct.status)">{{ acct.status }}</span>
                <div v-if="acct.error" class="err-text">{{ acct.error }}</div>
              </td>
              <td class="actions-cell">
                <button
                  v-if="auth?.authorized && acct.status !== 'Active'"
                  class="btn btn-sm btn-primary"
                  :disabled="updatingEnrollment === `${svc.key}:${acct.account_id}:Active`"
                  @click="updateEnrollment(svc.key, acct.account_id, 'Active')"
                >
                  <i v-if="updatingEnrollment === `${svc.key}:${acct.account_id}:Active`" class="pi pi-spin pi-spinner"></i>
                  Enable
                </button>
                <button
                  v-if="auth?.authorized && acct.status === 'Active'"
                  class="btn btn-sm btn-warning"
                  :disabled="updatingEnrollment === `${svc.key}:${acct.account_id}:Inactive`"
                  @click="updateEnrollment(svc.key, acct.account_id, 'Inactive')"
                >
                  <i v-if="updatingEnrollment === `${svc.key}:${acct.account_id}:Inactive`" class="pi pi-spin pi-spinner"></i>
                  Disable
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'

interface ServiceRow {
  name: string
  service_principal: string
  enabled: boolean
  supported: boolean
  description?: string
  toggle_supported?: boolean
  disabled_reason?: string
}

interface AccountEnrollment {
  account_id: string
  status: string
  error?: string
}

interface EnrollmentResp {
  service: string
  org_enabled: boolean
  accounts: AccountEnrollment[]
}

type EnrollmentKey = 'compute-optimizer' | 'cost-optimization-hub'

const loading = ref(false)
const auth = ref<{ authorized: boolean; error?: string } | null>(null)
const services = ref<ServiceRow[]>([])
const togglingPrincipal = ref<string | null>(null)
const bulkUpdating = ref<EnrollmentKey | null>(null)
const updatingEnrollment = ref<string | null>(null)
const banner = ref<{ type: 'success' | 'error'; message: string } | null>(null)

const enrollmentSections: { key: EnrollmentKey; label: string }[] = [
  { key: 'compute-optimizer', label: 'Compute Optimizer — Per-Account Enrollment' },
  { key: 'cost-optimization-hub', label: 'Cost Optimization Hub — Per-Account Enrollment' },
]

const enrollmentData = ref<Record<EnrollmentKey, EnrollmentResp | null>>({
  'compute-optimizer': null,
  'cost-optimization-hub': null,
})

onMounted(async () => {
  await refresh()
})

async function refresh() {
  loading.value = true
  try {
    const [authResp, svcResp] = await Promise.all([
      api.optinAuthorization(),
      api.optinServices(),
    ])
    auth.value = authResp
    services.value = svcResp
    // Fire off enrollment loads in parallel (non-blocking for the UI)
    loadEnrollment('compute-optimizer')
    loadEnrollment('cost-optimization-hub')
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Failed to load opt-in hub' }
  } finally {
    loading.value = false
  }
}

async function loadEnrollment(key: EnrollmentKey) {
  enrollmentData.value[key] = null
  try {
    enrollmentData.value[key] = await api.optinEnrollment(key)
  } catch (e) {
    banner.value = {
      type: 'error',
      message: `Failed to load ${key} enrollment: ${e instanceof Error ? e.message : String(e)}`,
    }
  }
}

async function toggleService(s: ServiceRow) {
  if (s.toggle_supported === false) {
    banner.value = {
      type: 'error',
      message: s.disabled_reason || 'This service is managed outside the Organizations toggle.',
    }
    return
  }

  togglingPrincipal.value = s.service_principal
  try {
    const resp = await api.optinToggleService(s.service_principal, !s.enabled)
    banner.value = { type: 'success', message: resp.message }
    await refresh()
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Toggle failed' }
  } finally {
    togglingPrincipal.value = null
  }
}

function serviceActionLabel(s: ServiceRow) {
  if (s.toggle_supported === false) return 'Managed in AWS'
  return s.enabled ? 'Disable' : 'Enable'
}

async function updateEnrollment(
  service: EnrollmentKey,
  account_id: string,
  status: 'Active' | 'Inactive',
) {
  updatingEnrollment.value = `${service}:${account_id}:${status}`
  try {
    await api.optinUpdateEnrollment({ service, account_id, status })
    banner.value = { type: 'success', message: `${service} set to ${status} for ${account_id}` }
    await loadEnrollment(service)
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Update failed' }
  } finally {
    updatingEnrollment.value = null
  }
}

async function updateOrganizationEnrollment(
  service: EnrollmentKey,
  status: 'Active' | 'Inactive',
) {
  bulkUpdating.value = service
  try {
    await api.optinUpdateEnrollment({
      service,
      account_id: 'organization',
      status,
      optin_organization: true,
    })
    banner.value = { type: 'success', message: `${service} set to ${status} for all member accounts` }
    await loadEnrollment(service)
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Update failed' }
  } finally {
    bulkUpdating.value = null
  }
}

function statusPillClass(status: string) {
  const s = status.toLowerCase()
  if (s === 'active') return 'pill-enabled'
  if (s === 'inactive') return 'pill-disabled'
  if (s === 'pending') return 'pill-pending'
  if (s === 'failed') return 'pill-error'
  return 'pill-unknown'
}
</script>

<style scoped>
.optin-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.view-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.view-title { font-size: 1.3rem; font-weight: 600; margin: 0; }
.view-subtitle {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  margin: 0.25rem 0 0 0;
  max-width: 680px;
}

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
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--primary-color); color: white; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}
.btn-secondary:hover:not(:disabled) { background: var(--surface-border); }
.btn-warning { background: #f59e0b; color: white; }
.btn-warning:hover:not(:disabled) { background: #d97706; }
.btn-sm { padding: 0.35rem 0.75rem; font-size: 0.78rem; }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Banners */
.auth-banner {
  display: flex;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  background: rgba(234, 179, 8, 0.12);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 8px;
  color: #facc15;
}
.auth-banner i { font-size: 1.1rem; margin-top: 0.15rem; }
.auth-banner strong { display: block; font-size: 0.9rem; margin-bottom: 0.25rem; }
.auth-banner p { font-size: 0.8rem; margin: 0; opacity: 0.85; }

.info-banner {
  margin: 0.75rem 1.25rem 0;
  padding: 0.6rem 0.85rem;
  background: rgba(32, 108, 245, 0.1);
  border: 1px solid rgba(32, 108, 245, 0.25);
  border-radius: 6px;
  color: #5a9aff;
  font-size: 0.8rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.result-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 1px solid;
  font-size: 0.85rem;
}
.result-banner.success {
  background: rgba(34, 197, 94, 0.1);
  border-color: rgba(34, 197, 94, 0.25);
  color: #4ade80;
}
.result-banner.error {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.25);
  color: #f87171;
}
.btn-dismiss {
  margin-left: auto;
  background: none;
  border: none;
  cursor: pointer;
  opacity: 0.6;
  color: inherit;
}
.btn-dismiss:hover { opacity: 1; }

/* Section card */
.section-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.85rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}
.section-title { font-size: 0.95rem; font-weight: 600; margin: 0; }
.section-hint { font-size: 0.75rem; color: var(--text-color-secondary); }
.section-actions { display: flex; align-items: center; gap: 0.5rem; }

.loading-state {
  padding: 2rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}
.empty-inline {
  padding: 1.25rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.82rem;
}

/* Table */
.svc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.svc-table th {
  text-align: left;
  padding: 0.65rem 1rem;
  background: var(--surface-ground);
  font-size: 0.72rem;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  border-bottom: 1px solid var(--surface-border);
  font-weight: 600;
}
.svc-table td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--surface-border);
  vertical-align: top;
}
.svc-table tbody tr:last-child td { border-bottom: none; }

.svc-name { font-weight: 600; }
.svc-principal {
  font-family: 'SF Mono', monospace;
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  margin-top: 0.15rem;
}
.desc-cell {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  max-width: 380px;
}
.svc-note {
  margin-top: 0.35rem;
  color: #facc15;
  line-height: 1.35;
}
.actions-cell { text-align: right; }

.mono-sm {
  font-family: 'SF Mono', monospace;
  font-size: 0.8rem;
}

.pill {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 500;
  margin-right: 0.25rem;
}
.pill-enabled { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.pill-disabled { background: var(--surface-card-hover); color: var(--text-color-secondary); }
.pill-pending { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.pill-error { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.pill-unknown { background: var(--surface-card-hover); color: var(--text-color-secondary); }
.pill-managed { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }

.err-text {
  font-size: 0.72rem;
  color: #f87171;
  margin-top: 0.25rem;
}
</style>

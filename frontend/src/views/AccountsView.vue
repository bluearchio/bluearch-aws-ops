<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { AccountResponse } from '@/types/api'

const router = useRouter()
const accounts = ref<AccountResponse[]>([])
const loading = ref(true)
const validating = ref(false)
const validation = ref<any>(null)
const stacksetStatus = ref<any>(null)
const stacksetLoading = ref(false)

onMounted(async () => {
  try { accounts.value = await api.listAccounts() }
  finally { loading.value = false }
  loadStacksetStatus()
})

function openAccountResources(acct: AccountResponse) {
  router.push({ path: '/resources', query: { account_id: acct.account_id } })
}

async function runValidation() {
  validating.value = true
  try {
    validation.value = await api.accountsValidate()
  } catch { /* silent */ }
  finally { validating.value = false }
}

async function loadStacksetStatus() {
  stacksetLoading.value = true
  try {
    stacksetStatus.value = await api.accountsStacksetStatus()
  } catch { /* silent */ }
  finally { stacksetLoading.value = false }
}
</script>

<template>
  <div class="accounts-view">
    <!-- Header -->
    <div class="header-bar">
      <div class="header-info">
        <div class="header-icon" style="background: rgba(32, 108, 245, 0.12)">
          <i class="pi pi-users" style="color: #5a9aff"></i>
        </div>
        <div>
          <div class="header-label">Multi-Account Management</div>
          <div class="header-count">{{ accounts.length }} account{{ accounts.length !== 1 ? 's' : '' }}</div>
        </div>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" @click="runValidation" :disabled="validating">
          <i :class="validating ? 'pi pi-spin pi-spinner' : 'pi pi-check-circle'"></i>
          {{ validating ? 'Validating...' : 'Validate' }}
        </button>
        <button class="btn btn-secondary" @click="loadStacksetStatus" :disabled="stacksetLoading">
          <i :class="stacksetLoading ? 'pi pi-spin pi-spinner' : 'pi pi-refresh'"></i>
        </button>
      </div>
    </div>

    <!-- Validation Result -->
    <div v-if="validation" class="validation-card" :class="validation.can_deploy ? 'validation-ok' : 'validation-warn'">
      <div class="validation-icon">
        <i :class="validation.can_deploy ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle'"></i>
      </div>
      <div class="validation-body">
        <strong>{{ validation.can_deploy ? 'Ready for Cross-Account Deployment' : 'Cannot Deploy' }}</strong>
        <p v-if="validation.current_account_id">Account: <span class="mono">{{ validation.current_account_id }}</span></p>
        <p v-if="validation.organization_id">Organization: <span class="mono">{{ validation.organization_id }}</span></p>
        <p v-if="validation.is_management_account">This is the management account</p>
        <p v-if="validation.is_delegated_admin">Delegated admin for CloudFormation StackSets</p>
        <p v-if="validation.guidance" class="guidance-text">{{ validation.guidance }}</p>
      </div>
    </div>

    <!-- StackSet Status -->
    <div v-if="stacksetStatus && stacksetStatus.exists" class="section-card">
      <div class="section-header">
        <h3 class="section-title">StackSet Deployment</h3>
        <span class="status-pill" :class="stacksetStatus.status === 'ACTIVE' ? 'pill-ok' : 'pill-warn'">
          {{ stacksetStatus.status }}
        </span>
      </div>
      <div class="stackset-stats">
        <div class="stat-box">
          <span class="stat-val">{{ stacksetStatus.instance_count }}</span>
          <span class="stat-lbl">Instances</span>
        </div>
        <div class="stat-box" v-if="stacksetStatus.template_version">
          <span class="stat-val mono">{{ stacksetStatus.template_version }}</span>
          <span class="stat-lbl">Version</span>
        </div>
      </div>
      <div v-if="stacksetStatus.instances.length" class="instance-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>Account</th>
              <th>Region</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="inst in stacksetStatus.instances" :key="inst.account_id + inst.region">
              <td class="mono">{{ inst.account_id }}</td>
              <td class="mono">{{ inst.region }}</td>
              <td>
                <span class="status-pill" :class="inst.status === 'CURRENT' ? 'pill-ok' : 'pill-warn'">
                  {{ inst.status }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Accounts Table -->
    <div v-if="loading" class="loading-state"><i class="pi pi-spin pi-spinner"></i> Loading...</div>
    <div v-else-if="!accounts.length" class="empty-state">
      <i class="pi pi-users" style="font-size: 1.5rem; margin-bottom: 0.5rem"></i>
      <div>No accounts discovered yet. Run a scan to discover accounts.</div>
    </div>
    <div v-else class="table-card">
      <table class="data-table">
        <thead>
          <tr>
            <th>Account ID</th>
            <th>Name</th>
            <th>Discovery</th>
            <th>Resources</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="acct in accounts"
            :key="acct.id"
            class="table-row clickable-row"
            @click="openAccountResources(acct)"
          >
            <td class="mono">{{ acct.account_id }}</td>
            <td>{{ acct.account_name }}</td>
            <td>
              <span :class="acct.enabled_for_discovery ? 'text-ok' : 'text-muted'">
                {{ acct.enabled_for_discovery ? 'Enabled' : 'Disabled' }}
              </span>
            </td>
            <td class="mono">{{ acct.total_resources_discovered }}</td>
            <td>
              <span class="status-pill" :class="acct.access_check_status === 'SUCCESS' ? 'pill-ok' : (acct.access_check_status === 'FAILED' ? 'pill-err' : 'pill-neutral')">
                {{ acct.access_check_status || 'NOT_TESTED' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.accounts-view { display: flex; flex-direction: column; gap: 1rem; }

.header-bar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.25rem; background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 10px; }
.header-info { display: flex; align-items: center; gap: 0.75rem; }
.header-icon { width: 40px; height: 40px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 1.1rem; }
.header-label { font-size: 0.78rem; color: var(--text-color-secondary); text-transform: uppercase; letter-spacing: 0.04em; }
.header-count { font-size: 0.9rem; font-weight: 600; margin-top: 2px; }
.header-actions { display: flex; gap: 0.5rem; }

.validation-card { display: flex; gap: 1rem; padding: 1rem 1.25rem; border-radius: 10px; border: 1px solid; }
.validation-ok { background: rgba(34, 197, 94, 0.08); border-color: rgba(34, 197, 94, 0.3); }
.validation-ok .validation-icon { color: #4ade80; }
.validation-warn { background: rgba(234, 179, 8, 0.08); border-color: rgba(234, 179, 8, 0.3); }
.validation-warn .validation-icon { color: #facc15; }
.validation-icon { font-size: 1.2rem; flex-shrink: 0; }
.validation-body { flex: 1; }
.validation-body strong { font-size: 0.9rem; }
.validation-body p { font-size: 0.82rem; color: var(--text-color-secondary); margin: 0.25rem 0; }
.guidance-text { white-space: pre-line; font-family: var(--font-mono, monospace); font-size: 0.78rem; }

.section-card { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 10px; overflow: hidden; }
.section-header { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1rem; border-bottom: 1px solid var(--surface-border); }
.section-title { font-size: 0.9rem; font-weight: 600; }
.stackset-stats { display: flex; gap: 2rem; padding: 0.75rem 1rem; border-bottom: 1px solid var(--surface-border); }
.stat-box { display: flex; flex-direction: column; align-items: center; }
.stat-val { font-size: 1.1rem; font-weight: 700; }
.stat-lbl { font-size: 0.65rem; text-transform: uppercase; color: var(--text-color-secondary); }

.table-card { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 10px; overflow: hidden; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { text-align: left; padding: 0.65rem 1rem; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: var(--text-color-secondary); background: var(--surface-ground); border-bottom: 1px solid var(--surface-border); }
.data-table td { padding: 0.6rem 1rem; font-size: 0.82rem; border-bottom: 1px solid var(--surface-border); }
.table-row { transition: background 0.1s; }
.clickable-row { cursor: pointer; }
.clickable-row:hover { background: rgba(32, 108, 245, 0.08); }

.status-pill { display: inline-block; padding: 0.15rem 0.45rem; border-radius: 10px; font-size: 0.72rem; font-weight: 500; }
.pill-ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.pill-warn { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.pill-err { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.pill-neutral { background: rgba(107, 114, 128, 0.15); color: var(--text-color-secondary); }

.text-ok { color: #4ade80; font-size: 0.82rem; }
.text-muted { color: var(--text-color-secondary); font-size: 0.82rem; }
.mono { font-family: var(--font-mono, monospace); }

.btn { padding: 0.45rem 0.85rem; border: none; border-radius: 6px; font-size: 0.82rem; cursor: pointer; font-weight: 500; transition: all 0.15s; display: inline-flex; align-items: center; gap: 0.35rem; font-family: var(--font-body); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: var(--surface-ground); color: var(--text-color); border: 1px solid var(--surface-border); }
.btn-secondary:hover:not(:disabled) { background: var(--surface-card); }

.loading-state { color: var(--text-color-secondary); padding: 2rem; text-align: center; display: flex; align-items: center; justify-content: center; gap: 0.5rem; }
.empty-state { display: flex; flex-direction: column; align-items: center; padding: 3rem; color: var(--text-color-secondary); font-size: 0.85rem; background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 10px; }

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.pi-spin { animation: spin 1s linear infinite; }
</style>

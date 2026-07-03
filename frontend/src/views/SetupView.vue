<template>
  <div class="setup-view">
    <div class="setup-header">
      <h2 class="setup-title">System Setup</h2>
      <div class="setup-header-actions">
        <button
          class="btn btn-secondary"
          :disabled="loading || infraLoading"
          @click="refreshAll"
        >
          <i class="pi pi-refresh" :class="{ 'spin': loading || infraLoading }"></i>
          Refresh
        </button>
        <button
          class="btn btn-primary"
          :disabled="loading"
          @click="runValidation"
        >
          <i class="pi pi-refresh" :class="{ 'spin': loading }"></i>
          {{ loading ? 'Validating...' : 'Run Validation' }}
        </button>
      </div>
    </div>

    <!-- Permission Tier Section -->
    <div v-if="permissionStore.status" class="tier-section">
      <div class="tier-header">
        <div class="tier-context">
          <i class="pi pi-building"></i>
          <span class="tier-account">{{ contextStore.currentLabel }}</span>
          <span class="tier-badge" :class="'tier-' + permissionStore.tier">{{ permissionStore.tier }}</span>
        </div>
      </div>

      <!-- Tier Progress Stepper -->
      <div class="tier-stepper">
        <div v-for="t in tiers" :key="t.name" class="tier-step" :class="{ active: t.active, completed: t.completed, warning: t.warning, skipped: t.skipped }">
          <div class="step-marker">
            <i v-if="t.completed" class="pi pi-check"></i>
            <i v-else-if="t.skipped" class="pi pi-minus"></i>
            <i v-else-if="t.warning" class="pi pi-exclamation-triangle"></i>
            <span v-else>{{ t.number }}</span>
          </div>
          <div class="step-label">{{ t.label }}</div>
          <div class="step-desc">{{ t.skipped ? 'Not needed' : t.desc }}</div>
        </div>
      </div>

      <!-- Feature Checklist -->
      <div class="feature-checklist">
        <div class="checklist-title">Feature Availability</div>
        <div class="checklist-grid">
          <div v-for="(feat, key) in permissionStore.status.features" :key="key" class="feature-item">
            <i class="pi" :class="featureIcon(feat)"></i>
            <span class="feature-name">{{ formatFeatureName(key as string) }}</span>
            <span v-if="feat.partial" class="feature-partial">partial</span>
          </div>
        </div>
      </div>

    </div>

    <!-- SSO Expired Alert -->
    <div v-if="ssoExpiredCheck" class="sso-alert">
      <div class="sso-alert-icon">
        <i class="pi pi-exclamation-triangle"></i>
      </div>
      <div class="sso-alert-body">
        <strong>AWS SSO Token Expired</strong>
        <p>Your SSO session has expired. Run the following command to re-authenticate:</p>
        <div class="sso-cmd-row">
          <code>aws sso login</code>
          <button class="btn-copy" @click="copySsoCmd" title="Copy command">
            <i class="pi pi-copy"></i>
          </button>
        </div>
        <p class="sso-hint">Then click "Run Validation" to re-check.</p>
      </div>
    </div>

    <!-- Credentials Not Configured Alert -->
    <div v-if="credentialsNotConfigured" class="creds-alert">
      <div class="creds-alert-icon">
        <i class="pi pi-exclamation-triangle"></i>
      </div>
      <div class="creds-alert-body">
        <strong>AWS Credentials Not Configured</strong>
        <p>No valid AWS credentials were found. Set one of the following:</p>
        <div class="creds-options">
          <div class="creds-option">
            <span class="creds-option-label">Option 1: AWS SSO Profile</span>
            <div class="sso-cmd-row">
              <code>export AWS_PROFILE=your-profile-name</code>
            </div>
          </div>
          <div class="creds-option">
            <span class="creds-option-label">Option 2: Environment Variables</span>
            <div class="sso-cmd-row">
              <code>export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...</code>
            </div>
          </div>
        </div>
        <p class="sso-hint">Then restart the web server and click "Run Validation" to re-check.</p>
      </div>
    </div>

    <!-- Overall Status -->
    <div v-if="result" class="status-banner" :class="'status-' + adjustedOverall">
      <div class="status-icon">
        <i :class="overallIcon"></i>
      </div>
      <div class="status-body">
        <strong>{{ overallLabel }}</strong>
        <p>{{ overallDescription }}</p>
      </div>
    </div>

    <!-- Deployed Infrastructure -->
    <div v-if="infraData || infraLoading" class="section-card">
      <div class="section-header">
        <h3 class="section-title">Deployed Infrastructure</h3>
        <span v-if="infraLoading" class="infra-loading-badge">
          <i class="pi pi-spin pi-spinner"></i> Loading...
        </span>
      </div>

      <template v-if="infraData">
        <!-- Account Info Bar -->
        <div v-if="infraData.account_id" class="account-bar">
          <span><strong>Account:</strong> {{ infraData.account_id }}</span>
          <span v-if="infraData.organization_id"><strong>Organization:</strong> {{ infraData.organization_id }}</span>
          <span v-if="infraData.region"><strong>Region:</strong> {{ infraData.region }}</span>
        </div>

        <!-- Unified Components Table -->
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Component</th>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>Version</th>
                <th>Region</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="comp in allInfraComponents" :key="comp.key">
                <td>{{ comp.label }}</td>
                <td class="mono">{{ comp.name }}</td>
                <td><span class="component-badge">{{ comp.type }}</span></td>
                <td>
                  <span class="status-pill" :class="comp.pillClass">{{ comp.statusText }}</span>
                </td>
                <td>
                  <span v-if="comp.version" class="version-text" :class="{ 'version-outdated': comp.versionOutdated }">
                    {{ comp.version }}
                    <span v-if="comp.versionOutdated" class="version-hint">(update available)</span>
                  </span>
                  <span v-else class="action-na">-</span>
                </td>
                <td>{{ comp.region || '-' }}</td>
                <td>
                  <div class="action-buttons">
                    <button
                      v-if="comp.templateName"
                      class="btn btn-secondary btn-sm"
                      title="View CloudFormation template"
                      @click="viewTemplate(comp.templateName!)"
                    >
                      <i class="pi pi-eye"></i> View
                    </button>
                    <button
                      v-if="comp.action === 'manage'"
                      class="btn btn-secondary btn-sm"
                      @click="router.push(comp.actionRoute!)"
                    >
                      Manage
                    </button>
                    <button
                      v-else-if="comp.action === 'deploy'"
                      class="btn btn-primary btn-sm"
                      :disabled="componentActioning === comp.key"
                      @click="handleComponentAction(comp)"
                    >
                      <i v-if="componentActioning === comp.key" class="pi pi-spin pi-spinner"></i>
                      Deploy
                    </button>
                    <button
                      v-else-if="comp.action === 'delete'"
                      class="btn btn-danger btn-sm"
                      :disabled="componentActioning === comp.key"
                      @click="handleComponentAction(comp)"
                    >
                      <i v-if="componentActioning === comp.key" class="pi pi-spin pi-spinner"></i>
                      Delete
                    </button>
                    <span v-if="comp.action === 'none' && !comp.templateName" class="action-na">-</span>
                    <button
                      v-if="comp.versionOutdated"
                      class="btn btn-primary btn-sm"
                      :disabled="updatingComponent === comp.key"
                      @click="handleUpdateStack(comp.key)"
                    >
                      <i v-if="updatingComponent === comp.key" class="pi pi-spin pi-spinner"></i>
                      Update
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Resource Group Compact Row -->
        <div class="rg-row">
          <div class="rg-row-left">
            <span class="rg-row-label">Resource Group</span>
            <span v-if="infraData.resource_group.exists" class="status-pill pill-success">Active</span>
            <span v-else class="status-pill pill-not-deployed">Not Created</span>
            <span v-if="infraData.resource_group.exists" class="rg-row-detail">
              <span class="mono">{{ infraData.resource_group.name }}</span>
              <span class="rg-row-count">{{ infraData.resource_group.resource_count }} resources</span>
            </span>
          </div>
          <div class="rg-row-actions">
            <button
              v-if="!infraData.resource_group.exists"
              class="btn btn-primary btn-sm"
              :disabled="rgLoading"
              @click="handleCreateRG"
            >
              <i class="pi pi-plus" :class="{ spin: rgLoading }"></i> Create
            </button>
            <button
              v-else
              class="btn btn-danger btn-sm"
              :disabled="rgLoading"
              @click="handleDeleteRG"
            >
              <i class="pi pi-trash"></i> Delete
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- Event Tracking Section -->
    <div v-if="etData || etLoading" class="section-card">
      <div class="section-header">
        <h3 class="section-title">
          <i class="pi pi-bolt" style="-webkit-text-fill-color: #facc15; font-size: 0.8rem;"></i>
          Event Tracking
        </h3>
        <div class="section-header-actions">
          <span v-if="etLoading" class="infra-loading-badge">
            <i class="pi pi-spin pi-spinner"></i> Loading...
          </span>
          <template v-if="etData">
            <span v-if="etData.service_running && !etData.service_paused" class="status-pill pill-success">
              <i class="pi pi-circle-fill" style="font-size: 0.5rem;"></i> Running
            </span>
            <span v-else-if="etData.service_paused" class="status-pill pill-warning">Paused</span>
            <span v-else-if="etData.total_queues > 0" class="status-pill pill-neutral">Stopped</span>
          </template>
        </div>
      </div>

      <template v-if="etData">
        <!-- No instances deployed -->
        <div v-if="!etHasInstances" class="et-empty">
          <i class="pi pi-bolt"></i>
          <div>
            <strong>Real-time resource tracking is not enabled</strong>
            <p>Activate event tracking to automatically detect resource changes as they happen. Infrastructure is deployed with cross-account setup.</p>
            <div v-if="!etDeploying" class="et-deploy-actions">
              <button class="btn btn-primary btn-sm" @click="handleDeployET">
                <i class="pi pi-bolt"></i> Activate Event Tracking
              </button>
            </div>
            <div v-else class="et-deploy-progress">
              <i class="pi pi-spin pi-spinner"></i>
              <span>Activating event tracking...</span>
            </div>
          </div>
        </div>

        <!-- Instances table -->
        <div v-if="etHasInstances" class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Region</th>
                <th>Status</th>
                <th>Events Today</th>
                <th>Last Polled</th>
                <th>Last Event</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="inst in etData.instances" :key="`${inst.account_id}:${inst.region}`">
                <td class="mono">{{ inst.account_id }}</td>
                <td>{{ inst.region }}</td>
                <td>
                  <span class="status-pill" :class="{
                    'pill-success': inst.status === 'active',
                    'pill-warning': inst.status === 'paused' || inst.status === 'deploying',
                    'pill-danger': inst.status === 'error' || inst.status === 'failed',
                    'pill-neutral': !['active','paused','deploying','error','failed'].includes(inst.status),
                  }">{{ inst.status }}</span>
                </td>
                <td>{{ inst.events_today }}</td>
                <td>{{ formatTimeAgo(inst.last_polled_at) }}</td>
                <td>{{ formatTimeAgo(inst.last_event_at) }}</td>
                <td>
                  <button
                    class="btn btn-danger btn-sm"
                    :disabled="etRemovingInstance === `${inst.account_id}:${inst.region}`"
                    @click="handleRemoveETInstance(inst)"
                  >
                    <i v-if="etRemovingInstance === `${inst.account_id}:${inst.region}`" class="pi pi-spin pi-spinner"></i>
                    Remove
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Auto-scan progress (shown within instances view) -->
        <div v-if="etScanning && etHasInstances" class="et-scan-progress">
          <i class="pi pi-spin pi-spinner"></i>
          <div>
            <strong>Populating resource baseline</strong>
            <p>{{ etScanMessage }}</p>
          </div>
        </div>

        <!-- Service Controls -->
        <div v-if="etHasInstances" class="et-controls">
          <div class="et-controls-left">
            <span class="et-controls-label">Service Controls</span>
            <span class="et-stat">{{ etData.active_queues }} / {{ etData.total_queues }} queues active</span>
          </div>
          <div class="et-controls-right">
            <button
              v-if="etData.service_running && !etData.service_paused"
              class="btn btn-secondary btn-sm"
              :disabled="etActionLoading === 'pause'"
              @click="handleEventTrackingServiceAction('pause')"
            >
              <i class="pi pi-pause"></i> Pause
            </button>
            <button
              v-else-if="etData.service_paused"
              class="btn btn-primary btn-sm"
              :disabled="etActionLoading === 'resume'"
              @click="handleEventTrackingServiceAction('resume')"
            >
              <i class="pi pi-play"></i> Resume
            </button>
            <button
              v-else
              class="btn btn-primary btn-sm"
              :disabled="etActionLoading === 'start'"
              @click="handleEventTrackingServiceAction('start')"
            >
              <i class="pi pi-play"></i> Start
            </button>
            <button
              class="btn btn-secondary btn-sm"
              :disabled="etActionLoading === 'sync'"
              @click="handleEventTrackingServiceAction('sync')"
            >
              <i class="pi pi-refresh"></i> Sync
            </button>
            <button
              class="btn btn-danger btn-sm"
              :disabled="etActionLoading === 'remove-all'"
              @click="handleRemoveAllET"
            >
              <i v-if="etActionLoading === 'remove-all'" class="pi pi-spin pi-spinner"></i>
              Remove All
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- Check Results -->
    <div v-if="result" class="checks-grid">
      <div
        v-for="check in coreChecks"
        :key="check.name"
        class="check-card"
        :class="'check-' + check.status"
      >
        <div class="check-icon">
          <i :class="statusIcon(check.status)"></i>
        </div>
        <div class="check-body">
          <span class="check-name">{{ check.name }}</span>
          <span class="check-message">{{ check.message }}</span>
          <div v-if="check.details" class="check-details">
            <div v-for="(val, key) in check.details" :key="String(key)" class="detail-row">
              <span class="detail-key">{{ key }}</span>
              <span class="detail-val">{{ val }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Multi-Account / Assume-Role Section -->
    <div v-if="result" class="section-card">
      <div class="section-header">
        <h3 class="section-title">Multi-Account Configuration</h3>
        <div class="section-header-actions">
          <span v-if="multiAccountOverall" class="ma-badge" :class="'ma-badge-' + multiAccountOverall">
            <i :class="statusIcon(multiAccountOverall)"></i>
            {{ multiAccountOverall === 'ok' ? 'Configured' : multiAccountOverall === 'error' ? 'Not configured' : 'Partially configured' }}
          </span>
          <button class="btn btn-secondary btn-sm" @click="router.push('/setup/multi-account')">
            <i class="pi pi-cog"></i> Manage
          </button>
        </div>
      </div>
      <div class="multi-account-content">
        <div class="config-cards">
          <!-- Assume Role Status -->
          <div class="config-card" :class="getAssumeRoleStatus.class">
            <div class="config-icon">
              <i :class="getAssumeRoleStatus.icon"></i>
            </div>
            <div class="config-body">
              <h4>Assume Role</h4>
              <p class="config-desc">{{ (permissionStore.tier === 'enterprise' || permissionStore.tier === 'standard') ? 'Optional - your IAM user/role already has the required permissions.' : 'Use a dedicated IAM role for CLI API calls instead of direct credentials.' }}</p>
              <p class="config-status">{{ getAssumeRoleStatus.message }}</p>
              <div v-if="getAssumeRoleStatus.details" class="config-details">
                <span v-for="(val, key) in filteredDetails(getAssumeRoleStatus.details)" :key="String(key)">
                  <strong>{{ key }}:</strong> {{ val }}
                </span>
              </div>
            </div>
          </div>

          <!-- Organizations / Multi-Account Status -->
          <div class="config-card" :class="getMultiAccountStatus.class">
            <div class="config-icon">
              <i :class="getMultiAccountStatus.icon"></i>
            </div>
            <div class="config-body">
              <h4>Multi-Account</h4>
              <p class="config-desc">Scan and manage resources across AWS Organization member accounts via StackSets.</p>
              <p class="config-status">{{ getMultiAccountStatus.message }}</p>
              <div v-if="getMultiAccountStatus.details" class="config-details">
                <span v-for="(val, key) in filteredDetails(getMultiAccountStatus.details)" :key="String(key)">
                  <strong>{{ key }}:</strong> {{ val }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div class="setup-instructions">
          <h4>Setup Instructions</h4>
          <div class="instruction-steps">
            <div class="step">
              <span class="step-num">1</span>
              <div class="step-content">
                <strong>Deploy Cross-Account Role (Single Account)</strong>
                <code>bluearch setup assume-role --deploy</code>
                <p>Creates an IAM role in your account with the required permissions.</p>
              </div>
            </div>
            <div class="step">
              <span class="step-num">2</span>
              <div class="step-content">
                <strong>Deploy Multi-Account StackSets (AWS Organizations)</strong>
                <code>bluearch setup multi-account</code>
                <p>Deploys IAM roles across all member accounts using StackSets.</p>
              </div>
            </div>
            <div class="step">
              <span class="step-num">3</span>
              <div class="step-content">
                <strong>Verify Configuration</strong>
                <code>bluearch setup assume-role --status</code>
                <p>Check the status of configured roles and test cross-account access.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- IAM Policy Section -->
    <div class="section-card">
      <div class="section-header clickable" @click="toggleIamPolicy">
        <h3 class="section-title">
          <i :class="iamPolicyExpanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'"></i>
          Required IAM Policy
        </h3>
        <div class="section-header-actions">
          <button class="btn btn-secondary btn-sm" @click.stop="downloadIamPolicy" :disabled="iamPolicyLoading">
            <i class="pi pi-download"></i> Download Policy
          </button>
          <button class="btn btn-secondary btn-sm" @click.stop="copyIamPolicy" :disabled="!iamPolicy">
            <i class="pi pi-copy"></i> Copy
          </button>
        </div>
      </div>
      <div v-if="iamPolicyExpanded" class="iam-policy-content">
        <div v-if="iamPolicyLoading" class="iam-loading">
          <i class="pi pi-spin pi-spinner"></i> Loading policy...
        </div>
        <div v-else-if="iamPolicyError" class="iam-error">
          {{ iamPolicyError }}
        </div>
        <div v-else-if="iamPolicy" class="iam-policy-groups">
          <div
            v-for="stmt in (iamPolicy.Statement || [])"
            :key="stmt.Sid"
            class="iam-policy-group"
          >
            <div class="group-header" @click="toggleStatement(stmt.Sid)">
              <i :class="expandedStatements.includes(stmt.Sid) ? 'pi pi-chevron-down' : 'pi pi-chevron-right'"></i>
              <span class="group-name">{{ stmt.Sid }}</span>
              <span class="group-action-count">{{ Array.isArray(stmt.Action) ? stmt.Action.length : 1 }} actions</span>
            </div>
            <div v-if="expandedStatements.includes(stmt.Sid)" class="group-details">
              <div class="detail-section">
                <span class="detail-label">Effect:</span>
                <span class="detail-value effect-allow">{{ stmt.Effect }}</span>
              </div>
              <div class="detail-section">
                <span class="detail-label">Actions:</span>
                <div class="actions-list">
                  <code v-for="action in (Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action])" :key="action">{{ action }}</code>
                </div>
              </div>
              <div v-if="stmt.Resource" class="detail-section">
                <span class="detail-label">Resource:</span>
                <code class="resource-value">{{ Array.isArray(stmt.Resource) ? stmt.Resource.join(', ') : stmt.Resource }}</code>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- CLI Commands Reference -->
    <div class="section-card">
      <div class="section-header">
        <h3 class="section-title">Setup CLI Commands</h3>
      </div>
      <div class="cli-commands">
        <div class="cli-group">
          <h4>Initial Setup</h4>
          <div class="cli-cmd"><code>bluearch setup wizard</code><span>Interactive setup wizard</span></div>
          <div class="cli-cmd"><code>bluearch setup validate</code><span>Validate configuration</span></div>
          <div class="cli-cmd"><code>bluearch setup validate --iam</code><span>Show required IAM permissions</span></div>
          <div class="cli-cmd"><code>bluearch setup doctor</code><span>Diagnose installation issues</span></div>
        </div>
        <div class="cli-group">
          <h4>AWS Configuration</h4>
          <div class="cli-cmd"><code>bluearch setup aws</code><span>Configure AWS profile</span></div>
          <div class="cli-cmd"><code>bluearch setup database</code><span>Initialize database</span></div>
          <div class="cli-cmd"><code>bluearch setup database --force</code><span>Reset and reinitialize database</span></div>
        </div>
        <div class="cli-group">
          <h4>Multi-Account</h4>
          <div class="cli-cmd"><code>bluearch setup multi-account</code><span>Deploy cross-account StackSets</span></div>
          <div class="cli-cmd"><code>bluearch setup assume-role --deploy</code><span>Configure assume-role auth</span></div>
          <div class="cli-cmd"><code>bluearch setup assume-role --status</code><span>Check role configuration</span></div>
        </div>
      </div>
    </div>

    <!-- Empty state before first validation -->
    <div v-if="!result && !loading" class="empty-state">
      <div class="empty-icon">
        <i class="pi pi-cog"></i>
      </div>
      <h3>System Validation</h3>
      <p>Run validation to check your AWS credentials, database, permissions, and system configuration.</p>
      <button class="btn btn-primary" @click="runValidation">
        <i class="pi pi-play"></i> Run Validation
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { api } from '@/api/client'
import { useSetupStore } from '@/stores/setup'
import { useContextStore } from '@/stores/context'
import { usePermissionStore } from '@/stores/permissions'
import type { EventTrackingStatusResponse, EventTrackingInstanceStatus } from '@/types/api'

const router = useRouter()
const setupStore = useSetupStore()
const contextStore = useContextStore()
const permissionStore = usePermissionStore()

const {
  result,
  loading,
  infraData,
  infraLoading,
  iamPolicy,
  iamPolicyLoading,
  iamPolicyError,
} = storeToRefs(setupStore)

// Local-only UI state (not persisted across navigation)
const rgLoading = ref(false)
const componentActioning = ref<string | null>(null)
const updatingComponent = ref<string | null>(null)
const iamPolicyExpanded = ref(false)
const expandedStatements = ref<string[]>([])

// --- Permission Tier ---

const tiers = computed(() => {
  const currentTier = permissionStore.tier
  const tierOrder = ['none', 'basic', 'standard', 'enterprise']
  const currentIdx = tierOrder.indexOf(currentTier)
  // Check if CLI Role (Assume Role stack) is actually deployed
  const assumeRoleDeployed = !!infraData.value?.stacks?.find((s: any) => s.component === 'assume-role')
  // Standard is "skipped" when user has enterprise perms natively (without CLI role)
  const standardSkipped = currentIdx >= 3 && !assumeRoleDeployed
  return [
    { name: 'basic', number: 1, label: 'Basic', desc: 'Permission validation', active: currentTier === 'basic', completed: currentIdx >= 2, warning: currentTier === 'basic', skipped: false },
    { name: 'standard', number: 2, label: 'Standard', desc: 'CLI Role (if needed)', active: currentTier === 'standard', completed: assumeRoleDeployed, warning: false, skipped: standardSkipped },
    { name: 'enterprise', number: 3, label: 'Enterprise', desc: 'Cross-account + Orgs', active: currentTier === 'enterprise', completed: currentIdx >= 3, warning: false, skipped: false },
  ]
})

function featureIcon(feat: { available: boolean; partial?: boolean }): string {
  if (feat.available) return 'pi-check-circle feature-available'
  if (feat.partial) return 'pi-exclamation-circle feature-partial-icon'
  return 'pi-times-circle feature-unavailable'
}

function formatFeatureName(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// --- Infrastructure ---

interface InfraComponent {
  key: string
  label: string
  name: string
  type: string
  statusText: string
  pillClass: string
  region: string
  version: string
  versionOutdated: boolean
  action: 'manage' | 'deploy' | 'delete' | 'none'
  actionRoute?: string
  templateName?: string
  outputs?: Record<string, string>
}

const COMPONENT_TEMPLATE_MAP: Record<string, string> = {
  'cross-account': 'cross_account_stack.yaml',
  'management': 'management_account_resources.yaml',
  'assume-role': 'single_account_role.yaml',
  'cur': 'cur_stack.yaml',
  'event-tracking': 'event_tracking_stack.yaml',
}

function viewTemplate(templateName: string) {
  window.open(`/api/v1/system/templates/${templateName}/raw`, '_blank')
}

function stackStatusPill(status: string): string {
  if (status.includes('COMPLETE') && !status.includes('ROLLBACK') && !status.includes('DELETE') && !status.includes('FAILED')) return 'pill-success'
  if (status.includes('FAILED') || status.includes('ROLLBACK')) return 'pill-danger'
  if (status.includes('IN_PROGRESS')) return 'pill-warning'
  return 'pill-neutral'
}

const allInfraComponents = computed<InfraComponent[]>(() => {
  const d = infraData.value
  const components: InfraComponent[] = []

  const localVer = d?.local_version || ''

  // 1. Cross-Account StackSet
  const ss = d?.stacksets.find(s => s.name.includes('CrossAccount'))
  if (ss) {
    const instanceInfo = ss.instance_count > 0 ? ` (${ss.instance_count} instances)` : ''
    const ver = ss.version || ''
    components.push({
      key: 'cross-account',
      label: 'Cross-Account',
      name: 'BlueArchCLI-CrossAccount-Infrastructure',
      type: 'StackSet',
      statusText: ss.status + instanceInfo,
      pillClass: ss.status === 'ACTIVE' ? 'pill-success' : ss.status === 'DELETED' ? 'pill-danger' : 'pill-neutral',
      region: '-',
      version: ver,
      versionOutdated: !!(localVer && (!ver || ver !== localVer)),
      action: 'manage',
      actionRoute: '/setup/multi-account',
      templateName: COMPONENT_TEMPLATE_MAP['cross-account'],
    })
  } else {
    components.push({
      key: 'cross-account',
      label: 'Cross-Account',
      name: 'BlueArchCLI-CrossAccount-Infrastructure',
      type: 'StackSet',
      statusText: 'Not Deployed',
      pillClass: 'pill-not-deployed',
      region: '-',
      version: '',
      versionOutdated: false,
      action: 'deploy',
      actionRoute: '/setup/multi-account',
      templateName: COMPONENT_TEMPLATE_MAP['cross-account'],
    })
  }

  // 2. Management Stack
  const mgmt = d?.stacks.find(s => s.component === 'management-resources')
  if (mgmt) {
    const ver = mgmt.version || ''
    components.push({
      key: 'management',
      label: 'Management',
      name: mgmt.stack_name,
      type: 'Stack',
      statusText: mgmt.status,
      pillClass: stackStatusPill(mgmt.status),
      region: mgmt.region,
      version: ver,
      versionOutdated: !!(localVer && (!ver || ver !== localVer)),
      action: 'manage',
      actionRoute: '/setup/multi-account',
      templateName: COMPONENT_TEMPLATE_MAP['management'],
    })
  } else {
    components.push({
      key: 'management',
      label: 'Management',
      name: 'BlueArchCLI-Management-Account-Resources',
      type: 'Stack',
      statusText: 'Not Deployed',
      pillClass: 'pill-not-deployed',
      region: '-',
      version: '',
      versionOutdated: false,
      action: 'deploy',
      actionRoute: '/setup/multi-account',
      templateName: COMPONENT_TEMPLATE_MAP['management'],
    })
  }

  // 3. Assume Role Stack
  const role = d?.stacks.find(s => s.component === 'assume-role')
  if (role) {
    const ver = role.version || ''
    components.push({
      key: 'assume-role',
      label: 'Assume Role',
      name: role.stack_name,
      type: 'Stack',
      statusText: role.status,
      pillClass: stackStatusPill(role.status),
      region: role.region,
      version: ver,
      versionOutdated: !!(localVer && (!ver || ver !== localVer)),
      action: 'manage',
      actionRoute: '/setup/assume-role',
      templateName: COMPONENT_TEMPLATE_MAP['assume-role'],
    })
  } else {
    const tier = permissionStore.tier
    const hasNativePerms = tier === 'enterprise' || tier === 'standard'
    components.push({
      key: 'assume-role',
      label: 'Assume Role',
      name: 'BlueArchCLI-Role',
      type: 'Stack',
      statusText: hasNativePerms ? 'Not needed' : 'Not Deployed',
      pillClass: hasNativePerms ? 'pill-neutral' : 'pill-not-deployed',
      region: '-',
      version: '',
      versionOutdated: false,
      action: hasNativePerms ? 'none' : 'deploy',
      actionRoute: '/setup/assume-role',
      templateName: COMPONENT_TEMPLATE_MAP['assume-role'],
    })
  }

  // 4. CUR Stack
  const cur = d?.stacks.find(s => s.component === 'cost-reports')
  if (cur) {
    const ver = cur.version || ''
    components.push({
      key: 'cur',
      label: 'Cost Reports',
      name: cur.stack_name,
      type: 'Stack',
      statusText: cur.status,
      pillClass: stackStatusPill(cur.status),
      region: cur.region,
      version: ver,
      versionOutdated: !!(localVer && (!ver || ver !== localVer)),
      action: 'delete',
      templateName: COMPONENT_TEMPLATE_MAP['cur'],
    })
  } else {
    components.push({
      key: 'cur',
      label: 'Cost Reports',
      name: 'BlueArchCUR',
      type: 'Stack',
      statusText: 'Not Deployed',
      pillClass: 'pill-not-deployed',
      region: 'us-east-1',
      version: '',
      versionOutdated: false,
      action: 'deploy',
      templateName: COMPONENT_TEMPLATE_MAP['cur'],
    })
  }

  // 5. Event Tracking (part of cross-account infrastructure)
  const etActive = etData.value && etData.value.active_queues > 0
  const etHasQueues = etData.value && etData.value.total_queues > 0
  if (etActive || etHasQueues) {
    const queueInfo = ` (${etData.value!.active_queues}/${etData.value!.total_queues} queues)`
    components.push({
      key: 'event-tracking',
      label: 'Event Tracking',
      name: 'Real-time resource monitoring',
      type: 'Feature',
      statusText: 'Active' + queueInfo,
      pillClass: 'pill-success',
      region: '-',
      version: '',
      versionOutdated: false,
      action: 'delete',
      templateName: COMPONENT_TEMPLATE_MAP['event-tracking'],
    })
  } else if (etData.value && etData.value.stackset_exists) {
    // Infrastructure deployed but not activated
    components.push({
      key: 'event-tracking',
      label: 'Event Tracking',
      name: 'Real-time resource monitoring',
      type: 'Feature',
      statusText: 'Not Activated',
      pillClass: 'pill-neutral',
      region: '-',
      version: '',
      versionOutdated: false,
      action: 'deploy',
      templateName: COMPONENT_TEMPLATE_MAP['event-tracking'],
    })
  } else {
    components.push({
      key: 'event-tracking',
      label: 'Event Tracking',
      name: 'Real-time resource monitoring',
      type: 'Feature',
      statusText: 'Not Deployed',
      pillClass: 'pill-not-deployed',
      region: '-',
      version: '',
      versionOutdated: false,
      action: 'none',
      templateName: COMPONENT_TEMPLATE_MAP['event-tracking'],
    })
  }

  return components
})

function loadInfrastructure() {
  return setupStore.loadInfrastructure()
}

async function handleCreateRG() {
  rgLoading.value = true
  try {
    const result = await api.createResourceGroup()
    if (infraData.value) {
      infraData.value.resource_group = result
    }
  } catch {
    // Error shown by API client
  } finally {
    rgLoading.value = false
  }
}

async function handleDeleteRG() {
  rgLoading.value = true
  try {
    await api.deleteResourceGroup()
    if (infraData.value) {
      infraData.value.resource_group = { exists: false, name: '', resource_count: 0 }
    }
  } catch {
    // Error shown by API client
  } finally {
    rgLoading.value = false
  }
}

async function handleComponentAction(comp: InfraComponent) {
  if (comp.action === 'deploy') {
    if (comp.key === 'event-tracking') {
      handleDeployET()
    } else if (comp.key === 'cur') {
      componentActioning.value = comp.key
      try {
        const job = await api.deployCurStack({ report_name: 'tag-manager-cur' })
        await pollInfrastructureJob(job.job_id)
      } catch {
        // Error shown by API client
      } finally {
        componentActioning.value = null
      }
    } else if (comp.actionRoute) {
      router.push(comp.actionRoute)
    }
    return
  }
  if (comp.action === 'delete') {
    if (comp.key === 'cur') {
      if (!confirm('Delete the BlueArchCUR CloudFormation stack? This will remove CUR report integration.')) return
      componentActioning.value = comp.key
      try {
        await api.deleteCurStack()
        await loadInfrastructure()
      } catch {
        // Error shown by API client
      } finally {
        componentActioning.value = null
      }
    } else if (comp.key === 'event-tracking') {
      if (!confirm('Deactivate event tracking? This will stop monitoring and clean up tracking records.')) return
      componentActioning.value = comp.key
      try {
        const job = await api.removeAllEventTracking()
        const pollJob = async () => {
          try {
            const status = await api.getJob(job.job_id)
            if (status.status === 'completed' || status.status === 'failed') {
              componentActioning.value = null
              await Promise.all([loadEventTracking(), loadInfrastructure()])
            } else {
              setTimeout(pollJob, 3000)
            }
          } catch {
            componentActioning.value = null
          }
        }
        setTimeout(pollJob, 3000)
      } catch {
        componentActioning.value = null
      }
    }
  }
}

async function pollInfrastructureJob(jobId: string) {
  await new Promise<void>((resolve) => {
    const poll = setInterval(async () => {
      try {
        const job = await api.getJob(jobId)
        if (job.status === 'completed' || job.status === 'failed') {
          clearInterval(poll)
          await loadInfrastructure()
          resolve()
        }
      } catch {
        clearInterval(poll)
        resolve()
      }
    }, 3000)
  })
}

const componentApiName: Record<string, string> = {
  'cur': 'cost-reports',
  'management': 'management-resources',
}

async function handleUpdateStack(component: string) {
  updatingComponent.value = component
  try {
    await api.updateInfraStack(componentApiName[component] || component)
    // Give CF time to start, then refresh
    setTimeout(() => loadInfrastructure(), 3000)
  } catch {
    // Error shown by API client
  } finally {
    updatingComponent.value = null
  }
}

// --- Event Tracking ---

const etData = ref<EventTrackingStatusResponse | null>(null)
const etLoading = ref(false)
const etActionLoading = ref<string | null>(null)
const etRemovingInstance = ref<string | null>(null)
const etDeploying = ref(false)
const etScanning = ref(false)
const etScanMessage = ref('')

async function loadEventTracking() {
  etLoading.value = true
  try {
    etData.value = await api.eventTrackingStatus()
  } catch {
    // Error shown by API client
  } finally {
    etLoading.value = false
  }
}

const etHasInstances = computed(() => {
  return etData.value && etData.value.instances.length > 0
})

async function handleEventTrackingServiceAction(action: string) {
  etActionLoading.value = action
  try {
    await api.eventTrackingService(action)
    await loadEventTracking()
  } catch {
    // Error shown by API client
  } finally {
    etActionLoading.value = null
  }
}

async function handleRemoveETInstance(inst: EventTrackingInstanceStatus) {
  const key = `${inst.account_id}:${inst.region}`
  if (!confirm(`Remove event tracking from ${inst.account_id} / ${inst.region}?`)) return
  etRemovingInstance.value = key
  try {
    await api.removeEventTracking({ [inst.account_id]: [inst.region] })
    // Refresh after a short delay to let CF start
    setTimeout(() => loadEventTracking(), 3000)
  } catch {
    // Error shown by API client
  } finally {
    etRemovingInstance.value = null
  }
}

async function handleRemoveAllET() {
  if (!confirm('Deactivate ALL event tracking? This will stop monitoring and clean up all tracking records.')) return
  etActionLoading.value = 'remove-all'
  try {
    await api.removeAllEventTracking()
    setTimeout(() => loadEventTracking(), 5000)
  } catch {
    // Error shown by API client
  } finally {
    etActionLoading.value = null
  }
}

async function handleDeployET() {
  // Deploy to current account + region (defaults from infra data)
  const accountId = infraData.value?.account_id
  const region = infraData.value?.region
  if (!accountId || !region) {
    return
  }
  etDeploying.value = true
  try {
    const job = await api.deployEventTracking({ [accountId]: [region] })
    // Poll deploy job until complete
    const pollJob = async () => {
      try {
        const status = await api.getJob(job.job_id)
        if (status.status === 'completed' || status.status === 'failed') {
          etDeploying.value = false
          // Refresh both ET status and infrastructure
          await Promise.all([loadEventTracking(), loadInfrastructure()])

          // Chain scan job if backend started one
          const scanJobId = status.result?.scan_job_id as string | undefined
          if (scanJobId && status.status === 'completed') {
            etScanning.value = true
            etScanMessage.value = 'Scanning resources across all accounts...'
            pollScanJob(scanJobId)
          }
        } else {
          setTimeout(pollJob, 3000)
        }
      } catch {
        etDeploying.value = false
      }
    }
    setTimeout(pollJob, 3000)
  } catch {
    etDeploying.value = false
  }
}

function pollScanJob(scanJobId: string) {
  const poll = async () => {
    try {
      const status = await api.getJob(scanJobId)
      if (status.progress_message) {
        etScanMessage.value = status.progress_message
      }
      if (status.status === 'completed' || status.status === 'failed') {
        etScanning.value = false
        etScanMessage.value = ''
        // Refresh ET status to reflect newly scanned resources
        await loadEventTracking()
      } else {
        setTimeout(poll, 3000)
      }
    } catch {
      etScanning.value = false
      etScanMessage.value = ''
    }
  }
  setTimeout(poll, 3000)
}

function formatTimeAgo(isoString?: string): string {
  if (!isoString) return '-'
  const d = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay}d ago`
}

function refreshAll() {
  loadEventTracking()
  return setupStore.refreshAll()
}

// --- IAM Policy ---

function loadIamPolicy() {
  return setupStore.loadIamPolicy()
}

function toggleIamPolicy() {
  iamPolicyExpanded.value = !iamPolicyExpanded.value
  if (iamPolicyExpanded.value && !iamPolicy.value) {
    loadIamPolicy()
  }
}

function toggleStatement(sid: string) {
  const idx = expandedStatements.value.indexOf(sid)
  if (idx >= 0) {
    expandedStatements.value.splice(idx, 1)
  } else {
    expandedStatements.value.push(sid)
  }
}

async function copyIamPolicy() {
  if (!iamPolicy.value) return
  try {
    await navigator.clipboard.writeText(JSON.stringify(iamPolicy.value, null, 2))
  } catch {
    console.error('Failed to copy')
  }
}

async function downloadIamPolicy() {
  if (!iamPolicy.value) {
    await loadIamPolicy()
  }
  if (!iamPolicy.value) return

  const blob = new Blob([JSON.stringify(iamPolicy.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'bluearch-iam-policy.json'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// --- Validation ---

const ssoExpiredCheck = computed(() => {
  if (!result.value) return null
  const awsCheck = result.value.checks.find(c => c.name === 'AWS Credentials')
  if (!awsCheck || awsCheck.status !== 'error') return null
  if (awsCheck.details?.error_type === 'sso_expired') {
    return awsCheck
  }
  return null
})

const credentialsNotConfigured = computed(() => {
  if (!result.value) return null
  const awsCheck = result.value.checks.find(c => c.name === 'AWS Credentials')
  if (!awsCheck || awsCheck.status !== 'error') return null
  const errorType = awsCheck.details?.error_type
  if (errorType === 'no_credentials' || errorType === 'profile_not_found') {
    return awsCheck
  }
  return null
})

async function copySsoCmd() {
  try {
    await navigator.clipboard.writeText('aws sso login')
  } catch {
    // ignore
  }
}

// Adjust overall status: if the only warnings are Assume Role / Multi-Account
// and user already has enterprise-level permissions, those warnings are irrelevant.
const adjustedOverall = computed(() => {
  if (!result.value) return ''
  const raw = result.value.overall
  if (raw !== 'degraded') return raw
  const tier = permissionStore.tier
  if (tier === 'enterprise' || tier === 'standard') {
    const realWarnings = result.value.checks.filter(
      c => c.status === 'warning' && !multiAccountCheckNames.includes(c.name)
    )
    if (realWarnings.length === 0) return 'healthy'
  }
  return raw
})

const overallIcon = computed(() => {
  switch (adjustedOverall.value) {
    case 'healthy': return 'pi pi-check-circle'
    case 'degraded': return 'pi pi-exclamation-triangle'
    case 'unhealthy': return 'pi pi-times-circle'
    default: return 'pi pi-question-circle'
  }
})

const overallLabel = computed(() => {
  switch (adjustedOverall.value) {
    case 'healthy': return 'All Systems Healthy'
    case 'degraded': return 'System Degraded'
    case 'unhealthy': return 'System Unhealthy'
    default: return 'Unknown'
  }
})

const overallDescription = computed(() => {
  if (!result.value) return ''
  const tier = permissionStore.tier
  const hasNativePerms = tier === 'enterprise' || tier === 'standard'
  // Count checks, treating Assume Role/Multi-Account warnings as OK when user has native perms
  let ok = 0, warn = 0, err = 0
  for (const c of result.value.checks) {
    const adjusted = (hasNativePerms && c.status === 'warning' && multiAccountCheckNames.includes(c.name)) ? 'ok' : c.status
    if (adjusted === 'ok') ok++
    else if (adjusted === 'warning') warn++
    else if (adjusted === 'error') err++
  }
  const parts = []
  if (ok) parts.push(`${ok} passed`)
  if (warn) parts.push(`${warn} warnings`)
  if (err) parts.push(`${err} errors`)
  return parts.join(', ')
})

function statusIcon(status: string): string {
  switch (status) {
    case 'ok': return 'pi pi-check-circle'
    case 'warning': return 'pi pi-exclamation-triangle'
    case 'error': return 'pi pi-times-circle'
    default: return 'pi pi-question-circle'
  }
}

// Filter out multi-account checks from the main grid (shown in dedicated section)
const multiAccountCheckNames = ['Assume Role', 'Multi-Account']

const coreChecks = computed(() => {
  if (!result.value) return []
  return result.value.checks.filter(c => !multiAccountCheckNames.includes(c.name))
})

const multiAccountOverall = computed(() => {
  if (!result.value) return null
  const checks = result.value.checks.filter(c => multiAccountCheckNames.includes(c.name))
  if (!checks.length) return null
  // If user has enterprise/standard perms, treat Assume Role warnings as OK
  const tier = permissionStore.tier
  const adjustedStatuses = checks.map(c => {
    if (c.name === 'Assume Role' && c.status === 'warning' && (tier === 'enterprise' || tier === 'standard')) {
      return 'ok'
    }
    return c.status
  })
  if (adjustedStatuses.every(s => s === 'ok')) return 'ok'
  if (adjustedStatuses.includes('error')) return 'error'
  return 'warning'
})

function filteredDetails(details: Record<string, unknown> | null): Record<string, unknown> {
  if (!details) return {}
  const hidden = ['hint', 'note', 'fix']
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(details)) {
    if (!hidden.includes(k)) out[k] = v
  }
  return out
}

const getAssumeRoleStatus = computed(() => {
  if (!result.value) return { class: '', icon: '', message: '', details: null }
  const check = result.value.checks.find(c => c.name === 'Assume Role')
  if (!check) return {
    class: 'config-unknown',
    icon: 'pi pi-question-circle',
    message: 'Status unknown',
    details: null,
  }
  // If user has enterprise/standard permissions natively, Assume Role is optional
  const tier = permissionStore.tier
  if (check.status === 'warning' && (tier === 'enterprise' || tier === 'standard')) {
    return {
      class: 'config-ok',
      icon: 'pi pi-check-circle',
      message: 'Not required - you have sufficient IAM permissions',
      details: null,
    }
  }
  return {
    class: `config-${check.status}`,
    icon: statusIcon(check.status),
    message: check.message,
    details: check.details,
  }
})

const getMultiAccountStatus = computed(() => {
  if (!result.value) return { class: '', icon: '', message: '', details: null }
  const check = result.value.checks.find(c => c.name === 'Multi-Account')
  if (!check) return {
    class: 'config-unknown',
    icon: 'pi pi-question-circle',
    message: 'Status unknown',
    details: null,
  }
  return {
    class: `config-${check.status}`,
    icon: statusIcon(check.status),
    message: check.message,
    details: check.details,
  }
})

function runValidation() {
  return setupStore.runValidation()
}

onMounted(() => {
  // Always refresh in background, but cached data shows instantly
  contextStore.loadCurrent({ background: true })
  contextStore.loadAll({ background: true })
  permissionStore.load({ background: true })
  setupStore.runValidation({ background: true })
  setupStore.loadInfrastructure({ background: true })
  loadEventTracking()
})
</script>

<style scoped>
.setup-view {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.setup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.setup-title {
  font-size: 1.1rem;
  font-weight: 600;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: all 0.15s;
}

.btn-primary {
  background: var(--gradient-brand-horizontal);
  color: white;
}

.btn-primary:hover { box-shadow: 0 0 14px rgba(32, 108, 245, 0.35); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* SSO Alert */
.sso-alert {
  display: flex;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.25);
  border-radius: 10px;
  color: #facc15;
}

.sso-alert-icon {
  font-size: 1.4rem;
  flex-shrink: 0;
  color: #facc15;
}

.sso-alert-body strong {
  font-size: 0.95rem;
  display: block;
  margin-bottom: 0.3rem;
}

.sso-alert-body p {
  font-size: 0.82rem;
  margin: 0 0 0.5rem;
  opacity: 0.85;
}

.sso-cmd-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
}

.sso-cmd-row code {
  display: inline-block;
  background: #1e293b;
  color: #e2e8f0;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  font-family: 'SF Mono', monospace;
  font-size: 0.85rem;
  user-select: all;
}

.btn-copy {
  background: none;
  border: 1px solid rgba(234, 179, 8, 0.25);
  border-radius: 4px;
  padding: 0.3rem 0.5rem;
  cursor: pointer;
  color: #facc15;
  font-size: 0.8rem;
  transition: all 0.15s;
}

.btn-copy:hover {
  background: rgba(234, 179, 8, 0.15);
}

.sso-hint {
  font-size: 0.76rem;
  opacity: 0.7;
  margin: 0;
}

/* Credentials Not Configured Alert */
.creds-alert {
  display: flex;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 10px;
  color: #f87171;
}

.creds-alert-icon {
  font-size: 1.4rem;
  flex-shrink: 0;
  color: #f87171;
}

.creds-alert-body strong {
  font-size: 0.95rem;
  display: block;
  margin-bottom: 0.3rem;
}

.creds-alert-body p {
  font-size: 0.82rem;
  margin: 0 0 0.5rem;
  opacity: 0.85;
}

.creds-options {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.creds-option-label {
  font-size: 0.78rem;
  font-weight: 600;
  display: block;
  margin-bottom: 0.25rem;
}

/* Status Banner */
.status-banner {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  border-radius: 10px;
  border: 1px solid;
}

.status-healthy {
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.25);
  color: #4ade80;
}

.status-degraded {
  background: rgba(234, 179, 8, 0.12);
  border-color: rgba(234, 179, 8, 0.25);
  color: #facc15;
}

.status-unhealthy {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.25);
  color: #f87171;
}

.status-icon {
  font-size: 1.5rem;
  flex-shrink: 0;
}

.status-body strong {
  font-size: 0.95rem;
  display: block;
}

.status-body p {
  font-size: 0.82rem;
  opacity: 0.85;
  margin: 0.15rem 0 0;
}

/* Check Cards */
.checks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 0.75rem;
}

.check-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  border-left: 4px solid;
}

.check-ok { border-left-color: #22c55e; }
.check-warning { border-left-color: #eab308; }
.check-error { border-left-color: #ef4444; }

.check-icon {
  font-size: 1.1rem;
  flex-shrink: 0;
  margin-top: 1px;
}

.check-ok .check-icon { color: #22c55e; }
.check-warning .check-icon { color: #eab308; }
.check-error .check-icon { color: #ef4444; }

.check-body {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.check-name {
  font-weight: 600;
  font-size: 0.88rem;
  color: var(--text-color);
}

.check-message {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  word-break: break-word;
}

.check-details {
  margin-top: 0.35rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.detail-row {
  display: flex;
  gap: 0.5rem;
  font-size: 0.76rem;
}

.detail-key {
  color: var(--text-color-secondary);
  min-width: 80px;
  font-weight: 500;
}

.detail-val {
  color: var(--text-color);
  font-family: 'SF Mono', monospace;
  font-size: 0.74rem;
  word-break: break-all;
}

/* CLI Commands Section */
.section-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.section-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-header.clickable {
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-header.clickable:hover {
  background: var(--surface-ground);
}

.section-title {
  font-size: 0.95rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.section-title i {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}

.cli-commands {
  padding: 1rem 1.25rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1.5rem;
}

.cli-group h4 {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.cli-cmd {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.35rem 0;
}

.cli-cmd code {
  background: var(--surface-ground);
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-family: 'SF Mono', monospace;
  font-size: 0.76rem;
  color: var(--primary-color);
  white-space: nowrap;
}

.cli-cmd span {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

/* IAM Policy Styles */
.iam-policy-content {
  padding: 1rem 1.25rem;
}

.iam-loading,
.iam-error {
  padding: 1rem;
  text-align: center;
  color: var(--text-color-secondary);
}

.iam-error {
  color: #ef4444;
}

.iam-policy-groups {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.iam-policy-group {
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  overflow: hidden;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.65rem 1rem;
  background: var(--surface-ground);
  cursor: pointer;
  font-size: 0.85rem;
}

.group-header:hover {
  background: var(--surface-card-hover);
}

.group-header i {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}

.group-name {
  font-weight: 600;
  color: var(--text-color);
}

.group-action-count {
  margin-left: auto;
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  background: var(--surface-card);
  padding: 0.15rem 0.4rem;
  border-radius: 8px;
}

.group-details {
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  border-top: 1px solid var(--surface-border);
  background: var(--surface-card);
}

.detail-section {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.detail-label {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-color-secondary);
  min-width: 60px;
}

.detail-value {
  font-size: 0.82rem;
  color: var(--text-color);
}

.effect-allow {
  color: #4ade80;
  font-weight: 600;
}

.actions-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.actions-list code {
  background: rgba(32, 108, 245, 0.12);
  color: #5a9aff;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-family: 'SF Mono', monospace;
  font-size: 0.72rem;
}

.resource-value {
  font-family: 'SF Mono', monospace;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  word-break: break-all;
}

.btn-sm {
  padding: 0.3rem 0.65rem;
  font-size: 0.78rem;
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--surface-border);
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Multi-Account Section */
.section-header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ma-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  font-weight: 500;
  padding: 0.25rem 0.65rem;
  border-radius: 12px;
}

.ma-badge i { font-size: 0.75rem; }
.ma-badge-ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.ma-badge-warning { background: rgba(234, 179, 8, 0.12); color: #facc15; }
.ma-badge-error { background: rgba(239, 68, 68, 0.15); color: #f87171; }

.multi-account-content {
  padding: 1rem 1.25rem;
}

.config-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.config-card {
  display: flex;
  gap: 0.85rem;
  padding: 1rem 1.25rem;
  border-radius: 10px;
  border: 1px solid;
  background: var(--surface-ground);
}

.config-ok {
  border-color: rgba(34, 197, 94, 0.25);
  background: rgba(34, 197, 94, 0.12);
}

.config-warning {
  border-color: rgba(234, 179, 8, 0.25);
  background: rgba(234, 179, 8, 0.12);
}

.config-error {
  border-color: rgba(239, 68, 68, 0.25);
  background: rgba(239, 68, 68, 0.1);
}

.config-unknown {
  border-color: var(--surface-border);
}

.config-icon {
  font-size: 1.35rem;
  flex-shrink: 0;
}

.config-ok .config-icon { color: #22c55e; }
.config-warning .config-icon { color: #eab308; }
.config-error .config-icon { color: #ef4444; }
.config-unknown .config-icon { color: var(--text-color-secondary); }

.config-body h4 {
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.config-body p {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  margin: 0;
}

.config-desc {
  font-size: 0.76rem;
  margin-bottom: 0.3rem;
}

.config-status {
  font-weight: 500;
  color: var(--text-color);
}

.config-details {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.config-details span {
  font-size: 0.75rem;
  color: var(--text-color);
}

.config-details strong {
  color: var(--text-color-secondary);
  font-weight: 500;
}

.setup-instructions {
  background: var(--surface-card-hover);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1rem 1.25rem;
}

.setup-instructions h4 {
  font-size: 0.88rem;
  font-weight: 600;
  margin-bottom: 1rem;
  color: var(--text-color);
}

.instruction-steps {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.step {
  display: flex;
  gap: 1rem;
}

.step-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--gradient-brand-horizontal);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
  box-shadow: 0 0 10px rgba(32, 108, 245, 0.3);
}

.step-content {
  flex: 1;
}

.step-content strong {
  font-size: 0.85rem;
  display: block;
  margin-bottom: 0.35rem;
}

.step-content code {
  display: inline-block;
  background: #1e293b;
  color: #e2e8f0;
  padding: 0.35rem 0.65rem;
  border-radius: 6px;
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
  margin-bottom: 0.35rem;
}

.step-content p {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin: 0;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 4rem 2rem;
  color: var(--text-color-secondary);
}

.empty-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(32, 108, 245, 0.12);
  color: #5a9aff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  margin-bottom: 1rem;
}

.empty-state h3 {
  font-size: 1.1rem;
  color: var(--text-color);
  margin-bottom: 0.5rem;
}

.empty-state p {
  font-size: 0.875rem;
  margin-bottom: 1.5rem;
  max-width: 400px;
}

/* Infrastructure Section */
.setup-header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.infra-loading-badge {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.account-bar {
  display: flex;
  gap: 1.5rem;
  padding: 0.65rem 1.25rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  border-bottom: 1px solid var(--surface-border);
}

.account-bar strong {
  color: var(--text-color-secondary);
  font-weight: 500;
  margin-right: 0.3rem;
}

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

.component-badge {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  font-size: 0.72rem;
  font-family: 'SF Mono', monospace;
  background: rgba(32, 108, 245, 0.12);
  color: #5a9aff;
}

.status-pill {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 600;
}

.pill-success { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.pill-warning { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.pill-danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.pill-neutral { background: var(--surface-card-hover); color: var(--text-color-secondary); }
.pill-not-deployed { background: var(--surface-ground); color: var(--text-color-secondary); opacity: 0.7; }

.action-na {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover:not(:disabled) { background: #dc2626; }
.btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }

/* Resource Group Compact Row */
.rg-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--surface-border);
  gap: 1rem;
}

.rg-row-left {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
}

.rg-row-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
}

.rg-row-detail {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.rg-row-count {
  font-size: 0.75rem;
  opacity: 0.7;
}

.rg-row-actions {
  flex-shrink: 0;
}

/* Version column */
.version-text {
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
  color: var(--text-color);
}

.version-outdated {
  color: #facc15;
}

.version-hint {
  font-size: 0.68rem;
  font-family: inherit;
  opacity: 0.8;
  margin-left: 0.25rem;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.btn-ghost {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
  padding: 0.25rem 0.45rem;
  -webkit-text-fill-color: initial;
  line-height: 1;
}

.btn-ghost:hover {
  background: rgba(32, 108, 245, 0.15);
  color: var(--primary-color);
  border-color: var(--primary-color);
}

/* Permission Tier Section */
.tier-section {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.tier-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.tier-context {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.88rem;
}

.tier-context > i {
  color: var(--text-color-secondary);
  font-size: 0.95rem;
}

.tier-account {
  font-weight: 600;
  color: var(--text-color);
}

.tier-badge {
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  font-family: var(--font-mono);
}

.tier-none { background: rgba(160, 160, 160, 0.15); color: #a0a0a0; }
.tier-unknown { background: rgba(160, 160, 160, 0.15); color: #a0a0a0; }
.tier-basic { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.tier-standard { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.tier-enterprise { background: rgba(25, 212, 212, 0.15); color: #19D4D4; }

/* Tier Stepper */
.tier-stepper {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 0;
  padding: 1.5rem 1.25rem;
  position: relative;
}

.tier-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  flex: 1;
  position: relative;
}

.tier-step::before,
.tier-step::after {
  content: '';
  position: absolute;
  top: 16px;
  height: 2px;
  background: var(--surface-border);
}

.tier-step::before {
  right: 50%;
  left: 0;
}

.tier-step::after {
  left: 50%;
  right: 0;
}

.tier-step:first-child::before { display: none; }
.tier-step:last-child::after { display: none; }

.tier-step.completed::before,
.tier-step.completed::after {
  background: var(--color-success, #22c55e);
}

.tier-step.active::before {
  background: var(--color-success, #22c55e);
}

.step-marker {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
  font-weight: 600;
  background: var(--surface-ground);
  border: 2px solid var(--surface-border);
  color: var(--text-color-secondary);
  position: relative;
  z-index: 1;
  transition: all 0.2s;
}

.tier-step.active .step-marker {
  background: var(--surface-card);
  border-image: var(--gradient-brand-horizontal) 1;
  border-style: solid;
  border-width: 2px;
  border-radius: 50%;
  border-image: none;
  border-color: #5a9aff;
  color: #5a9aff;
  box-shadow: 0 0 12px rgba(32, 108, 245, 0.35);
}

.tier-step.completed .step-marker {
  background: var(--color-success, #22c55e);
  border-color: var(--color-success, #22c55e);
  color: white;
}

.tier-step.warning .step-marker {
  background: rgba(245, 158, 11, 0.15);
  border-color: #f59e0b;
  color: #f59e0b;
  box-shadow: 0 0 10px rgba(245, 158, 11, 0.25);
}

.tier-step.warning::before {
  background: #f59e0b;
}

.step-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color-secondary);
}

.tier-step.active .step-label {
  color: var(--text-color);
}

.tier-step.completed .step-label {
  color: var(--color-success, #22c55e);
}

.tier-step.warning .step-label {
  color: #f59e0b;
}

.tier-step.skipped .step-marker {
  background: var(--surface-ground);
  border-color: var(--surface-border);
  border-style: dashed;
  color: var(--text-color-secondary);
  opacity: 0.6;
}

.tier-step.skipped .step-label {
  color: var(--text-color-secondary);
  opacity: 0.6;
}

.tier-step.skipped::before,
.tier-step.skipped::after {
  background: var(--color-success, #22c55e);
}

.step-desc {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  opacity: 0.7;
  text-align: center;
}

/* Feature Checklist */
.feature-checklist {
  padding: 1rem 1.25rem;
  border-top: 1px solid var(--surface-border);
}

.checklist-title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 0.75rem;
}

.checklist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.5rem;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.5rem;
  border-radius: 6px;
  font-size: 0.82rem;
  background: var(--surface-ground);
}

.feature-item .pi {
  font-size: 0.85rem;
  flex-shrink: 0;
}

.feature-available { color: var(--color-success, #22c55e); }
.feature-partial-icon { color: var(--color-warning, #eab308); }
.feature-unavailable { color: var(--color-danger, #ef4444); }

.feature-name {
  color: var(--text-color);
  font-size: 0.8rem;
}

.feature-partial {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--color-warning, #eab308);
  background: rgba(234, 179, 8, 0.12);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  margin-left: auto;
}

/* Upgrade Path */
.upgrade-path {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid var(--surface-border);
  background: rgba(25, 212, 212, 0.05);
  align-items: flex-start;
}

.upgrade-path > i {
  color: #19D4D4;
  font-size: 1.1rem;
  flex-shrink: 0;
  margin-top: 0.1rem;
}

.upgrade-content {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.upgrade-content strong {
  font-size: 0.88rem;
  color: #19D4D4;
}

.upgrade-content > span {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.upgrade-unlocks {
  font-size: 0.76rem;
  color: var(--text-color-secondary);
  opacity: 0.8;
}

/* Event Tracking Section */
.et-empty {
  display: flex;
  gap: 1rem;
  padding: 1.5rem 1.25rem;
  color: var(--text-color-secondary);
  align-items: flex-start;
}

.et-empty > i {
  font-size: 1.5rem;
  color: #facc15;
  flex-shrink: 0;
  margin-top: 0.1rem;
}

.et-empty strong {
  display: block;
  font-size: 0.88rem;
  color: var(--text-color);
  margin-bottom: 0.25rem;
}

.et-empty p {
  font-size: 0.8rem;
  margin: 0;
  line-height: 1.5;
}

.et-deploy-actions {
  margin-top: 0.75rem;
}

.et-deploy-progress {
  margin-top: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
  color: var(--primary-color);
}

.et-scan-progress {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.85rem 1.25rem;
  background: rgba(32, 108, 245, 0.08);
  border-top: 1px solid rgba(32, 108, 245, 0.15);
  color: var(--primary-color);
  font-size: 0.82rem;
}

.et-scan-progress > i {
  font-size: 1rem;
  flex-shrink: 0;
}

.et-scan-progress strong {
  display: block;
  font-size: 0.82rem;
  margin-bottom: 0.15rem;
}

.et-scan-progress p {
  font-size: 0.76rem;
  margin: 0;
  opacity: 0.8;
  color: var(--text-color-secondary);
}

.et-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--surface-border);
  gap: 1rem;
  flex-wrap: wrap;
}

.et-controls-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.et-controls-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
}

.et-stat {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  padding: 0.15rem 0.5rem;
  border-radius: 8px;
}

.et-controls-right {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}


.progress-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  font-size: 0.9rem;
}

.progress-bar-wrap {
  height: 6px;
  background: var(--surface-ground);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: var(--gradient-brand-horizontal);
  border-radius: 3px;
  transition: width 0.5s ease;
}

.pro-deploy-result {
  padding: 1.5rem;
}

.result-success {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  color: #4ade80;
}

.result-success .pi-check-circle {
  font-size: 1.5rem;
  margin-top: 0.1rem;
}

.result-error {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  color: #f87171;
}

.result-error .pi-times-circle {
  font-size: 1.5rem;
  margin-top: 0.1rem;
}

.result-body {
  flex: 1;
}

.result-body strong {
  font-size: 1rem;
  color: var(--text-color);
}

.result-body p {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  margin: 0.25rem 0 0.75rem;
}

.result-details {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.result-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
}

.result-label {
  font-weight: 600;
  color: var(--text-color-secondary);
  min-width: 120px;
}

.result-link {
  color: #5a9aff;
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.result-link:hover {
  text-decoration: underline;
}

.result-password {
  background: var(--surface-ground);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-family: monospace;
  font-size: 0.85rem;
  user-select: all;
}

.result-hint {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  opacity: 0.8;
}

/* Dialog styles */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.dialog {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.75rem;
  width: 100%;
  max-width: 480px;
  box-shadow: 0 0 30px rgba(32, 108, 245, 0.15), 0 8px 32px rgba(0, 0, 0, 0.4);
}

.dialog h3 {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 0.5rem;
}

.dialog-desc {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  margin: 0 0 1rem;
  line-height: 1.5;
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.dialog-form .form-group {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.dialog-form label {
  font-size: 0.82rem;
  font-weight: 500;
}

.dialog-form input,
.dialog-form select {
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.875rem;
  outline: none;
  background: var(--surface-card);
  color: var(--text-color);
}

.dialog-form input:focus,
.dialog-form select:focus {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(32, 108, 245, 0.15);
}

.dialog-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
  margin-top: 0.5rem;
}

.alert {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  border-radius: 6px;
  font-size: 0.85rem;
}

.alert-error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #f87171;
}

.alert.small {
  margin-bottom: 0;
}
</style>

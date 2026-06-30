<template>
  <div class="alarms-view">
    <!-- Header -->
    <div class="view-header">
      <div>
        <h2 class="view-title">Alarms</h2>
        <p class="view-subtitle">
          Track recommendations and get notified when thresholds are crossed.
        </p>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" :disabled="evaluating" @click="evaluateAll">
          <i class="pi pi-play" :class="{ spin: evaluating }"></i>
          Evaluate All
        </button>
        <button class="btn btn-primary" @click="openCreateDialog">
          <i class="pi pi-plus"></i>
          New Alarm
        </button>
      </div>
    </div>

    <!-- Result banner -->
    <div v-if="banner" class="result-banner" :class="banner.type">
      <i :class="banner.type === 'success' ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle'"></i>
      <span>{{ banner.message }}</span>
      <button class="btn-dismiss" @click="banner = null"><i class="pi pi-times"></i></button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <i class="pi pi-spin pi-spinner"></i> Loading alarms...
    </div>

    <!-- Empty -->
    <div v-else-if="!alarms.length" class="empty-state">
      <i class="pi pi-bell"></i>
      <h3>No alarms configured</h3>
      <p>Create an alarm to get notified when recommendations match your criteria.</p>
      <button class="btn btn-primary" @click="openCreateDialog">
        <i class="pi pi-plus"></i> Create your first alarm
      </button>
    </div>

    <!-- Alarms list -->
    <div v-else class="alarms-table-card">
      <table class="alarms-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Trigger</th>
            <th>Criteria</th>
            <th>Threshold</th>
            <th>Status</th>
            <th>Last Triggered</th>
            <th>Triggers</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in alarms" :key="a.id">
            <td>
              <div class="alarm-name">{{ a.name }}</div>
              <div v-if="a.description" class="alarm-desc">{{ a.description }}</div>
            </td>
            <td>
              <span class="pill" :class="'trigger-' + a.trigger_type">{{ triggerLabel(a.trigger_type) }}</span>
            </td>
            <td class="criteria-cell">
              <div v-if="a.recommendation_types.length" class="crit-line">
                <i class="pi pi-list"></i>
                {{ a.recommendation_types.length }} rec type{{ a.recommendation_types.length !== 1 ? 's' : '' }}
              </div>
              <div v-if="a.account_ids.length" class="crit-line">
                <i class="pi pi-users"></i>
                {{ a.account_ids.length }} account{{ a.account_ids.length !== 1 ? 's' : '' }}
              </div>
              <div v-if="a.regions.length" class="crit-line">
                <i class="pi pi-globe"></i>
                {{ a.regions.length }} region{{ a.regions.length !== 1 ? 's' : '' }}
              </div>
              <div v-if="a.severity_filter" class="crit-line">
                <i class="pi pi-flag"></i> severity: {{ a.severity_filter }}
              </div>
              <div v-if="!hasCriteria(a)" class="crit-line muted">Any</div>
            </td>
            <td>
              <span class="threshold-pill">≥ {{ a.threshold }}</span>
            </td>
            <td>
              <span class="pill" :class="a.enabled ? 'pill-enabled' : 'pill-disabled'">
                {{ a.enabled ? 'Enabled' : 'Disabled' }}
              </span>
              <div v-if="a.last_match_count > 0" class="match-count">
                {{ a.last_match_count }} matching
              </div>
            </td>
            <td class="mono-sm">{{ formatDate(a.last_triggered_at) }}</td>
            <td>{{ a.trigger_count }}</td>
            <td class="actions-cell">
              <button class="icon-btn" title="View events" @click="viewEvents(a)">
                <i class="pi pi-history"></i>
              </button>
              <button class="icon-btn" title="Evaluate now" @click="evaluateOne(a)">
                <i class="pi pi-play"></i>
              </button>
              <button class="icon-btn" title="Test notification" @click="testNotification(a)">
                <i class="pi pi-send"></i>
              </button>
              <button class="icon-btn" title="Edit" @click="openEditDialog(a)">
                <i class="pi pi-pencil"></i>
              </button>
              <button class="icon-btn icon-btn-danger" title="Delete" @click="confirmDelete(a)">
                <i class="pi pi-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Create / Edit Dialog -->
    <div v-if="showForm" class="dialog-overlay" @click.self="closeForm">
      <div class="dialog dialog-lg">
        <h3>{{ editingId ? 'Edit Alarm' : 'New Alarm' }}</h3>

        <div class="form-row">
          <div class="form-group flex-1">
            <label>Name</label>
            <input v-model="form.name" class="input" placeholder="e.g. Critical S3 public buckets" />
          </div>
          <div class="form-group">
            <label>Threshold</label>
            <input v-model.number="form.threshold" type="number" min="1" class="input input-sm" />
            <span class="hint">Trigger when matches ≥ N</span>
          </div>
        </div>

        <div class="form-group">
          <label>Description (optional)</label>
          <input v-model="form.description" class="input" placeholder="What does this alarm track?" />
        </div>

        <div class="form-group">
          <label>Trigger source</label>
          <div class="radio-row">
            <label class="radio">
              <input v-model="form.trigger_type" type="radio" value="recommendation" />
              Recommendations
            </label>
          </div>
        </div>

        <div class="form-group">
          <label>Recommendation types <span class="hint-inline">(empty = all)</span></label>
          <MultiSelectBox
            v-model="form.recommendation_types"
            :options="options.recommendation_types"
            placeholder="Select recommendation types..."
          />
        </div>

        <div class="form-row">
          <div class="form-group flex-1">
            <label>Account IDs <span class="hint-inline">(empty = all)</span></label>
            <MultiSelectBox
              v-model="form.account_ids"
              :options="options.account_ids"
              placeholder="Select accounts..."
            />
          </div>
          <div class="form-group flex-1">
            <label>Regions <span class="hint-inline">(empty = all)</span></label>
            <MultiSelectBox
              v-model="form.regions"
              :options="options.regions"
              placeholder="Select regions..."
            />
          </div>
        </div>

        <div class="form-group">
          <label>Notification targets</label>
          <div
            v-for="(target, idx) in form.notification_targets"
            :key="idx"
            class="target-row"
          >
            <select v-model="target.type" class="input input-sm target-type">
              <option value="slack">Slack</option>
              <option value="sns">SNS topic</option>
              <option value="email">Email</option>
            </select>
            <input
              v-model="target.value"
              class="input flex-1"
              :placeholder="targetPlaceholder(target.type)"
            />
            <button class="icon-btn icon-btn-danger" @click="removeTarget(idx)">
              <i class="pi pi-times"></i>
            </button>
          </div>
          <button class="btn btn-link" @click="addTarget">
            <i class="pi pi-plus"></i> Add target
          </button>
        </div>

        <div class="form-group">
          <label class="checkbox">
            <input v-model="form.enabled" type="checkbox" />
            Enabled
          </label>
        </div>

        <div v-if="formError" class="form-error">{{ formError }}</div>

        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="closeForm">Cancel</button>
          <button class="btn btn-primary" :disabled="submitting" @click="handleSubmit">
            <i v-if="submitting" class="pi pi-spin pi-spinner"></i>
            {{ editingId ? 'Save' : 'Create' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Events Drawer -->
    <div v-if="eventsAlarm" class="dialog-overlay" @click.self="eventsAlarm = null">
      <div class="dialog dialog-lg">
        <h3>Recent events — {{ eventsAlarm.name }}</h3>
        <div v-if="eventsLoading" class="loading-state">
          <i class="pi pi-spin pi-spinner"></i> Loading...
        </div>
        <div v-else-if="!events.length" class="empty-inline">No events recorded yet.</div>
        <div v-else class="events-wrap">
          <table class="events-table">
            <thead>
              <tr>
                <th>Triggered</th>
                <th>Matches</th>
                <th>Notification</th>
                <th>Sample</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ev in events" :key="ev.id">
                <td class="mono-sm">{{ formatDate(ev.triggered_at) }}</td>
                <td>{{ ev.match_count }}</td>
                <td>
                  <span v-if="ev.notification_sent" class="pill pill-enabled">Sent</span>
                  <span v-else-if="ev.notification_error" class="pill pill-error">Error</span>
                  <span v-else class="pill pill-disabled">Skipped</span>
                  <div v-if="ev.notification_error" class="err-text">{{ ev.notification_error }}</div>
                </td>
                <td class="sample-cell">
                  <div v-for="(m, i) in (ev.match_sample || []).slice(0, 3)" :key="i" class="sample-line">
                    {{ formatSample(m) }}
                  </div>
                  <div v-if="(ev.match_sample || []).length > 3" class="sample-more">
                    +{{ (ev.match_sample || []).length - 3 }} more
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="eventsAlarm = null">Close</button>
        </div>
      </div>
    </div>

    <!-- Delete confirm -->
    <div v-if="deletingAlarm" class="dialog-overlay" @click.self="deletingAlarm = null">
      <div class="dialog">
        <h3>Delete alarm?</h3>
        <p>
          This will permanently delete <strong>{{ deletingAlarm.name }}</strong> and all its event history.
          This action cannot be undone.
        </p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="deletingAlarm = null">Cancel</button>
          <button class="btn btn-danger" @click="handleDelete">Delete</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { api } from '@/api/client'
import type {
  AlarmResponse,
  AlarmCreate,
  AlarmEventResponse,
  AlarmOptions,
} from '@/types/api'
import MultiSelectBox from '@/components/MultiSelectBox.vue'

const alarms = ref<AlarmResponse[]>([])
const loading = ref(false)
const evaluating = ref(false)
const banner = ref<{ type: 'success' | 'error'; message: string } | null>(null)

const options = ref<AlarmOptions>({
  recommendation_types: [],
  account_ids: [],
  regions: [],
  resource_types: [],
  severities: ['low', 'medium', 'high', 'critical'],
  notification_types: ['slack', 'sns', 'email'],
})

// Form state
const showForm = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const formError = ref<string | null>(null)

const defaultForm = (): AlarmCreate => ({
  name: '',
  description: '',
  trigger_type: 'recommendation',
  recommendation_types: [],
  resource_types: [],
  account_ids: [],
  regions: [],
  severity_filter: '',
  threshold: 1,
  notification_targets: [],
  enabled: true,
})

const form = reactive<AlarmCreate>(defaultForm())

// Events drawer
const eventsAlarm = ref<AlarmResponse | null>(null)
const events = ref<AlarmEventResponse[]>([])
const eventsLoading = ref(false)

// Delete confirm
const deletingAlarm = ref<AlarmResponse | null>(null)

onMounted(async () => {
  await Promise.all([loadAlarms(), loadOptions()])
})

async function loadAlarms() {
  loading.value = true
  try {
    alarms.value = await api.listAlarms()
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Failed to load alarms' }
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    options.value = await api.alarmOptions()
  } catch {
    // non-critical
  }
}

function triggerLabel(t: string) {
  if (t === 'recommendation') return 'Recommendations'
  return 'Recommendations'
}

function hasCriteria(a: AlarmResponse) {
  return (
    a.recommendation_types.length ||
    a.account_ids.length ||
    a.regions.length ||
    a.severity_filter
  )
}

function formatDate(iso?: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatSample(m: Record<string, unknown>): string {
  if (!m) return ''
  if (m.kind === 'recommendation') return `${m.type} · ${m.resource_id}`
  return JSON.stringify(m)
}

function targetPlaceholder(type: string) {
  if (type === 'slack') return 'https://hooks.slack.com/services/...'
  if (type === 'sns') return 'arn:aws:sns:us-east-1:123:my-topic'
  return 'alerts@company.com'
}

function openCreateDialog() {
  editingId.value = null
  formError.value = null
  Object.assign(form, defaultForm())
  showForm.value = true
}

function openEditDialog(a: AlarmResponse) {
  editingId.value = a.id
  formError.value = null
  Object.assign(form, {
    name: a.name,
    description: a.description || '',
    trigger_type: a.trigger_type,
    recommendation_types: [...a.recommendation_types],
    resource_types: [...a.resource_types],
    account_ids: [...a.account_ids],
    regions: [...a.regions],
    severity_filter: a.severity_filter || '',
    threshold: a.threshold,
    notification_targets: a.notification_targets.map((t) => ({ ...t })),
    enabled: a.enabled,
  })
  showForm.value = true
}

function closeForm() {
  showForm.value = false
  editingId.value = null
  formError.value = null
}

function addTarget() {
  form.notification_targets = [...(form.notification_targets || []), { type: 'slack', value: '' }]
}

function removeTarget(idx: number) {
  form.notification_targets = (form.notification_targets || []).filter((_, i) => i !== idx)
}

async function handleSubmit() {
  formError.value = null
  if (!form.name.trim()) {
    formError.value = 'Name is required'
    return
  }
  if (form.threshold < 1) {
    formError.value = 'Threshold must be at least 1'
    return
  }
  const invalidTarget = (form.notification_targets || []).find((t) => !t.value.trim())
  if (invalidTarget) {
    formError.value = 'Notification target value cannot be empty'
    return
  }

  submitting.value = true
  try {
    const payload = {
      ...form,
      severity_filter: form.severity_filter || undefined,
    }
    if (editingId.value) {
      await api.updateAlarm(editingId.value, payload)
      banner.value = { type: 'success', message: 'Alarm updated' }
    } else {
      await api.createAlarm(payload)
      banner.value = { type: 'success', message: 'Alarm created' }
    }
    closeForm()
    await loadAlarms()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : 'Failed to save alarm'
  } finally {
    submitting.value = false
  }
}

function confirmDelete(a: AlarmResponse) {
  deletingAlarm.value = a
}

async function handleDelete() {
  if (!deletingAlarm.value) return
  try {
    await api.deleteAlarm(deletingAlarm.value.id)
    banner.value = { type: 'success', message: `Alarm '${deletingAlarm.value.name}' deleted` }
    deletingAlarm.value = null
    await loadAlarms()
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Delete failed' }
  }
}

async function evaluateOne(a: AlarmResponse) {
  try {
    const resp = await api.evaluateAlarm(a.id)
    banner.value = {
      type: 'success',
      message: resp.triggered
        ? `${a.name} triggered — ${resp.match_count} matches (${resp.notification_status})`
        : `${a.name} evaluated — ${resp.match_count} matches (below threshold)`,
    }
    await loadAlarms()
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Evaluate failed' }
  }
}

async function evaluateAll() {
  evaluating.value = true
  try {
    const resp = await api.evaluateAllAlarms()
    banner.value = { type: 'success', message: `Evaluated ${resp.evaluated} alarms` }
    await loadAlarms()
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Evaluate all failed' }
  } finally {
    evaluating.value = false
  }
}

async function testNotification(a: AlarmResponse) {
  try {
    const resp = await api.testAlarmNotification(a.id)
    banner.value = {
      type: resp.success ? 'success' : 'error',
      message: resp.success ? `Test sent to ${a.name} targets` : `Test failed: ${resp.error || 'unknown error'}`,
    }
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Test failed' }
  }
}

async function viewEvents(a: AlarmResponse) {
  eventsAlarm.value = a
  events.value = []
  eventsLoading.value = true
  try {
    events.value = await api.listAlarmEvents(a.id, 50)
  } catch (e) {
    banner.value = { type: 'error', message: e instanceof Error ? e.message : 'Failed to load events' }
  } finally {
    eventsLoading.value = false
  }
}
</script>

<style scoped>
.alarms-view {
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

.view-title {
  font-size: 1.3rem;
  font-weight: 600;
  margin: 0;
}

.view-subtitle {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  margin: 0.25rem 0 0 0;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
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
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--primary-color); color: white; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}
.btn-secondary:hover:not(:disabled) { background: var(--surface-border); }
.btn-danger { background: #ef4444; color: white; }
.btn-danger:hover:not(:disabled) { background: #dc2626; }
.btn-link {
  background: none;
  border: none;
  color: var(--primary-color);
  padding: 0.35rem 0;
  font-size: 0.8rem;
  cursor: pointer;
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Icon buttons */
.icon-btn {
  background: none;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  width: 30px;
  height: 30px;
  cursor: pointer;
  color: var(--text-color-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  transition: all 0.15s;
  margin-right: 0.25rem;
}
.icon-btn:hover {
  background: var(--surface-ground);
  color: var(--text-color);
}
.icon-btn-danger:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.3);
}

/* Result banner */
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

/* Loading / empty */
.loading-state, .empty-state {
  padding: 3rem 1rem;
  text-align: center;
  color: var(--text-color-secondary);
}
.empty-state i {
  font-size: 2.5rem;
  display: block;
  margin-bottom: 1rem;
  opacity: 0.5;
}
.empty-state h3 {
  font-size: 1.05rem;
  margin: 0 0 0.5rem 0;
  color: var(--text-color);
}
.empty-state p {
  font-size: 0.88rem;
  margin: 0 0 1.25rem 0;
}

/* Alarms table */
.alarms-table-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow-x: auto;
}
.alarms-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.alarms-table th {
  text-align: left;
  padding: 0.75rem 1rem;
  background: var(--surface-ground);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-color-secondary);
  border-bottom: 1px solid var(--surface-border);
  font-weight: 600;
}
.alarms-table td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--surface-border);
  vertical-align: top;
}
.alarms-table tbody tr:last-child td { border-bottom: none; }
.alarms-table tbody tr:hover { background: rgba(32, 108, 245, 0.05); }

.alarm-name { font-weight: 600; color: var(--text-color); }
.alarm-desc {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-top: 0.15rem;
}

.criteria-cell { max-width: 220px; }
.crit-line {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  padding: 0.1rem 0;
}
.crit-line.muted { opacity: 0.5; }
.crit-line i { font-size: 0.7rem; }

.pill {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 500;
}
.trigger-recommendation { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.pill-enabled { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.pill-disabled { background: var(--surface-card-hover); color: var(--text-color-secondary); }
.pill-error { background: rgba(239, 68, 68, 0.15); color: #f87171; }

.threshold-pill {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 6px;
  font-family: 'SF Mono', monospace;
  font-size: 0.75rem;
  background: var(--surface-ground);
  color: var(--text-color);
}

.match-count {
  font-size: 0.72rem;
  color: #facc15;
  margin-top: 0.25rem;
}

.mono-sm {
  font-family: 'SF Mono', monospace;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.actions-cell {
  white-space: nowrap;
  text-align: right;
}

/* Dialog */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
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
  max-height: 85vh;
  overflow-y: auto;
}
.dialog-lg { max-width: 680px; }
.dialog h3 {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0 0 1rem 0;
}
.dialog p {
  font-size: 0.85rem;
  color: var(--text-color-secondary);
  line-height: 1.5;
  margin-bottom: 0.5rem;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.5rem;
}

/* Form */
.form-row {
  display: flex;
  gap: 0.75rem;
}
.form-group {
  margin-top: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.form-group.flex-1 { flex: 1; }
.form-group label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-color);
}
.hint, .hint-inline {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  font-weight: 400;
}
.hint-inline { margin-left: 0.35rem; }

.input {
  padding: 0.5rem 0.75rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  color: var(--text-color);
  font-size: 0.85rem;
  width: 100%;
  box-sizing: border-box;
}
.input:focus {
  outline: none;
  border-color: var(--primary-color);
}
.input-sm { max-width: 100px; }

select.input {
  cursor: pointer;
}

.radio-row {
  display: flex;
  gap: 1rem;
  padding: 0.3rem 0;
}
.radio, .checkbox {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
  cursor: pointer;
  color: var(--text-color);
}

.target-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.target-type { max-width: 110px; }

.form-error {
  margin-top: 0.85rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #f87171;
  font-size: 0.8rem;
}

/* Events drawer */
.empty-inline {
  padding: 2rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}
.events-wrap { max-height: 50vh; overflow-y: auto; }
.events-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
.events-table th {
  text-align: left;
  padding: 0.5rem 0.75rem;
  background: var(--surface-ground);
  font-size: 0.72rem;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  border-bottom: 1px solid var(--surface-border);
}
.events-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--surface-border);
  vertical-align: top;
}
.sample-cell {
  max-width: 280px;
  font-family: 'SF Mono', monospace;
  font-size: 0.72rem;
}
.sample-line { padding: 0.1rem 0; }
.sample-more {
  font-size: 0.7rem;
  color: var(--text-color-secondary);
  font-style: italic;
}
.err-text {
  font-size: 0.72rem;
  color: #f87171;
  margin-top: 0.25rem;
}
</style>

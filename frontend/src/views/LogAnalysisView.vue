<template>
  <div class="logs-view">
    <!-- Filters bar — log scanning runs as part of `bluearch scan` now; trigger
         a scan from the Resources screen -->
    <div class="actions-bar">
      <label class="field">
        <span>Severity</span>
        <select v-model="severityFilter" @change="refresh">
          <option value="">All</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </label>

      <div class="last-scan" v-if="latestBatch">
        <span>Last scan:</span>
        <strong>{{ formatTimestamp(latestBatch.scan.started_at) }}</strong>
        <span class="muted">
          — {{ latestBatch.findings }} findings across {{ latestBatch.groups }} groups
          ({{ latestBatch.regions }} region{{ latestBatch.regions === 1 ? '' : 's' }})
        </span>
      </div>
      <div v-else class="last-scan muted">
        No log scans yet — run <router-link to="/resources">Scan Resources</router-link> to populate findings.
      </div>
    </div>

    <div v-if="store.error" class="error-banner">
      <i class="pi pi-exclamation-triangle"></i>
      <span>{{ store.error }}</span>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button
        class="tab"
        :class="{ active: activeTab === 'linked' }"
        @click="activeTab = 'linked'"
      >
        Resource-Linked
        <span class="tab-count">{{ store.linkedFindings.length }}</span>
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'unlinked' }"
        @click="activeTab = 'unlinked'"
      >
        Unlinked
        <span class="tab-count">{{ store.unlinkedFindings.length }}</span>
      </button>
    </div>

    <!-- Findings Tables -->
    <div class="section-card" v-if="activeTab === 'linked'">
      <table class="findings-table">
        <thead>
          <tr>
            <th>Severity</th>
            <th>Resource</th>
            <th>Type</th>
            <th>Error Pattern</th>
            <th class="num">Count</th>
            <th>Last Seen</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in store.linkedFindings" :key="f.id">
            <td><span class="sev-badge" :class="'sev-' + (f.severity || 'medium')">{{ (f.severity || '?').toUpperCase() }}</span></td>
            <td class="mono">
              <router-link v-if="f.resource_id" :to="`/resources/${f.resource_id}`" class="resource-link">
                {{ f.resource_id.slice(0, 8) }}
              </router-link>
            </td>
            <td>{{ f.resource_type || '—' }}</td>
            <td class="pattern">{{ f.error_pattern }}</td>
            <td class="num">{{ f.occurrence_count }}</td>
            <td class="mono">{{ formatTimestamp(f.last_seen) }}</td>
            <td>
              <button class="btn btn-sm" @click="openAnalysis(f)">
                <i :class="analyzingId === f.id ? 'pi pi-spin pi-spinner' : 'pi pi-bolt'"></i>
                Analyze
              </button>
            </td>
          </tr>
          <tr v-if="!store.linkedFindings.length">
            <td colspan="7" class="empty">No resource-linked findings for the latest scan.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="section-card" v-if="activeTab === 'unlinked'">
      <table class="findings-table">
        <thead>
          <tr>
            <th>Severity</th>
            <th>Log Group</th>
            <th>Error Pattern</th>
            <th class="num">Count</th>
            <th>Last Seen</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in store.unlinkedFindings" :key="f.id">
            <td><span class="sev-badge" :class="'sev-' + (f.severity || 'medium')">{{ (f.severity || '?').toUpperCase() }}</span></td>
            <td class="mono log-group">{{ f.log_group_name }}</td>
            <td class="pattern">{{ f.error_pattern }}</td>
            <td class="num">{{ f.occurrence_count }}</td>
            <td class="mono">{{ formatTimestamp(f.last_seen) }}</td>
            <td>
              <button class="btn btn-sm" @click="openAnalysis(f)">
                <i :class="analyzingId === f.id ? 'pi pi-spin pi-spinner' : 'pi pi-bolt'"></i>
                Analyze
              </button>
            </td>
          </tr>
          <tr v-if="!store.unlinkedFindings.length">
            <td colspan="6" class="empty">No unlinked findings for the latest scan.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Analysis Slide-out Panel -->
    <div v-if="panelFinding" class="slideout-backdrop" @click.self="closePanel">
      <aside class="slideout">
        <header class="slideout-header">
          <div>
            <div class="slideout-title">AI Root-Cause Analysis</div>
            <div class="slideout-sub">{{ panelFinding.log_group_name }}</div>
          </div>
          <button class="btn-icon" @click="closePanel">
            <i class="pi pi-times"></i>
          </button>
        </header>

        <div class="slideout-body">
          <div class="meta-row">
            <span class="sev-badge" :class="'sev-' + (panelFinding.severity || 'medium')">{{ (panelFinding.severity || '?').toUpperCase() }}</span>
            <span>{{ panelFinding.occurrence_count }} occurrences</span>
            <span class="muted">{{ formatTimestamp(panelFinding.last_seen) }}</span>
          </div>

          <div class="pattern-block">
            <div class="label">Error pattern</div>
            <pre>{{ panelFinding.error_pattern }}</pre>
          </div>

          <!-- Live tool-use ticker: what Bedrock is doing right now -->
          <div v-if="toolEvents.length" class="tool-ticker">
            <div class="label">Investigation</div>
            <ul>
              <li
                v-for="(ev, i) in toolEvents"
                :key="i"
                :class="{ 'tool-err': ev.status === 'error' }"
              >
                <i
                  :class="
                    ev.status === 'running'
                      ? 'pi pi-spin pi-spinner'
                      : ev.status === 'done'
                        ? 'pi pi-check'
                        : 'pi pi-times-circle'
                  "
                ></i>
                <span class="tool-name">{{ toolLabel(ev.name) }}</span>
                <span v-if="ev.summary" class="tool-summary">— {{ ev.summary }}</span>
              </li>
            </ul>
          </div>

          <!-- Streaming text / final analysis (rendered markdown) -->
          <div v-if="streaming || panelFinding.ai_analysis || streamedText" class="analysis">
            <div class="label">
              <span v-if="streaming">Analysis (live)</span>
              <span v-else>Analysis <span class="muted">— {{ formatTimestamp(panelFinding.ai_analyzed_at) }}</span></span>
            </div>
            <div
              class="analysis-body markdown"
              v-html="renderMarkdown(streaming ? streamedText : (panelFinding.ai_analysis || streamedText))"
            ></div>
            <div v-if="streaming" class="analyzing-inline">
              <i class="pi pi-spin pi-spinner"></i> {{ selectedModel }}…
            </div>
          </div>

          <!-- CTA (shows only when nothing is in-flight and no prior result) -->
          <div v-if="!streaming && !panelFinding.ai_analysis && !streamedText" class="analysis-cta">
            <div class="models">
              <label v-for="m in ['haiku', 'sonnet', 'opus']" :key="m">
                <input type="radio" :value="m" v-model="selectedModel" />
                {{ m }}
              </label>
            </div>
            <button class="btn btn-primary" @click="runAnalysis(panelFinding.id)">
              <i class="pi pi-bolt"></i> Run analysis
            </button>
          </div>

          <!-- Re-run button when a prior analysis is present and we're not streaming -->
          <div v-if="!streaming && panelFinding.ai_analysis" class="rerun-row">
            <button class="btn btn-sm" @click="runAnalysis(panelFinding.id)">
              <i class="pi pi-refresh"></i> Re-run
            </button>
            <div class="models">
              <label v-for="m in ['haiku', 'sonnet', 'opus']" :key="m">
                <input type="radio" :value="m" v-model="selectedModel" />
                {{ m }}
              </label>
            </div>
          </div>

          <div v-if="streamError" class="error-banner">
            <i class="pi pi-times-circle"></i>
            <span>{{ streamError }}</span>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import { api } from '@/api/client'
import { useLogsStore } from '@/stores/logs'
import { useJobsStore } from '@/stores/jobs'
import type { LogAnalysisStreamEvent, LogFinding, LogSeverity } from '@/types/logs'

const store = useLogsStore()
const jobsStore = useJobsStore()

const activeTab = ref<'linked' | 'unlinked'>('linked')
const severityFilter = ref<'' | LogSeverity>('')
const selectedModel = ref<'haiku' | 'sonnet' | 'opus'>('sonnet')
const analyzingId = ref<string | null>(null)
const panelFinding = ref<LogFinding | null>(null)

// Streaming state for the live investigation view
interface ToolEvent {
  name: string
  status: 'running' | 'done' | 'error'
  summary?: string
}
const streaming = ref(false)
const streamedText = ref('')
const toolEvents = ref<ToolEvent[]>([])
const streamError = ref<string | null>(null)

marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text: string | null): string {
  if (!text) return ''
  try {
    return marked.parse(text) as string
  } catch {
    return text
  }
}

const _TOOL_LABELS: Record<string, string> = {
  fetch_log_events: 'Fetching more log events',
  describe_lambda_function: 'Reading Lambda configuration',
  get_cloudwatch_metric: 'Pulling CloudWatch metric',
  get_resource_detail: 'Inspecting linked resource',
}

function toolLabel(name: string): string {
  return _TOOL_LABELS[name] || name
}

// A single `bluearch scan` emits one LogScan per region; roll them up so the
// header reflects the whole batch instead of whichever region finished last.
const latestBatch = computed(() => {
  const scans = store.scans
  if (!scans.length) return null
  const latest = scans[0]
  if (!latest.started_at) return { scan: latest, groups: latest.log_groups_scanned, findings: latest.findings_count, regions: 1 }
  const windowMs = 10 * 60 * 1000
  const latestTs = new Date(latest.started_at).getTime()
  const batch = scans.filter(
    (s) => s.account_id === latest.account_id
      && s.started_at
      && latestTs - new Date(s.started_at).getTime() <= windowMs,
  )
  return {
    scan: latest,
    groups: batch.reduce((n, s) => n + (s.log_groups_scanned || 0), 0),
    findings: batch.reduce((n, s) => n + (s.findings_count || 0), 0),
    regions: batch.length,
  }
})


async function refresh() {
  const filters: { severity?: LogSeverity } = {}
  if (severityFilter.value) filters.severity = severityFilter.value as LogSeverity
  await Promise.all([store.fetchScans(), store.fetchFindings(filters)])
}

// When the shared resource scan finishes, the logs collector has just written
// fresh LogScan + LogFinding rows — pull them in.
watch(
  () => jobsStore.currentScanJob?.status,
  (status) => {
    if (status === 'completed') refresh()
  },
)

function openAnalysis(finding: LogFinding) {
  panelFinding.value = finding
  streamedText.value = ''
  toolEvents.value = []
  streamError.value = null
}

function closePanel() {
  panelFinding.value = null
  streaming.value = false
  streamedText.value = ''
  toolEvents.value = []
  streamError.value = null
}

async function runAnalysis(id: string) {
  analyzingId.value = id
  streaming.value = true
  streamedText.value = ''
  toolEvents.value = []
  streamError.value = null

  try {
    for await (const ev of api.logsAnalyzeFindingStream(id, { model: selectedModel.value })) {
      handleStreamEvent(ev, id)
    }
  } catch (e) {
    streamError.value = e instanceof Error ? e.message : 'Analysis stream failed'
  } finally {
    streaming.value = false
    analyzingId.value = null
  }
}

function handleStreamEvent(ev: LogAnalysisStreamEvent, findingId: string) {
  if (ev.type === 'text_delta') {
    streamedText.value += ev.text
  } else if (ev.type === 'tool_use') {
    toolEvents.value.push({ name: ev.name, status: 'running' })
  } else if (ev.type === 'tool_result') {
    // Mark the most recent running entry for this tool as done
    for (let i = toolEvents.value.length - 1; i >= 0; i--) {
      if (toolEvents.value[i].name === ev.name && toolEvents.value[i].status === 'running') {
        toolEvents.value[i] = { name: ev.name, status: 'done', summary: ev.summary }
        break
      }
    }
  } else if (ev.type === 'done') {
    // Persist locally so the panel reflects the saved analysis
    if (panelFinding.value && panelFinding.value.id === findingId) {
      panelFinding.value = {
        ...panelFinding.value,
        ai_analysis: ev.analysis,
        ai_analyzed_at: new Date().toISOString(),
      }
    }
    // Also update the row in the store so the list reflects "analyzed"
    const idx = store.findings.findIndex((f) => f.id === findingId)
    if (idx !== -1) {
      store.findings[idx] = {
        ...store.findings[idx],
        ai_analysis: ev.analysis,
        ai_analyzed_at: new Date().toISOString(),
      }
    }
  } else if (ev.type === 'error') {
    streamError.value = ev.message
  }
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

watch(severityFilter, () => refresh())

onMounted(() => {
  refresh()
})
</script>

<style scoped>
.logs-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.actions-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
}

.field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}

.field select {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
}

.last-scan {
  margin-left: auto;
  font-size: 0.85rem;
  color: var(--text-color-secondary);
}

.last-scan strong {
  color: var(--text-color);
  margin: 0 0.25rem;
}

.last-scan .muted,
.muted {
  color: var(--text-color-secondary);
  opacity: 0.7;
}

.tabs {
  display: flex;
  gap: 0.5rem;
  border-bottom: 1px solid var(--surface-border);
}

.tab {
  background: transparent;
  border: none;
  padding: 0.75rem 1rem;
  color: var(--text-color-secondary);
  cursor: pointer;
  font-size: 0.9rem;
  border-bottom: 2px solid transparent;
}

.tab.active {
  color: var(--text-color);
  border-bottom-color: var(--primary-color);
}

.tab-count {
  display: inline-block;
  margin-left: 0.4rem;
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  padding: 0 0.4rem;
  border-radius: 10px;
  font-size: 0.75rem;
}

.section-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  overflow: hidden;
}

.findings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.findings-table th,
.findings-table td {
  text-align: left;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--surface-border);
}

.findings-table th {
  font-weight: 600;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
}

.findings-table td.num,
.findings-table th.num {
  text-align: right;
}

.findings-table td.mono {
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
}

.findings-table td.pattern {
  max-width: 500px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.findings-table td.log-group {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty {
  text-align: center;
  color: var(--text-color-secondary);
  padding: 2rem;
}

.sev-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.03em;
}

.sev-critical { background: rgba(220, 38, 38, 0.15); color: #f87171; }
.sev-high     { background: rgba(234, 88, 12, 0.15); color: #fb923c; }
.sev-medium   { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.sev-low      { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }

.btn {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
  padding: 0.4rem 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
}

.btn:hover {
  background: rgba(32, 108, 245, 0.08);
}

.btn-sm {
  padding: 0.25rem 0.6rem;
  font-size: 0.75rem;
}

.btn-primary {
  background: var(--primary-color);
  color: #fff;
  border-color: var(--primary-color);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-banner {
  padding: 0.6rem 0.85rem;
  background: rgba(220, 38, 38, 0.12);
  color: #fecaca;
  border: 1px solid rgba(220, 38, 38, 0.4);
  border-radius: 6px;
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.resource-link {
  color: var(--primary-color);
  text-decoration: none;
}

.resource-link:hover {
  text-decoration: underline;
}

/* Slide-out panel */
.slideout-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  justify-content: flex-end;
  z-index: 1000;
}

.slideout {
  width: 540px;
  max-width: 100vw;
  background: var(--surface-card);
  border-left: 1px solid var(--surface-border);
  display: flex;
  flex-direction: column;
}

.slideout-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.slideout-title {
  font-weight: 600;
  color: var(--text-color);
}

.slideout-sub {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
  margin-top: 0.25rem;
  word-break: break-all;
}

.slideout-body {
  flex: 1;
  overflow: auto;
  padding: 1rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.85rem;
}

.label {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
  margin-bottom: 0.25rem;
}

.pattern-block pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface-ground);
  padding: 0.75rem;
  border-radius: 6px;
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
  color: var(--text-color);
  margin: 0;
}

.analysis-body {
  background: var(--surface-ground);
  padding: 0.9rem 1rem;
  border-radius: 6px;
  color: var(--text-color);
  font-size: 0.85rem;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

/* Markdown element styling inside the analysis panel */
.analysis-body.markdown :deep(h1),
.analysis-body.markdown :deep(h2),
.analysis-body.markdown :deep(h3),
.analysis-body.markdown :deep(h4) {
  margin: 1rem 0 0.4rem;
  font-weight: 600;
  line-height: 1.3;
}
.analysis-body.markdown :deep(h1) { font-size: 1.1rem; }
.analysis-body.markdown :deep(h2) { font-size: 1.0rem; }
.analysis-body.markdown :deep(h3) { font-size: 0.95rem; color: var(--primary-color); }
.analysis-body.markdown :deep(h4) { font-size: 0.88rem; color: var(--text-color-secondary); }
.analysis-body.markdown :deep(p) { margin: 0.5rem 0; }
.analysis-body.markdown :deep(ul),
.analysis-body.markdown :deep(ol) { padding-left: 1.25rem; margin: 0.4rem 0; }
.analysis-body.markdown :deep(li) { margin: 0.2rem 0; }
.analysis-body.markdown :deep(code) {
  background: rgba(32, 108, 245, 0.12);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}
.analysis-body.markdown :deep(pre) {
  background: rgba(0, 0, 0, 0.3);
  padding: 0.65rem 0.8rem;
  border-radius: 5px;
  overflow-x: auto;
  margin: 0.5rem 0;
}
.analysis-body.markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}
.analysis-body.markdown :deep(table) {
  border-collapse: collapse;
  margin: 0.5rem 0;
  font-size: 0.8rem;
}
.analysis-body.markdown :deep(th),
.analysis-body.markdown :deep(td) {
  border: 1px solid var(--surface-border);
  padding: 0.3rem 0.55rem;
  text-align: left;
}
.analysis-body.markdown :deep(th) { background: rgba(32, 108, 245, 0.08); font-weight: 600; }
.analysis-body.markdown :deep(blockquote) {
  margin: 0.5rem 0;
  padding: 0.4rem 0.75rem;
  border-left: 3px solid var(--primary-color);
  color: var(--text-color-secondary);
  background: rgba(32, 108, 245, 0.05);
}
.analysis-body.markdown :deep(strong) { color: var(--text-color); }
.analysis-body.markdown :deep(hr) {
  border: none;
  border-top: 1px solid var(--surface-border);
  margin: 0.9rem 0;
}

.analyzing-inline {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

/* Live tool-use ticker */
.tool-ticker ul {
  list-style: none;
  padding: 0;
  margin: 0;
  background: var(--surface-ground);
  border-radius: 6px;
  padding: 0.4rem 0.65rem;
}
.tool-ticker li {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  padding: 0.2rem 0;
  font-size: 0.82rem;
  color: var(--text-color-secondary);
}
.tool-ticker li i {
  width: 14px;
  text-align: center;
  font-size: 0.75rem;
  color: var(--primary-color);
  flex-shrink: 0;
}
.tool-ticker li.tool-err i { color: #f87171; }
.tool-ticker .tool-name { color: var(--text-color); font-weight: 500; }
.tool-ticker .tool-summary {
  color: var(--text-color-secondary);
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  overflow-wrap: anywhere;
}

.rerun-row {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-top: 0.25rem;
}

.analyzing {
  color: var(--text-color-secondary);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.analysis-cta {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  align-items: flex-start;
}

.models {
  display: flex;
  gap: 0.75rem;
  font-size: 0.85rem;
}

.btn-icon {
  background: transparent;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  font-size: 1rem;
  padding: 0.25rem 0.5rem;
}
.btn-icon:hover { color: var(--text-color); }
</style>

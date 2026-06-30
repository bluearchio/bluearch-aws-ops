<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import type { ScanHistoryItem } from '@/types/api'

const scanHistory = ref<ScanHistoryItem[]>([])
const loading = ref(true)

function timeAgo(d?: string): string {
  if (!d) return '-'
  const diff = Date.now() - new Date(d).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

async function loadData() {
  loading.value = true
  try {
    scanHistory.value = await api.scanHistory()
  } catch { /* silent */ }
  finally { loading.value = false }
}

onMounted(loadData)
</script>

<template>
  <div class="audit-view">
    <div class="audit-header">
      <h2 class="audit-title">Scan History</h2>
      <button class="btn btn-secondary" @click="loadData" :disabled="loading">
        <i :class="loading ? 'pi pi-spin pi-spinner' : 'pi pi-refresh'"></i>
        Refresh
      </button>
    </div>

    <div v-if="loading" class="loading-state"><i class="pi pi-spin pi-spinner"></i> Loading...</div>

    <div v-else class="table-card">
      <div v-if="!scanHistory.length" class="empty-state">
        <i class="pi pi-clock"></i>
        <div>No scan history yet. Run a scan to see results here.</div>
      </div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th>Started</th>
            <th>Mode</th>
            <th>Collected By</th>
            <th>Status</th>
            <th>Resources</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="scan in scanHistory" :key="scan.id">
            <td class="mono">{{ timeAgo(scan.started_at) }}</td>
            <td>
              <span class="mode-pill">{{ scan.scan_mode }}</span>
            </td>
            <td class="mono">{{ scan.collected_by }}</td>
            <td>
              <span class="status-pill" :class="{
                'pill-ok': scan.status === 'completed',
                'pill-warn': scan.status === 'running',
                'pill-err': scan.status === 'failed'
              }">{{ scan.status }}</span>
            </td>
            <td class="mono">{{ scan.resources_found }}</td>
            <td class="mono">
              <template v-if="scan.started_at && scan.completed_at">
                {{ Math.round((new Date(scan.completed_at).getTime() - new Date(scan.started_at).getTime()) / 1000) }}s
              </template>
              <template v-else>-</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.audit-view { display: flex; flex-direction: column; gap: 1rem; }
.audit-header { display: flex; justify-content: space-between; align-items: center; }
.audit-title { font-size: 1.1rem; font-weight: 600; background: var(--gradient-brand-horizontal); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }

.table-card { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 10px; overflow: hidden; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { text-align: left; padding: 0.65rem 1rem; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: var(--text-color-secondary); background: var(--surface-ground); border-bottom: 1px solid var(--surface-border); }
.data-table td { padding: 0.6rem 1rem; font-size: 0.82rem; border-bottom: 1px solid var(--surface-border); }
.data-table tbody tr:hover { background: rgba(32, 108, 245, 0.05); }

.status-pill { display: inline-block; padding: 0.15rem 0.45rem; border-radius: 10px; font-size: 0.72rem; font-weight: 500; }
.pill-ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.pill-warn { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.pill-err { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.mode-pill { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.72rem; background: rgba(32, 108, 245, 0.12); color: #5a9aff; font-weight: 500; }
.mono { font-family: var(--font-mono, monospace); }

.loading-state { color: var(--text-color-secondary); padding: 2rem; text-align: center; display: flex; align-items: center; justify-content: center; gap: 0.5rem; }
.empty-state { display: flex; flex-direction: column; align-items: center; padding: 3rem; color: var(--text-color-secondary); font-size: 0.85rem; gap: 0.5rem; }
.empty-state i { font-size: 1.3rem; }

.btn { padding: 0.45rem 0.85rem; border: none; border-radius: 6px; font-size: 0.82rem; cursor: pointer; font-weight: 500; display: inline-flex; align-items: center; gap: 0.35rem; font-family: var(--font-body); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: var(--surface-ground); color: var(--text-color); border: 1px solid var(--surface-border); }

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.pi-spin { animation: spin 1s linear infinite; }
</style>

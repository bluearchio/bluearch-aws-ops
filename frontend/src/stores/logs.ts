import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { LogFinding, LogScan, LogSeverity } from '@/types/logs'

export const useLogsStore = defineStore('logs', () => {
  const findings = ref<LogFinding[]>([])
  const findingsTotal = ref(0)
  const findingsPage = ref(1)
  const findingsPageSize = ref(50)
  const scans = ref<LogScan[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const linkedFindings = computed(() => findings.value.filter((f) => f.link_status === 'linked'))
  const unlinkedFindings = computed(() => findings.value.filter((f) => f.link_status !== 'linked'))

  async function fetchFindings(filters: {
    scan_id?: string
    severity?: LogSeverity
    link_status?: 'linked' | 'unlinked'
    resource_id?: string
  } = {}) {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, string> = {
        page: String(findingsPage.value),
        page_size: String(findingsPageSize.value),
      }
      if (filters.scan_id) params.scan_id = filters.scan_id
      if (filters.severity) params.severity = filters.severity
      if (filters.link_status) params.link_status = filters.link_status
      if (filters.resource_id) params.resource_id = filters.resource_id

      const page = await api.logsListFindings(params)
      findings.value = page.items
      findingsTotal.value = page.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load findings'
    } finally {
      loading.value = false
    }
  }

  async function fetchScans() {
    try {
      scans.value = await api.logsListScans()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load scans'
    }
  }

  async function analyzeFinding(id: string, model = 'sonnet') {
    error.value = null
    try {
      const resp = await api.logsAnalyzeFinding(id, { model })
      // Update the in-memory finding so the UI reflects the saved analysis
      const idx = findings.value.findIndex((f) => f.id === id)
      if (idx !== -1) {
        findings.value[idx] = {
          ...findings.value[idx],
          ai_analysis: resp.analysis,
          ai_analyzed_at: resp.analyzed_at,
        }
      }
      return resp
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Analysis failed'
      throw e
    }
  }

  return {
    findings,
    findingsTotal,
    findingsPage,
    findingsPageSize,
    scans,
    loading,
    error,
    linkedFindings,
    unlinkedFindings,
    fetchFindings,
    fetchScans,
    analyzeFinding,
  }
})

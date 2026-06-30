import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { createCachedLoader, type CachedLoadOptions } from '@/stores/cache'
import type { ScanJob, JobResponse } from '@/types/api'

const ACTIVE_STATUSES = new Set(['pending', 'running', 'cancelling'])
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<ScanJob[]>([])
  const activeJob = ref<ScanJob | null>(null)
  const currentScanJobId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Generic jobs list (multi-account, delete, etc.) tracked separately from scans
  const multiAccountJobs = ref<JobResponse[]>([])
  const currentMultiAccountJobId = ref<string | null>(null)
  let multiAccountPollInterval: ReturnType<typeof setInterval> | null = null
  let multiAccountCleanupTimeout: ReturnType<typeof setTimeout> | null = null

  let pollInterval: ReturnType<typeof setInterval> | null = null
  let cleanupTimeout: ReturnType<typeof setTimeout> | null = null

  /** Computed accessor for the current scan job (used by ScanProgressPanel). */
  const currentScanJob = computed(() => {
    if (!currentScanJobId.value) return null
    return jobs.value.find((j) => j.id === currentScanJobId.value) || activeJob.value
  })

  /** Computed accessor for the current multi-account job (used by MultiAccountView). */
  const currentMultiAccountJob = computed(() => {
    if (!currentMultiAccountJobId.value) return null
    return multiAccountJobs.value.find((j) => j.id === currentMultiAccountJobId.value) || null
  })

  function assignJobs(list: ScanJob[]) {
    jobs.value = list
    // Sync activeJob if it's in the list
    if (activeJob.value) {
      const match = jobs.value.find(j => j.id === activeJob.value!.id)
      if (match) activeJob.value = match
    }
    // Auto-detect running scans (e.g. on page reload)
    if (!currentScanJobId.value) {
      const runningScans = jobs.value.filter(
        (j) => ACTIVE_STATUSES.has(j.status),
      )
      if (runningScans.length > 0) {
        currentScanJobId.value = runningScans[0].id
        activeJob.value = runningScans[0]
        startPolling(runningScans[0].id)
      }
    }
  }

  const jobsLoader = createCachedLoader<ScanJob[]>({
    fetcher: api.listScanJobs,
    assign: assignJobs,
    hasData: () => jobs.value.length > 0,
    setLoading: (value) => { loading.value = value },
    setError: (message) => { error.value = message },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load jobs',
    staleMs: 10_000,
  })

  function fetchJobs(options?: CachedLoadOptions) {
    return jobsLoader.load(options).catch(() => null)
  }

  async function startScan(services?: string[], regions?: string[]) {
    error.value = null
    try {
      const result = await api.startScan({ services, regions })
      activeJob.value = {
        id: result.job_id,
        status: 'pending',
        message: result.message,
        created_at: new Date().toISOString(),
      }
      currentScanJobId.value = result.job_id
      startPolling(result.job_id)
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to start scan'
      throw e
    }
  }

  async function pollJob(jobId: string) {
    try {
      const job = await api.getScanJob(jobId)
      activeJob.value = job
      const idx = jobs.value.findIndex(j => j.id === jobId)
      if (idx !== -1) {
        jobs.value[idx] = job
      } else {
        jobs.value.unshift(job)
      }
      return job
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to poll job'
      throw e
    }
  }

  async function cancelScan(jobId = currentScanJobId.value) {
    if (!jobId) return null
    error.value = null
    try {
      const job = await api.cancelScan(jobId)
      activeJob.value = job
      const idx = jobs.value.findIndex(j => j.id === jobId)
      if (idx !== -1) {
        jobs.value[idx] = job
      } else {
        jobs.value.unshift(job)
      }
      return job
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to cancel scan'
      throw e
    }
  }

  function startPolling(jobId: string) {
    stopPolling()
    // Poll immediately to get the first status update without waiting
    pollJob(jobId).catch(() => {})
    pollInterval = setInterval(async () => {
      try {
        const job = await pollJob(jobId)
        if (TERMINAL_STATUSES.has(job.status)) {
          stopPolling()
          scheduleCleanup()
        }
      } catch {
        stopPolling()
      }
    }, 2000)
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  function clearCurrentJob() {
    currentScanJobId.value = null
    activeJob.value = null
  }

  function scheduleCleanup() {
    if (cleanupTimeout) clearTimeout(cleanupTimeout)
    cleanupTimeout = setTimeout(() => {
      clearCurrentJob()
    }, 60000)
  }

  // Auto-cleanup when currentScanJob reaches terminal state
  watch(currentScanJob, (job) => {
    if (job && TERMINAL_STATUSES.has(job.status)) {
      stopPolling()
      scheduleCleanup()
    }
  })

  // ---------------------------------------------------------------------------
  // Multi-Account Jobs (deploy/update/remove/clean)
  // ---------------------------------------------------------------------------

  async function pollMultiAccountJob(jobId: string): Promise<JobResponse | null> {
    try {
      const job = await api.getJob(jobId)
      const idx = multiAccountJobs.value.findIndex((j) => j.id === jobId)
      if (idx >= 0) {
        multiAccountJobs.value[idx] = job
      } else {
        multiAccountJobs.value.unshift(job)
      }
      return job
    } catch {
      return null
    }
  }

  function startMultiAccountPolling(jobId: string) {
    stopMultiAccountPolling()
    pollMultiAccountJob(jobId).catch(() => {})
    multiAccountPollInterval = setInterval(async () => {
      const job = await pollMultiAccountJob(jobId)
      if (!job || TERMINAL_STATUSES.has(job.status)) {
        stopMultiAccountPolling()
        scheduleMultiAccountCleanup()
      }
    }, 2000)
  }

  function stopMultiAccountPolling() {
    if (multiAccountPollInterval) {
      clearInterval(multiAccountPollInterval)
      multiAccountPollInterval = null
    }
  }

  function scheduleMultiAccountCleanup() {
    if (multiAccountCleanupTimeout) clearTimeout(multiAccountCleanupTimeout)
    multiAccountCleanupTimeout = setTimeout(() => {
      currentMultiAccountJobId.value = null
    }, 60000)
  }

  async function submitMultiAccountJob(
    action: 'deploy' | 'update' | 'remove' | 'clean',
    body?: Record<string, unknown>,
  ) {
    error.value = null
    try {
      let result: { job_id: string; job_type: string; status: string; message: string }
      switch (action) {
        case 'deploy':
          result = await api.deployMultiAccount(body as never)
          break
        case 'update':
          result = await api.updateMultiAccount()
          break
        case 'remove':
          result = await api.removeMultiAccount()
          break
        case 'clean':
          result = await api.deployMultiAccount({ force_recreate: true })
          break
      }
      currentMultiAccountJobId.value = result.job_id
      // Seed an initial placeholder job immediately so the view can render
      // "pending" state without waiting for the first poll round-trip.
      multiAccountJobs.value.unshift({
        id: result.job_id,
        job_type: result.job_type,
        status: 'pending',
        progress: 0,
        progress_message: result.message,
        created_at: new Date().toISOString(),
      })
      startMultiAccountPolling(result.job_id)
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to submit multi-account job'
      throw e
    }
  }

  function clearCurrentMultiAccount() {
    currentMultiAccountJobId.value = null
    stopMultiAccountPolling()
  }

  /** Auto-detect a running multi-account job on page reload via /api/v1/jobs. */
  const multiAccountJobsLoader = createCachedLoader<JobResponse[]>({
    fetcher: api.listJobs,
    assign: (list) => {
      multiAccountJobs.value = list.filter((j) => j.job_type?.startsWith('multi_account_'))
      if (!currentMultiAccountJobId.value) {
        const running = multiAccountJobs.value.find(
          (j) => ACTIVE_STATUSES.has(j.status),
        )
        if (running) {
          currentMultiAccountJobId.value = running.id
          startMultiAccountPolling(running.id)
        }
      }
    },
    hasData: () => multiAccountJobs.value.length > 0,
    staleMs: 10_000,
  })

  function fetchMultiAccountJobs(options?: CachedLoadOptions) {
    return multiAccountJobsLoader.load(options).catch(() => null)
  }

  // Auto-cleanup when currentMultiAccountJob reaches terminal state
  watch(currentMultiAccountJob, (job) => {
    if (job && TERMINAL_STATUSES.has(job.status)) {
      stopMultiAccountPolling()
      scheduleMultiAccountCleanup()
    }
  })

  return {
    jobs,
    activeJob,
    currentScanJob,
    currentScanJobId,
    loading,
    error,
    fetchJobs,
    startScan,
    cancelScan,
    pollJob,
    startPolling,
    stopPolling,
    clearCurrentJob,
    // Multi-account
    multiAccountJobs,
    currentMultiAccountJob,
    currentMultiAccountJobId,
    submitMultiAccountJob,
    clearCurrentMultiAccount,
    fetchMultiAccountJobs,
    pollMultiAccountJob,
  }
})

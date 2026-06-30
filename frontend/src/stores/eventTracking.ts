import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'

interface EventTrackingInstance {
  account_id: string
  region: string
  status: string
  queue_url: string
  queue_arn: string
  last_polled_at?: string
  last_event_at?: string
  messages_processed: number
  events_today: number
  error_message?: string
}

interface EventTrackingStatus {
  stackset_exists: boolean
  stackset_status: string
  instances: EventTrackingInstance[]
  service_running: boolean
  service_paused: boolean
  total_queues: number
  active_queues: number
}

export const useEventTrackingStore = defineStore('eventTracking', () => {
  const status = ref<EventTrackingStatus | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchStatus() {
    loading.value = true
    error.value = null
    try {
      status.value = await api.eventTrackingStatus()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load event tracking status'
    } finally {
      loading.value = false
    }
  }

  async function controlService(action: 'pause' | 'resume' | 'start' | 'stop' | 'sync') {
    try {
      await api.eventTrackingControl(action)
      await fetchStatus()
    } catch (e) {
      error.value = e instanceof Error ? e.message : `Failed to ${action} service`
      throw e
    }
  }

  return { status, loading, error, fetchStatus, controlService }
})

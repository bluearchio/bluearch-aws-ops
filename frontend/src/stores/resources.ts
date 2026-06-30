import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { createCachedLoader, type CachedLoadOptions } from '@/stores/cache'
import type { ResourceResponse, ResourceSummary } from '@/types/api'

export const useResourcesStore = defineStore('resources', () => {
  const items = ref<ResourceResponse[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const detail = ref<ResourceResponse | null>(null)
  const summary = ref<ResourceSummary | null>(null)

  const filters = ref({
    search: '',
    service_name: '',
    region: '',
    account_id: '',
    page: 1,
    page_size: 50,
  })

  async function fetchItems() {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, string> = {
        page: String(filters.value.page),
        page_size: String(filters.value.page_size),
      }
      if (filters.value.search) params.search = filters.value.search
      if (filters.value.service_name) params.service_name = filters.value.service_name
      if (filters.value.region) params.region = filters.value.region
      if (filters.value.account_id) params.account_id = filters.value.account_id

      const data = await api.listResources(params)
      items.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load resources'
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(id: string) {
    loading.value = true
    error.value = null
    try {
      detail.value = await api.getResource(id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load resource'
    } finally {
      loading.value = false
    }
  }

  const summaryLoader = createCachedLoader<ResourceSummary>({
    fetcher: api.resourceSummary,
    assign: (value) => { summary.value = value },
    hasData: () => summary.value !== null,
    setError: (message) => {
      if (message) error.value = message
    },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load resource summary',
  })

  async function fetchSummary(options?: CachedLoadOptions) {
    await summaryLoader.load(options).catch(() => null)
  }

  return {
    items,
    total,
    loading,
    error,
    detail,
    summary,
    filters,
    fetchItems,
    fetchDetail,
    fetchSummary,
  }
})

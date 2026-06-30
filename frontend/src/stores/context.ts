import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { createCachedLoader, type CachedLoadOptions } from '@/stores/cache'
import type { AccountContextListResponse, AccountContextResponse } from '@/types/api'

export const useContextStore = defineStore('context', () => {
  const current = ref<AccountContextResponse | null>(null)
  const all = ref<AccountContextResponse[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  let loadingCount = 0

  function setLoading(value: boolean) {
    loadingCount += value ? 1 : -1
    loading.value = loadingCount > 0
  }

  const currentLabel = computed(() => {
    if (!current.value?.account_id) return 'No Account'
    return current.value.account_alias
      ? `${current.value.account_alias} (${current.value.account_id})`
      : current.value.account_id
  })

  const currentLoader = createCachedLoader<AccountContextResponse>({
    fetcher: api.currentContext,
    assign: (value) => { current.value = value },
    hasData: () => current.value !== null,
    setLoading,
    setError: (message) => { error.value = message },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load current context',
  })

  const allLoader = createCachedLoader<AccountContextListResponse>({
    fetcher: api.allContexts,
    assign: (res) => {
      all.value = Array.isArray(res) ? res : (res.contexts ?? [])
      const cur = all.value.find((c: AccountContextResponse) => c.is_current)
      if (cur) current.value = cur
    },
    hasData: () => all.value.length > 0,
    setLoading,
    setError: (message) => { error.value = message },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load contexts',
  })

  function loadCurrent(options?: CachedLoadOptions) {
    return currentLoader.load(options).catch(() => null)
  }

  function loadAll(options?: CachedLoadOptions) {
    return allLoader.load(options).catch(() => null)
  }

  function refresh() {
    return Promise.all([
      currentLoader.refresh().catch(() => null),
      allLoader.refresh().catch(() => null),
    ])
  }

  async function switchTo(accountId: string) {
    loading.value = true
    error.value = null
    try {
      await api.switchContext(accountId)
      // Reload page to refresh all data for new context
      window.location.reload()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to switch context'
      loading.value = false
      throw e
    }
  }

  return {
    current,
    all,
    loading,
    error,
    currentLabel,
    loadCurrent,
    loadAll,
    fetchCurrent: loadCurrent,
    fetchAll: loadAll,
    refresh,
    switchTo,
  }
})

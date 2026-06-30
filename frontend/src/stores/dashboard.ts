import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { createCachedLoader, type CachedLoadOptions } from '@/stores/cache'
import type { RecommendationSummary, ResourceSummary, SystemStats, HealthResponse } from '@/types/api'

interface DashboardData {
  health: HealthResponse
  resourceSummary: ResourceSummary
  stats: SystemStats
  summary: RecommendationSummary
}

export const useDashboardStore = defineStore('dashboard', () => {
  const stats = ref<SystemStats | null>(null)
  const summary = ref<RecommendationSummary | null>(null)
  const health = ref<HealthResponse | null>(null)
  const resourceSummary = ref<ResourceSummary | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const loader = createCachedLoader<DashboardData>({
    fetcher: async () => {
      const [s, sm, h, rs] = await Promise.all([
        api.stats(),
        api.recommendationSummary(),
        api.health(),
        api.resourceSummary(),
      ])
      return { stats: s, summary: sm, health: h, resourceSummary: rs }
    },
    assign: (value) => {
      stats.value = value.stats
      summary.value = value.summary
      health.value = value.health
      resourceSummary.value = value.resourceSummary
    },
    hasData: () => stats.value !== null || summary.value !== null || health.value !== null,
    setLoading: (value) => { loading.value = value },
    setError: (message) => { error.value = message },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load dashboard',
  })

  function fetchAll(options?: CachedLoadOptions) {
    return loader.load(options).catch(() => null)
  }

  function refresh() {
    return loader.refresh().catch(() => null)
  }

  return { stats, summary, health, resourceSummary, loading, error, fetchAll, refresh }
})

import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'

export interface GraphNode {
  id: string
  name: string
  service: string
  service_name: string
  resource_type: string
  resource_id: string
  region: string
  account_id: string
  category: number
  symbol_size: number
  value: number
  tags?: Record<string, string>
  recommendation_count: number
}

export interface GraphEdge {
  source: string
  target: string
  relationship_type: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  categories: { name: string; color: string }[]
  stats: Record<string, unknown>
  truncated: boolean
}

export interface GraphFilters {
  services: string[]
  regions: string[]
  relationship_types: string[]
  account_ids: string[]
}

export const useGraphStore = defineStore('graph', () => {
  const data = ref<GraphData | null>(null)
  const filters = ref<GraphFilters | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const selectedService = ref<string | null>(null)
  const selectedRegion = ref<string | null>(null)
  const selectedAccountId = ref<string | null>(null)
  const selectedNodeArn = ref<string | null>(null)

  const nodeCount = computed(() => data.value?.nodes.length ?? 0)
  const edgeCount = computed(() => data.value?.edges.length ?? 0)
  const truncated = computed(() => data.value?.truncated ?? false)

  const selectedNode = computed(() => {
    if (!selectedNodeArn.value || !data.value) return null
    return data.value.nodes.find(n => n.id === selectedNodeArn.value) ?? null
  })

  async function fetchData(params?: { service?: string; region?: string; account_id?: string }) {
    loading.value = true
    error.value = null
    try {
      const queryParams: Record<string, string> = {}
      const svc = params?.service ?? selectedService.value
      const rgn = params?.region ?? selectedRegion.value
      const acct = params?.account_id ?? selectedAccountId.value
      if (svc) queryParams.service = svc
      if (rgn) queryParams.region = rgn
      if (acct) queryParams.account_id = acct
      data.value = await api.graphData(queryParams) as GraphData
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load graph data'
    } finally {
      loading.value = false
    }
  }

  async function fetchFilters() {
    try {
      filters.value = await api.graphFilters() as GraphFilters
    } catch {
      // silent
    }
  }

  function selectNode(arn: string | null) {
    selectedNodeArn.value = arn
  }

  function clearFilters() {
    selectedService.value = null
    selectedRegion.value = null
    selectedAccountId.value = null
  }

  return {
    data,
    filters,
    loading,
    error,
    selectedService,
    selectedRegion,
    selectedAccountId,
    selectedNodeArn,
    nodeCount,
    edgeCount,
    truncated,
    selectedNode,
    fetchData,
    fetchFilters,
    selectNode,
    clearFilters,
  }
})

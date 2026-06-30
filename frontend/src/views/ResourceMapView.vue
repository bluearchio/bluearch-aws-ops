<template>
  <div class="resource-map-view">
    <!-- Truncation banner -->
    <div v-if="graph.truncated" class="truncation-banner">
      <i class="pi pi-info-circle"></i>
      Graph truncated to {{ graph.nodeCount }} nodes. Use filters to narrow results.
    </div>

    <!-- Filters bar -->
    <div class="filters-bar">
      <div class="filter-group">
        <select v-model="filterService" class="filter-input" @change="applyFilters">
          <option value="">All Services</option>
          <option v-for="s in graph.filters?.services" :key="s" :value="s">{{ s }}</option>
        </select>
        <select v-model="filterRegion" class="filter-input" @change="applyFilters">
          <option value="">All Regions</option>
          <option v-for="r in graph.filters?.regions" :key="r" :value="r">{{ r }}</option>
        </select>
        <select v-model="filterAccount" class="filter-input" @change="applyFilters">
          <option value="">All Accounts</option>
          <option v-for="a in graph.filters?.account_ids" :key="a" :value="a">{{ a }}</option>
        </select>
        <button
          v-if="hasActiveFilters"
          class="btn btn-sm btn-outline"
          @click="clearFilters"
        >
          <i class="pi pi-filter-slash"></i> Clear
        </button>
      </div>
    </div>

    <!-- Main content -->
    <div class="map-content">
      <!-- Graph area -->
      <div class="graph-container">
        <div v-if="graph.loading" class="graph-loading">
          <i class="pi pi-spin pi-spinner"></i> Loading graph...
        </div>
        <div v-else-if="graph.error" class="graph-error">
          {{ graph.error }}
        </div>
        <div v-else-if="!graph.data || graph.nodeCount === 0" class="graph-empty">
          <i class="pi pi-sitemap graph-empty-icon"></i>
          <p>No resources found.</p>
          <p class="graph-empty-hint">Run a scan to discover resources and relationships.</p>
        </div>
        <VChart
          v-else
          ref="chartRef"
          class="graph-chart"
          :option="chartOption"
          autoresize
          @click="onNodeClick"
        />
      </div>

      <!-- Detail panel -->
      <GraphDetailPanel
        v-if="graph.selectedNode"
        :node="graph.selectedNode"
        :edges="graph.data?.edges ?? []"
        @close="graph.selectNode(null)"
        @focus="onFocusNode"
      />
    </div>

    <!-- Footer -->
    <div class="map-footer">
      <div class="legend">
        <span
          v-for="cat in visibleCategories"
          :key="cat.name"
          class="legend-item"
        >
          <span class="legend-dot" :style="{ background: cat.color }"></span>
          {{ cat.name }}
        </span>
      </div>
      <div class="map-stats">
        {{ graph.nodeCount }} nodes, {{ graph.edgeCount }} edges
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useGraphStore } from '@/stores/graph'
import { useJobsStore } from '@/stores/jobs'
import GraphDetailPanel from '@/components/GraphDetailPanel.vue'

use([CanvasRenderer, GraphChart, TooltipComponent, LegendComponent])

const graph = useGraphStore()
const jobsStore = useJobsStore()

// Refresh the map when a scan finishes (scan button lives on Resources screen)
watch(
  () => jobsStore.currentScanJob?.status,
  (status) => {
    if (status === 'completed') {
      graph.fetchFilters()
      graph.fetchData()
    }
  },
)
// @ts-ignore used in template ref
const chartRef = ref<InstanceType<typeof VChart> | null>(null)
const filterService = ref('')
const filterRegion = ref('')
const filterAccount = ref('')

const SERVICE_COLORS: Record<string, string> = {
  ec2: '#f97316', s3: '#22c55e', lambda: '#a855f7', rds: '#3b82f6',
  dynamodb: '#f59e0b', ecs: '#14b8a6', elb: '#06b6d4', elbv2: '#06b6d4',
  sns: '#e11d48', sqs: '#8b5cf6', cloudwatch: '#ef4444', logs: '#ef4444',
  eks: '#0ea5e9', elasticache: '#dc2626', vpc: '#6b7280', subnet: '#9ca3af',
  sg: '#4b5563', iam: '#eab308',
}

const hasActiveFilters = computed(() => {
  return !!(filterService.value || filterRegion.value || filterAccount.value)
})

const visibleCategories = computed(() => {
  if (!graph.data) return []
  const usedServices = new Set(graph.data.nodes.map(n => n.service_name))
  return graph.data.categories.filter(c => usedServices.has(c.name))
})

const chartOption = computed(() => {
  if (!graph.data) return {}

  const nodes = graph.data.nodes.map(n => {
    const baseColor = SERVICE_COLORS[n.service_name] || '#6b7280'
    const isSelected = n.id === graph.selectedNodeArn
    let borderColor = isSelected ? '#fff' : 'transparent'
    let borderWidth = isSelected ? 3 : 0

    if (n.recommendation_count > 0 && !isSelected) {
      borderColor = '#f59e0b'
      borderWidth = 2
    }

    return {
      id: n.id,
      name: n.name || n.resource_id,
      symbolSize: n.symbol_size,
      category: n.category,
      itemStyle: {
        color: baseColor,
        borderColor,
        borderWidth,
      },
      label: {
        show: graph.nodeCount <= 80,
        fontSize: 10,
        color: '#ccc',
      },
      value: n.service_name,
    }
  })

  const edges = graph.data.edges.map(e => ({
    source: e.source,
    target: e.target,
    label: {
      show: false,
      formatter: e.relationship_type,
      fontSize: 9,
      color: '#999',
    },
    emphasis: {
      label: { show: true },
    },
    lineStyle: {
      color: '#555',
      width: 1,
      curveness: 0.1,
    },
  }))

  const categories = graph.data.categories.map(c => ({
    name: c.name,
    itemStyle: { color: c.color },
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: Record<string, unknown>) => {
        if (params.dataType === 'edge') {
          const data = params.data as { label?: { formatter?: string } }
          return data?.label?.formatter || ''
        }
        const nodeId = (params.data as { id?: string })?.id
        const node = graph.data?.nodes.find(n => n.id === nodeId)
        if (!node) {
          const data = params.data as { name?: string; value?: string }
          return `<b>${data?.name || ''}</b><br/>${data?.value || ''}`
        }
        let html = `<b>${node.name || node.resource_id}</b><br/>${node.service_name} / ${node.resource_type}`
        html += `<br/>Region: ${node.region}`
        if (node.recommendation_count > 0) {
          html += `<br/><span style="color:#f59e0b">Recommendations: ${node.recommendation_count}</span>`
        }
        html += `<br/><span style="font-size:10px;color:#999">${node.id}</span>`
        return html
      },
      backgroundColor: '#1a1a2e',
      borderColor: '#333',
      textStyle: { color: '#eee', fontSize: 12 },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        data: nodes,
        links: edges,
        categories: categories,
        roam: true,
        draggable: true,
        force: {
          repulsion: 200,
          gravity: 0.05,
          edgeLength: [80, 200],
          friction: 0.6,
        },
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 3 },
        },
        label: {
          position: 'right',
          distance: 5,
        },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [0, 8],
      },
    ],
    animationDuration: 1500,
    animationEasingUpdate: 'quinticInOut' as const,
  }
})

function onNodeClick(params: Record<string, unknown>) {
  if (params.dataType === 'node') {
    const data = params.data as { id?: string }
    if (data?.id) {
      graph.selectNode(data.id)
    }
  }
}

function onFocusNode(arn: string) {
  graph.selectNode(arn)
}

function applyFilters() {
  graph.selectedService = filterService.value || null
  graph.selectedRegion = filterRegion.value || null
  graph.selectedAccountId = filterAccount.value || null
  graph.fetchData()
}

function clearFilters() {
  filterService.value = ''
  filterRegion.value = ''
  filterAccount.value = ''
  graph.clearFilters()
  graph.fetchData()
}

onMounted(async () => {
  await graph.fetchFilters()
  await graph.fetchData()
  // Sync any scan that's already running so the panel shows its progress
  jobsStore.fetchJobs()
})
</script>

<style scoped>
.resource-map-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 1rem);
  gap: 0;
}

.truncation-banner {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #f59e0b;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  border-radius: 8px;
  margin-bottom: 0.5rem;
}

.filters-bar {
  padding: 0.5rem 0;
  display: flex;
  align-items: center;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.filter-input {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  color: var(--text-color);
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
  font-size: 0.82rem;
  min-width: 130px;
  font-family: var(--font-body);
}

.filter-input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.map-content {
  flex: 1;
  display: flex;
  min-height: 0;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface-card);
}

.graph-container {
  flex: 1;
  position: relative;
  min-height: 400px;
}

.graph-chart {
  width: 100%;
  height: 100%;
}

.graph-loading,
.graph-error,
.graph-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: var(--text-color-secondary);
}

.graph-loading i {
  font-size: 1.5rem;
}

.graph-error {
  color: var(--color-danger, #ef4444);
}

.graph-empty-icon {
  font-size: 3rem;
  opacity: 0.3;
}

.graph-empty p {
  margin: 0;
  font-size: 0.9rem;
}

.graph-empty-hint {
  font-size: 0.8rem;
  opacity: 0.6;
}

.map-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0;
}

.legend {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.map-stats {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  font-family: var(--font-body);
}

.btn-sm {
  font-size: 0.78rem;
  padding: 0.35rem 0.65rem;
}

.btn-outline {
  background: transparent;
  color: var(--text-color-secondary);
  border-color: var(--surface-border);
}

.btn-outline:hover {
  background: var(--surface-hover);
  color: var(--text-color);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pi-spin {
  animation: spin 1s linear infinite;
}
</style>

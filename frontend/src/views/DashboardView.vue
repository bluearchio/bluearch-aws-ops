<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDashboardStore } from '@/stores/dashboard'
import { useJobsStore } from '@/stores/jobs'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const router = useRouter()
const dashboard = useDashboardStore()
const jobsStore = useJobsStore()
const resourceSummary = computed(() => dashboard.resourceSummary)

// Scan progress state — delegated to the shared jobs store so the
// floating ScanProgressPanel mounted in App.vue stays in sync.
const activeScan = computed(() => jobsStore.currentScanJob)
const scanning = computed(
  () => activeScan.value?.status === 'running' || activeScan.value?.status === 'pending',
)

const scanProgress = computed(() => activeScan.value?.progress ?? 0)
const scanMessage = computed(
  () => activeScan.value?.progress_message || activeScan.value?.message || 'Scanning...',
)

// When a scan completes, refresh dashboard stats
watch(
  () => activeScan.value?.status,
  async (status, oldStatus) => {
    if ((status === 'completed' || status === 'failed') && oldStatus === 'running') {
      await dashboard.refresh()
    }
  },
)

const serviceColors = [
  '#5a9aff', '#19d5d5', '#a855f7', '#f87171', '#4ade80',
  '#facc15', '#fb923c', '#ec4899', '#6366f1', '#14b8a6',
  '#8b5cf6', '#f59e0b',
]

const maxServiceCount = computed(() => {
  if (!resourceSummary.value?.by_service?.length) return 1
  return Math.max(1, ...resourceSummary.value.by_service.map(s => s.count))
})

function serviceColor(idx: number): string {
  return serviceColors[idx % serviceColors.length]
}

const pieChartOption = computed(() => {
  if (!resourceSummary.value?.by_service?.length) return null
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      itemStyle: { borderRadius: 4, borderColor: '#1a1d23', borderWidth: 2 },
      label: { color: '#94a3b8', fontSize: 11 },
      data: resourceSummary.value.by_service.map((s, i) => ({
        name: s.service_name,
        value: s.count,
        itemStyle: { color: serviceColors[i % serviceColors.length] },
      })),
    }],
  }
})

const barChartOption = computed(() => {
  if (!resourceSummary.value?.by_region?.length) return null
  const regions = resourceSummary.value.by_region
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: regions.map(r => r.region), axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 45 }, axisLine: { lineStyle: { color: '#374151' } } },
    yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1f2937' } } },
    series: [{ type: 'bar', data: regions.map((r, i) => ({ value: r.count, itemStyle: { color: serviceColors[i % serviceColors.length], borderRadius: [4, 4, 0, 0] } })) }],
  }
})

onMounted(async () => {
  dashboard.fetchAll({ background: true })
  // Pick up any running scan started elsewhere (CLI, other tab, etc.)
  await jobsStore.fetchJobs({ background: true })
})
</script>

<template>
  <div class="dashboard">
    <div v-if="dashboard.loading" class="loading-state">Loading...</div>
    <div v-else-if="dashboard.error" class="error-state">{{ dashboard.error }}</div>

    <template v-else-if="dashboard.stats">
      <!-- Scan in progress banner -->
      <div v-if="scanning" class="scan-banner">
        <div class="scan-banner-content">
          <i class="pi pi-spin pi-spinner"></i>
          <span class="scan-banner-text">{{ scanMessage }}</span>
          <span class="scan-banner-pct">{{ Math.round(scanProgress) }}%</span>
        </div>
        <div class="scan-banner-track">
          <div class="scan-banner-fill" :style="{ width: scanProgress + '%' }"></div>
        </div>
      </div>

      <!-- Stat cards -->
      <div class="cards-grid" :class="{ 'cards-dimmed': scanning }">
        <div class="stat-card stat-clickable" @click="router.push('/resources')">
          <div class="stat-icon" style="background: rgba(32, 108, 245, 0.12)">
            <i class="pi pi-server" style="color: #5a9aff"></i>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ dashboard.stats.resources }}</div>
            <div class="stat-label">Resources</div>
          </div>
        </div>
        <div class="stat-card stat-clickable" @click="router.push('/recommendations')">
          <div class="stat-icon" style="background: rgba(234, 179, 8, 0.12)">
            <i class="pi pi-exclamation-triangle" style="color: #facc15"></i>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ dashboard.stats.recommendations }}</div>
            <div class="stat-label">Recommendations</div>
          </div>
        </div>
        <div class="stat-card stat-clickable" @click="router.push('/setup/multi-account')">
          <div class="stat-icon" style="background: rgba(34, 197, 94, 0.12)">
            <i class="pi pi-users" style="color: #4ade80"></i>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ dashboard.stats.accounts }}</div>
            <div class="stat-label">Accounts</div>
          </div>
        </div>
        <div class="stat-card" v-if="dashboard.health">
          <div class="stat-icon" :style="{ background: dashboard.health.aws.connected ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.12)' }">
            <i class="pi pi-cloud" :style="{ color: dashboard.health.aws.connected ? '#4ade80' : '#f87171' }"></i>
          </div>
          <div class="stat-info">
            <div class="stat-value" style="font-size: 1rem">{{ dashboard.health.aws.account_id || 'Disconnected' }}</div>
            <div class="stat-label">AWS Account</div>
          </div>
        </div>
      </div>

      <!-- ECharts: Service Pie + Region Bar -->
      <div class="charts-row" v-if="resourceSummary?.by_service?.length">
        <div class="chart-card" v-if="pieChartOption">
          <div class="chart-title text-gradient">Resources by Service</div>
          <v-chart :option="pieChartOption" style="height: 260px" autoresize />
        </div>
        <div class="chart-card" v-if="barChartOption">
          <div class="chart-title text-gradient">Resources by Region</div>
          <v-chart :option="barChartOption" style="height: 260px" autoresize />
        </div>
      </div>

      <!-- Resources by Service (bar breakdown) -->
      <div class="chart-card" v-if="resourceSummary?.by_service?.length">
        <div class="chart-title text-gradient">Service Breakdown</div>
        <div class="service-bars">
          <div
            v-for="(item, idx) in resourceSummary.by_service"
            :key="item.service_name"
            class="service-bar-item clickable-bar"
            @click="router.push({ path: '/resources', query: { service_name: item.service_name } })"
          >
            <span class="service-bar-label">{{ item.service_name }}</span>
            <div class="service-bar-track">
              <div
                class="service-bar-fill"
                :style="{ width: (item.count / maxServiceCount * 100) + '%', background: serviceColor(idx) }"
              ></div>
            </div>
            <span class="service-bar-count">{{ item.count }}</span>
          </div>
        </div>
      </div>

      <!-- Resources by Region -->
      <div class="chart-card" v-if="resourceSummary?.by_region?.length">
        <div class="chart-title text-gradient">Resources by Region</div>
        <div class="service-bars">
          <div
            v-for="item in resourceSummary.by_region"
            :key="item.region"
            class="service-bar-item clickable-bar"
            @click="router.push({ path: '/resources', query: { region: item.region } })"
          >
            <span class="service-bar-label mono">{{ item.region }}</span>
            <div class="service-bar-track">
              <div
                class="service-bar-fill"
                :style="{ width: (item.count / Math.max(1, ...resourceSummary!.by_region.map(r => r.count)) * 100) + '%', background: '#19d5d5' }"
              ></div>
            </div>
            <span class="service-bar-count">{{ item.count }}</span>
          </div>
        </div>
      </div>

      <!-- Recommendations by type -->
      <div class="chart-card" v-if="dashboard.summary && dashboard.summary.by_type.length">
        <div class="chart-title text-gradient">Recommendations by Type</div>
        <div class="table-card">
          <table class="data-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in dashboard.summary.by_type"
                :key="item.recommendation_type"
                class="table-row clickable-row"
                @click="router.push({ path: '/recommendations', query: { recommendation_type: item.recommendation_type } })"
              >
                <td><span class="service-badge">{{ item.recommendation_type.replace(/_/g, ' ') }}</span></td>
                <td>{{ item.count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- By region -->
      <div class="chart-card" v-if="dashboard.summary && dashboard.summary.by_region.length">
        <div class="chart-title text-gradient">Findings by Region</div>
        <div class="table-card">
          <table class="data-table">
            <thead>
              <tr>
                <th>Region</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in dashboard.summary.by_region"
                :key="item.region"
                class="table-row clickable-row"
                @click="router.push({ path: '/resources', query: { region: item.region } })"
              >
                <td><span class="mono">{{ item.region }}</span></td>
                <td>{{ item.count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
@media (max-width: 800px) { .charts-row { grid-template-columns: 1fr; } }

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.stat-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  transition: all 0.2s ease;
  position: relative;
}

.stat-card::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: 11px;
  padding: 1px;
  background: var(--gradient-border);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.25s ease;
  pointer-events: none;
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-card:hover {
  border-color: transparent;
  box-shadow: 0 0 20px rgba(32, 108, 245, 0.2);
}

.stat-clickable {
  cursor: pointer;
}

.stat-clickable:hover {
  border-color: transparent;
  box-shadow: 0 0 20px rgba(32, 108, 245, 0.2);
  transform: translateY(-1px);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 1.1rem;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-top: 2px;
}

.chart-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
  margin-bottom: 1.5rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.chart-card:hover {
  border-color: rgba(32, 108, 245, 0.3);
  box-shadow: var(--glow-blue);
}

.chart-title {
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

/* Service bars (Resources by Service / Region) */
.service-bars {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.service-bar-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.clickable-bar {
  cursor: pointer;
  padding: 0.15rem 0;
  border-radius: 4px;
  transition: background 0.15s;
}

.clickable-bar:hover {
  background: rgba(32, 108, 245, 0.05);
}

.service-bar-label {
  font-size: 0.8rem;
  color: var(--text-color);
  min-width: 90px;
  text-transform: capitalize;
}

.service-bar-track {
  flex: 1;
  height: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  overflow: hidden;
}

.service-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s ease;
}

.service-bar-count {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-color);
  min-width: 35px;
  text-align: right;
  font-family: var(--font-mono);
}

.table-card {
  border-radius: 8px;
  overflow: hidden;
}

.data-table { width: 100%; border-collapse: collapse; }
.data-table th {
  text-align: left;
  padding: 0.75rem 1rem;
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
}
.data-table td {
  padding: 0.7rem 1rem;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--surface-border);
}
.table-row { transition: background 0.1s; }
.table-row:hover { background: rgba(32, 108, 245, 0.05); }

.clickable-row {
  cursor: pointer;
}

.clickable-row:hover {
  background: rgba(32, 108, 245, 0.08);
}

.service-badge {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  text-transform: capitalize;
}

.loading-state { color: var(--text-color-secondary); padding: 2rem; }
.error-state { color: var(--color-danger); padding: 1rem; background: rgba(239, 68, 68, 0.1); border-radius: 8px; }

/* Scan progress banner */
.scan-banner {
  background: rgba(32, 108, 245, 0.08);
  border: 1px solid rgba(32, 108, 245, 0.25);
  border-radius: 10px;
  padding: 0.85rem 1.25rem;
  margin-bottom: 1.25rem;
}

.scan-banner-content {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-color);
}

.scan-banner-content i {
  color: #5a9aff;
  font-size: 0.9rem;
}

.scan-banner-text {
  flex: 1;
}

.scan-banner-pct {
  font-weight: 700;
  font-family: var(--font-mono);
  color: #5a9aff;
}

.scan-banner-track {
  height: 4px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 2px;
  overflow: hidden;
}

.scan-banner-fill {
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, #206CF5, #19D4D4);
  transition: width 0.4s ease;
}

/* Dimmed state while scanning */
.cards-dimmed {
  opacity: 0.45;
  pointer-events: none;
}
</style>

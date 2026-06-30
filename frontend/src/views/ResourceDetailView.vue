<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useResourcesStore } from '@/stores/resources'

const route = useRoute()
const router = useRouter()
const store = useResourcesStore()

function parseIfString(val: unknown): Record<string, unknown> | null {
  if (!val) return null
  if (typeof val === 'string') {
    try { return JSON.parse(val) } catch { return null }
  }
  if (typeof val === 'object') return val as Record<string, unknown>
  return null
}

const tags = computed(() => {
  const raw = store.detail?.current_tags ?? store.detail?.tags
  const parsed = parseIfString(raw)
  if (!parsed) return []
  return Object.entries(parsed).map(([key, value]) => ({ key, value: String(value ?? '') }))
})

const metadata = computed(() => {
  const raw = store.detail?.metadata_json ?? store.detail?.attributes
  const parsed = parseIfString(raw)
  if (!parsed) return []
  return Object.entries(parsed).map(([key, value]) => ({
    key,
    value: typeof value === 'object' && value !== null ? JSON.stringify(value, null, 2) : String(value ?? '-'),
  }))
})

const shortType = computed(() => {
  if (!store.detail?.resource_type) return ''
  const parts = store.detail.resource_type.split('::')
  return parts[parts.length - 1] || store.detail.resource_type
})

const lastScannedDisplay = computed(() => {
  const d = store.detail?.last_scanned_at || store.detail?.updated_at
  if (!d) return null
  return new Date(d).toLocaleString()
})

function goBack() {
  router.push('/resources')
}

onMounted(() => {
  const id = route.params.id as string
  store.fetchDetail(id)
})
</script>

<template>
  <div class="resource-detail">
    <!-- Back button -->
    <button class="btn btn-secondary btn-sm back-btn" @click="goBack">
      <i class="pi pi-arrow-left"></i> Back to Resources
    </button>

    <!-- Loading / Error -->
    <div v-if="store.loading" class="loading-state">
      <i class="pi pi-spin pi-spinner" style="margin-right: 0.5rem"></i> Loading resource...
    </div>
    <div v-else-if="store.error" class="error-state">
      <i class="pi pi-exclamation-circle" style="margin-right: 0.5rem"></i> {{ store.error }}
    </div>

    <!-- Detail -->
    <template v-else-if="store.detail">
      <!-- Header -->
      <div class="detail-header">
        <div class="detail-header-top">
          <span class="service-badge service-badge-lg">{{ store.detail.service_name }}</span>
          <span class="resource-type-badge">{{ shortType }}</span>
          <span v-if="store.detail.resource_type" class="resource-type-full">{{ store.detail.resource_type }}</span>
        </div>
        <div class="detail-arn">{{ store.detail.resource_arn || store.detail.resource_id }}</div>
        <div class="detail-meta-row">
          <span class="detail-meta-item">
            <i class="pi pi-globe"></i> {{ store.detail.region }}
          </span>
          <span class="detail-meta-item">
            <i class="pi pi-building"></i> {{ store.detail.account_id }}
          </span>
          <span v-if="store.detail.created_at" class="detail-meta-item">
            <i class="pi pi-calendar"></i> Created {{ new Date(store.detail.created_at).toLocaleString() }}
          </span>
          <span v-if="lastScannedDisplay" class="detail-meta-item">
            <i class="pi pi-refresh"></i> Last Scanned {{ lastScannedDisplay }}
          </span>
        </div>
      </div>

      <!-- Tags section -->
      <div class="section-card">
        <div class="section-title">
          <i class="pi pi-tags"></i> Tags ({{ tags.length }})
        </div>
        <div v-if="!tags.length" class="empty-section">No tags found</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="tag in tags"
              :key="tag.key"
              class="table-row"
              :class="{ 'managed-tag-row': tag.key.startsWith('bluearch:') }"
            >
              <td class="tag-key">{{ tag.key }}</td>
              <td class="tag-value">{{ tag.value }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Metadata section -->
      <div class="section-card" v-if="metadata.length">
        <div class="section-title">
          <i class="pi pi-list"></i> Metadata ({{ metadata.length }})
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="attr in metadata" :key="attr.key" class="table-row">
              <td class="attr-key">{{ attr.key }}</td>
              <td class="attr-value">
                <pre v-if="attr.value.includes('\n')" class="attr-pre">{{ attr.value }}</pre>
                <span v-else>{{ attr.value }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Recommendations section -->
      <div class="section-card" v-if="store.detail.recommendations?.length">
        <div class="section-title">
          <i class="pi pi-exclamation-circle"></i> Recommendations ({{ store.detail.recommendations.length }})
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Region</th>
              <th>Last Updated</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rec in store.detail.recommendations" :key="rec.id" class="table-row">
              <td><span class="rec-type-badge">{{ rec.recommendation_type }}</span></td>
              <td class="mono">{{ rec.region_name }}</td>
              <td class="mono">{{ rec.last_updated ? new Date(rec.last_updated).toLocaleString() : '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

    </template>
  </div>
</template>

<style scoped>
.back-btn {
  margin-bottom: 1rem;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.15s;
  font-family: var(--font-body);
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-card);
}

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
}

.detail-header {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
  margin-bottom: 1rem;
}

.detail-header-top {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.service-badge {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.service-badge-lg {
  padding: 0.3rem 0.75rem;
  font-size: 0.85rem;
  font-weight: 600;
}

.resource-type-badge {
  background: rgba(25, 212, 212, 0.12);
  color: var(--accent-cyan);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
}

.resource-type-full {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  font-family: var(--font-mono);
}

.detail-arn {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--text-color);
  word-break: break-all;
  margin-bottom: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--surface-ground);
  border-radius: 6px;
  border: 1px solid var(--surface-border);
}

.detail-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.detail-meta-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  color: var(--text-color-secondary);
}

.detail-meta-item i {
  font-size: 0.8rem;
  color: var(--primary-color);
}

.section-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 1rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.section-card:hover {
  border-color: rgba(32, 108, 245, 0.3);
  box-shadow: 0 0 20px rgba(32, 108, 245, 0.15);
}

.section-title {
  padding: 0.75rem 1rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-color);
  border-bottom: 1px solid var(--surface-border);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-title i {
  color: var(--primary-color);
}

.empty-section {
  padding: 1.5rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

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

.table-row {
  transition: background 0.1s;
}

.table-row:hover {
  background: rgba(32, 108, 245, 0.05);
}

.tag-key {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  font-weight: 600;
  color: #5a9aff;
  white-space: nowrap;
}

.tag-value {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  color: var(--text-color);
  word-break: break-all;
}

.attr-key {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--text-color-secondary);
  white-space: nowrap;
  min-width: 150px;
}

.attr-value {
  font-size: 0.82rem;
  color: var(--text-color);
  word-break: break-all;
}

.attr-pre {
  margin: 0;
  padding: 0.5rem;
  background: var(--surface-ground);
  border-radius: 4px;
  font-size: 0.78rem;
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.loading-state {
  color: var(--text-color-secondary);
  padding: 2rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.error-state {
  color: var(--color-danger);
  padding: 1rem;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 8px;
  display: flex;
  align-items: center;
}

.managed-tag-row {
  background: rgba(32, 108, 245, 0.08);
}

.managed-tag-row:hover { background: rgba(32, 108, 245, 0.12); }
.rec-type-badge { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.75rem; background: rgba(32, 108, 245, 0.12); color: #5a9aff; font-weight: 500; }
.risk-badge { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.72rem; font-weight: 500; }
.risk-0 { background: rgba(107, 114, 128, 0.15); color: var(--text-color-secondary); }
.risk-1 { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.risk-2 { background: rgba(249, 115, 22, 0.15); color: #f97316; }
.risk-3 { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.tier-badge { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.72rem; font-weight: 500; }
.tier-confirmed { background: rgba(239, 68, 68, 0.12); color: #f87171; }
.tier-advisory { background: rgba(107, 114, 128, 0.12); color: var(--text-color-secondary); }
.status-pill { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 10px; font-size: 0.72rem; font-weight: 500; }
.pill-open { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.pill-ack { background: rgba(32, 108, 245, 0.15); color: #5a9aff; }
.pill-resolved { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.scenario-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mono { font-family: var(--font-mono, monospace); }
</style>

<template>
  <div class="detail-panel" v-if="node">
    <div class="panel-header">
      <h3>{{ node.name || node.resource_id }}</h3>
      <button class="panel-close" @click="$emit('close')">
        <i class="pi pi-times"></i>
      </button>
    </div>
    <div class="panel-body">
      <div class="panel-field">
        <span class="field-label">Service</span>
        <span class="service-badge" :style="{ background: serviceColor }">{{ node.service_name }}</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Type</span>
        <span class="field-value">{{ node.resource_type }}</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Region</span>
        <span class="field-value">{{ node.region }}</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Account</span>
        <span class="field-value mono">{{ node.account_id }}</span>
      </div>
      <div class="panel-field">
        <span class="field-label">Connections</span>
        <span class="field-value">{{ connectionCount }}</span>
      </div>
      <div class="panel-field" v-if="node.recommendation_count > 0">
        <span class="field-label">Recommendations</span>
        <span class="count-badge count-warning">{{ node.recommendation_count }}</span>
      </div>
      <!-- Tags -->
      <div class="panel-section" v-if="node.tags && Object.keys(node.tags).length > 0">
        <span class="section-title">Tags</span>
        <div class="tags-table">
          <div class="tag-row" v-for="(val, key) in node.tags" :key="key">
            <span class="tag-key">{{ key }}</span>
            <span class="tag-value">{{ val }}</span>
          </div>
        </div>
      </div>

      <div class="panel-arn">
        <span class="field-label">ARN</span>
        <span class="field-value mono arn-text">{{ node.id }}</span>
      </div>

      <div class="panel-actions">
        <button class="btn btn-sm btn-primary" @click="$emit('focus', node.id)">
          <i class="pi pi-search"></i> Focus
        </button>
        <router-link
          :to="resourceDetailPath"
          class="btn btn-sm btn-secondary"
        >
          <i class="pi pi-external-link"></i> Details
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { GraphNode, GraphEdge } from '@/stores/graph'

const props = defineProps<{
  node: GraphNode | null
  edges: GraphEdge[]
}>()

defineEmits<{
  close: []
  focus: [arn: string]
}>()

const SERVICE_COLORS: Record<string, string> = {
  ec2: '#f97316', s3: '#22c55e', lambda: '#a855f7', rds: '#3b82f6',
  dynamodb: '#f59e0b', ecs: '#14b8a6', elb: '#06b6d4', elbv2: '#06b6d4',
  sns: '#e11d48', sqs: '#8b5cf6', cloudwatch: '#ef4444', logs: '#ef4444',
  eks: '#0ea5e9', elasticache: '#dc2626', vpc: '#6b7280', subnet: '#9ca3af',
  sg: '#4b5563', iam: '#eab308',
}

const serviceColor = computed(() => SERVICE_COLORS[props.node?.service_name ?? ''] ?? '#6b7280')

const connectionCount = computed(() => {
  if (!props.node) return 0
  return props.edges.filter(
    e => e.source === props.node!.id || e.target === props.node!.id
  ).length
})

const resourceDetailPath = computed(() => {
  if (!props.node) return '/resources'
  // URL-encode the ARN for the resource detail route
  return `/resources/${encodeURIComponent(props.node.id)}`
})
</script>

<style scoped>
.detail-panel {
  width: 320px;
  min-width: 280px;
  border-left: 1px solid var(--surface-border);
  background: var(--surface-ground);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--surface-border);
}

.panel-header h3 {
  font-size: 0.9rem;
  font-weight: 600;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-close {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.panel-close:hover {
  background: var(--surface-hover);
  color: var(--text-color);
}

.panel-body {
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.panel-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.field-label {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
  font-weight: 500;
  flex-shrink: 0;
}

.field-value {
  font-size: 0.82rem;
  color: var(--text-color);
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}

.service-badge {
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #fff;
  text-transform: uppercase;
}

.count-badge {
  padding: 0.1rem 0.45rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #fff;
}

.count-warning {
  background: #f59e0b;
}

.count-danger {
  background: #ef4444;
}

.panel-section {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding-top: 0.35rem;
  border-top: 1px solid var(--surface-border);
}

.section-title {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
  font-weight: 600;
}

.tags-table {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.tag-row {
  display: flex;
  gap: 0.5rem;
  font-size: 0.78rem;
}

.tag-key {
  color: var(--text-color-secondary);
  font-family: var(--font-mono, monospace);
  flex-shrink: 0;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-value {
  color: var(--text-color);
  font-family: var(--font-mono, monospace);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-arn {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding-top: 0.35rem;
  border-top: 1px solid var(--surface-border);
}

.arn-text {
  word-break: break-all;
  white-space: normal;
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  line-height: 1.4;
}

.panel-actions {
  display: flex;
  gap: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--surface-border);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  font-size: 0.78rem;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  font-family: var(--font-body);
}

.btn-sm {
  font-size: 0.75rem;
  padding: 0.3rem 0.6rem;
}

.btn-primary {
  background: rgba(32, 108, 245, 0.15);
  color: #5a9aff;
  border-color: rgba(32, 108, 245, 0.3);
}

.btn-primary:hover {
  background: rgba(32, 108, 245, 0.25);
}

.btn-secondary {
  background: transparent;
  color: var(--text-color-secondary);
  border-color: var(--surface-border);
}

.btn-secondary:hover {
  background: var(--surface-hover);
  color: var(--text-color);
}
</style>

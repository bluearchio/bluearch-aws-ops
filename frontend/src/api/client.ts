// API client — matches tag-manager pattern: request<T>, requestMutation<T>

const BASE_URL = import.meta.env.DEV ? 'http://localhost:8095' : ''

async function request<T>(
  path: string,
  params?: Record<string, string>,
): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }

  const res = await fetch(url.toString(), { credentials: 'include' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function requestMutation<T>(
  method: 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'include',
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// Typed API methods
import type {
  PaginatedResponse,
  ResourceResponse,
  ResourceSummary,
  RecommendationResponse,
  RecommendationSummary,
  AccountResponse,
  ScanJobResponse,
  ScanJob,
  ScanHistoryItem,
  HealthResponse,
  SystemStats,
  SetupValidation,
  IamPolicy,
  AssumeRoleConfig,
  AssumeRoleConfigRecord,
  AssumeRoleStatusResponse,
  AlarmResponse,
  AlarmCreate,
  AlarmUpdate,
  AlarmEventResponse,
  AlarmEvaluateResponse,
  AlarmOptions,
  ConversationSummary,
  ConversationMessage,
  ChatStreamEvent,
  InfrastructureStatusResponse,
  ResourceGroupInfo,
  StackSetStatusResponse,
  AccountValidationResponse,
  DeployRequest,
  TemplateMetadata,
  TemplateDetail,
  JobResponse,
  JobSubmittedResponse,
  NotificationEvent,
  EventTrackingStatusResponse,
  AccountContextResponse,
  AccountContextListResponse,
  ContextGateResponse,
  PermissionStatusResponse,
} from '@/types/api'

export const api = {
  // System
  health: () => request<HealthResponse>('/api/v1/system/health'),
  stats: () => request<SystemStats>('/api/v1/system/stats'),
  notifications: (params?: { limit?: number; refresh?: boolean }) =>
    request<NotificationEvent[]>('/api/v1/notifications', {
      limit: String(params?.limit ?? 20),
      refresh: String(params?.refresh ?? false),
    }),

  // Resources
  listResources: (params?: Record<string, string>) =>
    request<PaginatedResponse<ResourceResponse>>('/api/v1/resources', params),
  getResource: (id: string) =>
    request<ResourceResponse>(`/api/v1/resources/${id}`),
  resourceSummary: () =>
    request<ResourceSummary>('/api/v1/resources/summary'),

  // Recommendations
  listRecommendations: (params?: Record<string, string>) =>
    request<PaginatedResponse<RecommendationResponse>>('/api/v1/recommendations', params),
  getRecommendation: (id: string) =>
    request<RecommendationResponse>(`/api/v1/recommendations/${id}`),
  recommendationSummary: () =>
    request<RecommendationSummary>('/api/v1/recommendations/summary'),
  recommendationTypes: () =>
    request<{ type: string; count: number }[]>('/api/v1/recommendations/types'),
  listRecommendationNotes: (rec_id: string) =>
    request<import('@/types/api').RecommendationNote[]>(
      `/api/v1/recommendations/${rec_id}/notes`,
    ),
  createRecommendationNote: (rec_id: string, body: string, author?: string) =>
    requestMutation<import('@/types/api').RecommendationNote>(
      'POST',
      `/api/v1/recommendations/${rec_id}/notes`,
      author ? { body, author } : { body },
    ),
  updateRecommendationNote: (note_id: string, body: string) =>
    requestMutation<import('@/types/api').RecommendationNote>(
      'PATCH',
      `/api/v1/recommendations/notes/${note_id}`,
      { body },
    ),
  deleteRecommendationNote: (note_id: string) =>
    requestMutation<void>('DELETE', `/api/v1/recommendations/notes/${note_id}`),

  // Accounts
  listAccounts: () => request<AccountResponse[]>('/api/v1/accounts'),
  accountsValidate: () => request<AccountValidationResponse>('/api/v1/accounts/validate'),
  accountsStacksetStatus: () => request<StackSetStatusResponse>('/api/v1/accounts/status'),

  // Multi-Account (aliases matching Tag Manager CLI method names)
  validateAccount: () => request<AccountValidationResponse>('/api/v1/accounts/validate'),
  multiAccountStatus: () => request<StackSetStatusResponse>('/api/v1/accounts/status'),
  deployMultiAccount: (body?: DeployRequest) =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/accounts/deploy', body || {}),
  updateMultiAccount: () =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/accounts/update'),
  removeMultiAccount: () =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/accounts/remove'),

  // CloudFormation Templates
  listTemplates: () => request<TemplateMetadata[]>('/api/v1/system/templates'),
  getTemplate: (name: string) => request<TemplateDetail>(`/api/v1/system/templates/${name}`),

  // Generic Jobs (multi-account, delete, etc. — not scan-specific)
  listJobs: (params?: Record<string, string>) =>
    request<JobResponse[]>('/api/v1/jobs', params),
  getJob: (id: string) => request<JobResponse>(`/api/v1/jobs/${id}`),

  // Scans
  startScan: (body?: { services?: string[]; regions?: string[] }) =>
    requestMutation<ScanJobResponse>('POST', '/api/v1/scans', body || {}),
  listScanJobs: () => request<ScanJob[]>('/api/v1/scans/jobs'),
  getScanJob: (id: string) => request<ScanJob>(`/api/v1/scans/jobs/${id}`),
  cancelScan: (id: string) =>
    requestMutation<ScanJob>('POST', `/api/v1/scans/jobs/${id}/cancel`),
  scanHistory: () => request<ScanHistoryItem[]>('/api/v1/scans/history'),

  // Setup
  setupValidate: () => request<SetupValidation>('/api/v1/setup/validate'),
  iamPolicy: () => request<IamPolicy>('/api/v1/setup/iam-policy'),

  // Assume Role
  assumeRoleStatus: () => request<AssumeRoleStatusResponse>('/api/v1/assume-role/status'),
  assumeRoleConfigs: () => request<AssumeRoleConfigRecord[]>('/api/v1/assume-role/configs'),
  addAssumeRole: (data: { account_id: string; role_arn: string; external_id?: string }) =>
    requestMutation<AssumeRoleConfig>('POST', '/api/v1/assume-role/add', data),
  deleteAssumeRole: (id: string) =>
    requestMutation<void>('DELETE', `/api/v1/assume-role/${id}`),
  testAssumeRole: (id: string) =>
    requestMutation<{ success: boolean; error?: string }>('POST', `/api/v1/assume-role/test/${id}`),
  deployAssumeRole: (body: Record<string, string | undefined>) =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/assume-role/deploy', body),
  disableAssumeRole: (body: { delete_stack: boolean }) =>
    requestMutation<{ success?: boolean; message?: string; job_id?: string; job_type?: string; status?: string }>(
      'POST',
      '/api/v1/assume-role/disable',
      body,
    ),

  // Alarms
  listAlarms: () => request<AlarmResponse[]>('/api/v1/alarms'),
  getAlarm: (id: string) => request<AlarmResponse>(`/api/v1/alarms/${id}`),
  createAlarm: (body: AlarmCreate) =>
    requestMutation<AlarmResponse>('POST', '/api/v1/alarms', body),
  updateAlarm: (id: string, body: AlarmUpdate) =>
    requestMutation<AlarmResponse>('PATCH', `/api/v1/alarms/${id}`, body),
  deleteAlarm: (id: string) =>
    requestMutation<{ success: boolean; message: string }>('DELETE', `/api/v1/alarms/${id}`),
  evaluateAlarm: (id: string) =>
    requestMutation<AlarmEvaluateResponse>('POST', `/api/v1/alarms/${id}/evaluate`),
  evaluateAllAlarms: () =>
    requestMutation<{ evaluated: number; results: unknown[] }>('POST', '/api/v1/alarms/evaluate-all'),
  listAlarmEvents: (id: string, limit = 50) =>
    request<AlarmEventResponse[]>(`/api/v1/alarms/${id}/events`, { limit: String(limit) }),
  testAlarmNotification: (id: string) =>
    requestMutation<{ success: boolean; error?: string }>('POST', `/api/v1/alarms/${id}/test`),
  alarmOptions: () => request<AlarmOptions>('/api/v1/alarms/meta/options'),

  // Opt-In Hub
  optinAuthorization: () =>
    request<{ authorized: boolean; error?: string }>('/api/v1/optin/authorization'),
  optinServices: () =>
    request<
      Array<{
        name: string
        service_principal: string
        enabled: boolean
        supported: boolean
        description?: string
        toggle_supported?: boolean
        disabled_reason?: string
      }>
    >(
      '/api/v1/optin/services',
    ),
  optinToggleService: (service_principal: string, enable: boolean) =>
    requestMutation<{ success: boolean; message: string }>(
      'POST',
      '/api/v1/optin/services/toggle',
      { service_principal, enable },
    ),
  optinEnrollment: (service: 'compute-optimizer' | 'cost-optimization-hub') =>
    request<{
      service: string
      org_enabled: boolean
      accounts: Array<{ account_id: string; status: string; error?: string }>
    }>(`/api/v1/optin/enrollment/${service}`),
  optinUpdateEnrollment: (body: {
    service: string
    account_id: string
    status: 'Active' | 'Inactive'
    optin_organization?: boolean
  }) =>
    requestMutation<{ success: boolean; service: string; new_status: string }>(
      'POST',
      '/api/v1/optin/enrollment/update',
      body,
    ),

  // Context
  currentContext: () => request<AccountContextResponse>('/api/v1/system/context'),
  allContexts: () => request<AccountContextListResponse>('/api/v1/system/contexts'),
  listContexts: () => request<AccountContextListResponse>('/api/v1/system/contexts'),
  addContext: (body?: { alias?: string }) =>
    requestMutation<AccountContextResponse>('POST', '/api/v1/system/context', body || {}),
  switchContext: (body: string | { account_id: string }) => {
    const payload = typeof body === 'string' ? { account_id: body } : body
    return requestMutation<AccountContextResponse>('POST', '/api/v1/system/context/switch', payload)
  },
  removeContext: (accountId: string) =>
    requestMutation<void>('DELETE', `/api/v1/system/context/${accountId}`),
  contextGate: () => request<ContextGateResponse>('/api/v1/system/context/gate'),

  // Graph
  graphData: (params?: Record<string, string>) => request<any>('/api/v1/graph/data', params),
  graphFilters: () => request<any>('/api/v1/graph/filters'),
  graphStats: () => request<any>('/api/v1/graph/stats'),

  // Infrastructure
  infrastructureStatus: () => request<InfrastructureStatusResponse>('/api/v1/infrastructure/status'),
  createResourceGroup: () =>
    requestMutation<ResourceGroupInfo>('POST', '/api/v1/infrastructure/resource-group/create'),
  deleteResourceGroup: () =>
    requestMutation<{ success: boolean }>('POST', '/api/v1/infrastructure/resource-group/delete'),
  deleteCurStack: () =>
    requestMutation<{ success: boolean; message: string }>('POST', '/api/v1/infrastructure/cur-stack/delete'),
  deployCurStack: (config?: { bucket_name?: string; report_name?: string }) =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/infrastructure/stacks/cost-reports/deploy', config || {}),
  updateInfraStack: (component: string) =>
    requestMutation<JobSubmittedResponse>('POST', `/api/v1/infrastructure/stacks/${component}/update`),

  // Event Tracking
  eventTrackingStatus: () => request<EventTrackingStatusResponse>('/api/v1/event-tracking/status'),
  deployEventTracking: (targets: Record<string, string[]>) =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/event-tracking/deploy', { targets }),
  removeEventTracking: (targets: Record<string, string[]>) =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/event-tracking/remove', { targets }),
  removeAllEventTracking: () =>
    requestMutation<JobSubmittedResponse>('POST', '/api/v1/event-tracking/remove-all'),
  eventTrackingService: (action: string) =>
    requestMutation<Record<string, unknown>>('POST', '/api/v1/event-tracking/service', { action }),
  eventTrackingControl: (action: string) =>
    requestMutation<any>('POST', '/api/v1/event-tracking/service', { action }),

  // Jobs (extended)
  submitScanJob: (data?: { services?: string[]; regions?: string[] }) =>
    requestMutation<any>('POST', '/api/v1/jobs/scan', data || {}),
  submitDeleteJob: (data?: { services?: string[] }) =>
    requestMutation<any>('POST', '/api/v1/jobs/delete', data || {}),

  // Permissions
  permissions: () => request<PermissionStatusResponse>('/api/v1/system/permissions'),
  refreshPermissions: () => requestMutation<PermissionStatusResponse>('POST', '/api/v1/system/permissions/refresh'),

  // AI Chat
  chatStream(body: { question: string; model: string; session_id?: string }): AsyncGenerator<ChatStreamEvent> {
    const url = `${BASE_URL}/api/v1/ai/chat`
    return (async function* () {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        credentials: 'include',
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue
          const payload = trimmed.slice(6)
          if (payload === '[DONE]') return
          try {
            yield JSON.parse(payload) as ChatStreamEvent
          } catch {
            // skip malformed SSE lines
          }
        }
      }
    })()
  },
  getConversations: () => request<ConversationSummary[]>('/api/v1/ai/conversations'),
  getConversationMessages: (id: string) =>
    request<ConversationMessage[]>(`/api/v1/ai/conversations/${id}/messages`),
  deleteConversation: (id: string) =>
    requestMutation<{ success: boolean }>('DELETE', `/api/v1/ai/conversations/${id}`),

  // Log Analysis — scanning happens through the unified /api/v1/scans endpoint
  // (LogsCollector in the scan pipeline), so there's no dedicated scan route.
  logsListScans: (params?: Record<string, string>) =>
    request<import('@/types/logs').LogScan[]>('/api/v1/logs/scans', params),
  logsListFindings: (params?: Record<string, string>) =>
    request<import('@/types/logs').LogFindingsPage>('/api/v1/logs/findings', params),
  logsGetFinding: (id: string) =>
    request<import('@/types/logs').LogFinding>(`/api/v1/logs/findings/${id}`),
  logsAnalyzeFinding: (id: string, body: { model?: string }) =>
    requestMutation<import('@/types/logs').LogAnalyzeResponse>(
      'POST',
      `/api/v1/logs/findings/${id}/analyze`,
      body,
    ),
  logsAnalyzeFindingStream(id: string, body: { model?: string }): AsyncGenerator<import('@/types/logs').LogAnalysisStreamEvent> {
    const url = `${BASE_URL}/api/v1/logs/findings/${id}/analyze/stream`
    return (async function* () {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        credentials: 'include',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response body')
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // Split on the SSE record boundary (blank line)
        let idx: number
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const raw = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 2)
          if (!raw.startsWith('data: ')) continue
          const payload = raw.slice(6).trim()
          if (payload === '[DONE]') return
          try {
            yield JSON.parse(payload) as import('@/types/logs').LogAnalysisStreamEvent
          } catch {
            // skip malformed
          }
        }
      }
    })()
  },
}

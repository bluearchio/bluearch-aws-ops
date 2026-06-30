// TypeScript interfaces for the Log Analysis feature

export type LogSeverity = 'critical' | 'high' | 'medium' | 'low'
export type LogLinkStatus = 'linked' | 'unlinked'
export type LogFindingStatus = 'open' | 'acknowledged' | 'resolved'

export interface LogFinding {
  id: string
  scan_id: string | null
  log_group_name: string | null
  error_pattern: string | null
  severity: LogSeverity | null
  occurrence_count: number
  first_seen: string | null
  last_seen: string | null
  sample_message: string | null
  resource_id: string | null
  resource_type: string | null
  service_name: string | null
  link_status: LogLinkStatus
  status: LogFindingStatus
  ai_analysis: string | null
  ai_analyzed_at: string | null
  detected_at: string | null
}

export interface LogScan {
  id: string
  account_id: string | null
  region: string | null
  log_groups_scanned: number
  findings_count: number
  time_window_hours: number
  started_at: string | null
  completed_at: string | null
  status: 'running' | 'completed' | 'failed'
  error_message: string | null
}

export interface LogFindingsPage {
  items: LogFinding[]
  total: number
  page: number
  page_size: number
}

export interface LogAnalyzeResponse {
  finding_id: string
  analysis: string
  model: string
  analyzed_at: string
}

export type LogAnalysisStreamEvent =
  | { type: 'text_delta'; text: string }
  | { type: 'tool_use'; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; name: string; summary: string }
  | { type: 'done'; analysis: string }
  | { type: 'error'; message: string }

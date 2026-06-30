import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { ChatMessage, ConversationSummary } from '@/types/api'

const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  haiku: { input: 0.25, output: 1.25 },
  sonnet: { input: 3.0, output: 15.0 },
  opus: { input: 15.0, output: 75.0 },
}

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  status?: 'running' | 'success' | 'failed'
  summary?: string
  startedAt?: number
  durationMs?: number
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const model = ref('auto')
  const sessionId = ref<string | null>(null)
  const isStreaming = ref(false)
  const error = ref<string | null>(null)
  const currentToolCalls = ref<ToolCall[]>([])
  const suggestions = ref<string[]>([])
  const selectedModel = ref<string | null>(null)
  const conversations = ref<ConversationSummary[]>([])
  const conversationId = ref<string | null>(null)
  const totalInputTokens = ref(0)
  const totalOutputTokens = ref(0)
  const totalToolCalls = ref(0)
  const sessionStartTime = ref<number | null>(null)

  function getSessionStats() {
    const questions = messages.value.filter((m) => m.role === 'user').length
    const toolCalls = totalToolCalls.value
    let duration = ''
    if (sessionStartTime.value) {
      const ms = Date.now() - sessionStartTime.value
      const totalSec = Math.floor(ms / 1000)
      const min = Math.floor(totalSec / 60)
      const sec = totalSec % 60
      duration = min > 0 ? `${min}m ${sec}s` : `${sec}s`
    }
    const modelKey = selectedModel.value?.toLowerCase() || model.value?.toLowerCase() || 'sonnet'
    const pricing = MODEL_PRICING[modelKey] || MODEL_PRICING.sonnet
    const estimatedCost =
      (totalInputTokens.value / 1_000_000) * pricing.input +
      (totalOutputTokens.value / 1_000_000) * pricing.output
    return {
      questions,
      toolCalls,
      duration,
      estimatedCost,
      inputTokens: totalInputTokens.value,
      outputTokens: totalOutputTokens.value,
    }
  }

  async function sendMessage(question: string) {
    if (isStreaming.value) return

    // Clear suggestions from previous response
    suggestions.value = []
    selectedModel.value = null

    // Start session timer on first message
    if (sessionStartTime.value === null) {
      sessionStartTime.value = Date.now()
    }

    // Add user message
    messages.value.push({
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    })

    // Add empty assistant message to fill via streaming
    const assistantMsg: ChatMessage = {
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    }
    messages.value.push(assistantMsg)

    isStreaming.value = true
    error.value = null
    currentToolCalls.value = []

    try {
      const stream = api.chatStream({
        question,
        model: model.value,
        session_id: sessionId.value || undefined,
      })

      for await (const event of stream) {
        if (event.type === 'text' && typeof event.content === 'string') {
          assistantMsg.content += event.content
        } else if (event.type === 'tool_call' && typeof event.content === 'object') {
          const data = event.content as { name: string; input: Record<string, unknown>; started_at?: number }
          currentToolCalls.value.push({
            name: data.name,
            input: data.input,
            status: 'running',
            startedAt: Date.now(),
          })
          totalToolCalls.value++
        } else if (event.type === 'tool_result' && typeof event.content === 'object') {
          const data = event.content as { name: string; success: boolean; summary?: string; duration_ms?: number }
          const toolCall = currentToolCalls.value.find(
            (tc) => tc.name === data.name && tc.status === 'running',
          )
          if (toolCall) {
            toolCall.status = data.success ? 'success' : 'failed'
            toolCall.summary = data.summary
            toolCall.durationMs = data.duration_ms ?? undefined
          }
        } else if (event.type === 'suggestions' && Array.isArray(event.content)) {
          suggestions.value = event.content as string[]
        } else if (event.type === 'done' && typeof event.content === 'object') {
          const data = event.content as Record<string, unknown>
          if (data.session_id) {
            sessionId.value = data.session_id as string
          }
          if (data.conversation_id) {
            conversationId.value = data.conversation_id as string
          }
          if (data.selected_model) {
            selectedModel.value = data.selected_model as string
          }
          if (typeof data.input_tokens === 'number') {
            totalInputTokens.value = data.input_tokens
          }
          if (typeof data.output_tokens === 'number') {
            totalOutputTokens.value = data.output_tokens
          }
        } else if (event.type === 'error') {
          error.value = typeof event.content === 'string' ? event.content : 'Stream error'
        }
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to send message'
      if (!assistantMsg.content) {
        assistantMsg.content = '[Error: ' + error.value + ']'
      }
    } finally {
      isStreaming.value = false
      // Refresh conversations list after message completes
      fetchConversations()
    }
  }

  async function fetchConversations() {
    try {
      conversations.value = await api.getConversations()
    } catch {
      // Silently fail - conversations are a nice-to-have
    }
  }

  async function loadConversation(id: string) {
    try {
      const msgs = await api.getConversationMessages(id)
      messages.value = msgs.map((m) => ({
        role: m.role,
        content: m.content,
        timestamp: m.created_at,
      }))
      sessionId.value = id
      conversationId.value = id
      suggestions.value = []
      currentToolCalls.value = []
      error.value = null
      totalInputTokens.value = 0
      totalOutputTokens.value = 0
      totalToolCalls.value = 0
      sessionStartTime.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load conversation'
    }
  }

  async function deleteConversation(id: string) {
    try {
      await api.deleteConversation(id)
      conversations.value = conversations.value.filter((c) => c.id !== id)
      if (conversationId.value === id) {
        clearHistory()
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to delete conversation'
    }
  }

  function clearHistory() {
    messages.value = []
    sessionId.value = null
    conversationId.value = null
    error.value = null
    suggestions.value = []
    selectedModel.value = null
    currentToolCalls.value = []
    totalInputTokens.value = 0
    totalOutputTokens.value = 0
    totalToolCalls.value = 0
    sessionStartTime.value = null
  }

  function newChat() {
    clearHistory()
  }

  return {
    messages,
    model,
    sessionId,
    isStreaming,
    error,
    currentToolCalls,
    suggestions,
    selectedModel,
    conversations,
    conversationId,
    getSessionStats,
    sendMessage,
    clearHistory,
    newChat,
    fetchConversations,
    loadConversation,
    deleteConversation,
  }
})

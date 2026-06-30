<template>
  <div class="chat-view">
    <div class="chat-layout">
      <!-- Conversation Sidebar -->
      <div class="conversation-sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div class="sidebar-header">
          <button class="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed" :title="sidebarCollapsed ? 'Expand' : 'Collapse'">
            <i :class="sidebarCollapsed ? 'pi pi-angle-right' : 'pi pi-angle-left'"></i>
          </button>
          <template v-if="!sidebarCollapsed">
            <span class="sidebar-title">Conversations</span>
            <button class="new-chat-btn" @click="chatStore.newChat()" title="New Chat">
              <i class="pi pi-plus"></i>
            </button>
          </template>
        </div>
        <div v-if="!sidebarCollapsed" class="conversation-list">
          <div
            v-for="conv in chatStore.conversations"
            :key="conv.id"
            class="conversation-item"
            :class="{ active: chatStore.conversationId === conv.id }"
            @click="chatStore.loadConversation(conv.id)"
          >
            <div class="conv-title">{{ conv.title }}</div>
            <div class="conv-meta">
              <span>{{ conv.message_count }} msgs</span>
              <span>{{ formatRelativeTime(conv.updated_at) }}</span>
            </div>
            <button
              class="conv-delete"
              @click.stop="confirmDeleteConversation(conv.id)"
              title="Delete"
            >
              <i class="pi pi-trash"></i>
            </button>
          </div>
          <div v-if="!chatStore.conversations.length" class="no-conversations">
            No conversations yet
          </div>
        </div>
      </div>

      <!-- Main Chat -->
      <div class="chat-container">
        <!-- Messages -->
        <div ref="messagesContainer" class="messages">
          <div v-if="!chatStore.messages.length" class="empty-state">
            <div class="empty-icon">
              <i class="pi pi-comment"></i>
            </div>
            <h3>AWS AI Assistant</h3>
            <p>Ask questions about your AWS resources, recommendations, and alarms.</p>
            <div class="example-questions">
              <button
                v-for="q in exampleQuestions"
                :key="q"
                class="example-btn"
                @click="sendExample(q)"
              >{{ q }}</button>
            </div>
          </div>

          <div
            v-for="(msg, idx) in chatStore.messages"
            :key="idx"
            class="message"
            :class="msg.role"
          >
            <div class="message-avatar">
              <i :class="msg.role === 'user' ? 'pi pi-user' : 'pi pi-bolt'"></i>
            </div>
            <div class="message-content">
              <template v-if="msg.role === 'assistant'">
                <!-- Show tool calls when streaming -->
                <div
                  v-if="chatStore.isStreaming && idx === chatStore.messages.length - 1 && chatStore.currentToolCalls.length > 0"
                  class="tool-calls-panel"
                >
                  <div class="tool-calls-header">
                    <i class="pi pi-spin pi-cog"></i>
                    <span>Executing AWS operations...</span>
                  </div>
                  <div class="tool-calls-list">
                    <div
                      v-for="(tool, tidx) in chatStore.currentToolCalls"
                      :key="tidx"
                      class="tool-call-item"
                      :class="tool.status"
                    >
                      <span class="tool-icon">
                        <i v-if="tool.status === 'running'" class="pi pi-spin pi-spinner"></i>
                        <i v-else-if="tool.status === 'success'" class="pi pi-check-circle"></i>
                        <i v-else-if="tool.status === 'failed'" class="pi pi-times-circle"></i>
                      </span>
                      <span class="tool-name">{{ formatToolName(tool.name) }}</span>
                      <span v-if="tool.status === 'running' && tool.startedAt" class="tool-duration running">
                        {{ formatElapsed(tool.startedAt) }}...
                      </span>
                      <span v-else-if="tool.durationMs != null" class="tool-duration">
                        {{ (tool.durationMs / 1000).toFixed(1) }}s
                      </span>
                      <span v-if="tool.summary" class="tool-summary">{{ tool.summary }}</span>
                    </div>
                  </div>
                </div>
                <!-- Show thinking state when streaming and no content/tools yet -->
                <div
                  v-else-if="chatStore.isStreaming && idx === chatStore.messages.length - 1 && !msg.content"
                  class="message-text thinking-state"
                >
                  <div class="thinking-content">
                    <span class="thinking-icon"><i class="pi pi-spin pi-cog"></i></span>
                    <span class="thinking-text">Analyzing your request...</span>
                  </div>
                  <div class="thinking-subtext">
                    The AI is preparing a response.
                  </div>
                </div>
                <!-- Show actual content when available -->
                <div
                  v-if="msg.content"
                  class="message-text markdown-body"
                  @click="handleContentClick"
                  v-html="renderMarkdown(msg.content)"
                ></div>
              </template>
              <div v-else class="message-text">{{ msg.content }}</div>
              <div class="message-footer">
                <span class="message-time">{{ formatDateTime(msg.timestamp) }}</span>
                <span
                  v-if="msg.role === 'assistant' && idx === chatStore.messages.length - 1 && chatStore.selectedModel && !chatStore.isStreaming"
                  class="model-badge"
                >
                  Answered with {{ chatStore.selectedModel }}
                </span>
              </div>
            </div>
          </div>

          <!-- Suggestion Chips -->
          <div v-if="chatStore.suggestions.length && !chatStore.isStreaming" class="suggestion-chips">
            <div class="suggestion-label">Follow-up questions:</div>
            <div class="suggestion-list">
              <button
                v-for="(s, i) in chatStore.suggestions"
                :key="i"
                class="suggestion-chip"
                @click="sendExample(s)"
              >
                <i class="pi pi-arrow-right"></i>
                {{ s }}
              </button>
            </div>
          </div>
        </div>

        <!-- Input -->
        <div class="input-area">
          <div class="input-controls">
            <select v-model="chatStore.model" class="model-select">
              <option value="auto">Auto (Recommended)</option>
              <option value="haiku">Haiku (Fast)</option>
              <option value="sonnet">Sonnet (Balanced)</option>
              <option value="opus">Opus (Best)</option>
            </select>
            <div v-if="chatStore.messages.length" class="input-controls-right">
              <div class="usage-btn-wrapper">
                <button
                  class="usage-btn"
                  :class="{ active: showUsagePanel }"
                  @click="showUsagePanel = !showUsagePanel"
                  title="Session Usage"
                >
                  <i class="pi pi-chart-bar"></i>
                </button>
                <div v-if="showUsagePanel" class="usage-panel" @click.stop>
                  <div class="usage-panel-title">Session Usage</div>
                  <div class="usage-panel-divider"></div>
                  <div class="usage-panel-rows">
                    <div class="usage-row">
                      <span class="usage-label">Questions</span>
                      <span class="usage-value">{{ sessionStats.questions }}</span>
                    </div>
                    <div class="usage-row">
                      <span class="usage-label">Tools Used</span>
                      <span class="usage-value">{{ sessionStats.toolCalls }}</span>
                    </div>
                    <div class="usage-row">
                      <span class="usage-label">Duration</span>
                      <span class="usage-value">{{ sessionStats.duration || '--' }}</span>
                    </div>
                    <div class="usage-row">
                      <span class="usage-label">Est. Cost</span>
                      <span class="usage-value">${{ sessionStats.estimatedCost.toFixed(4) }}</span>
                    </div>
                  </div>
                  <div class="usage-panel-divider"></div>
                  <div class="usage-tokens">
                    Tokens: {{ sessionStats.inputTokens.toLocaleString() }} in / {{ sessionStats.outputTokens.toLocaleString() }} out
                  </div>
                </div>
              </div>
              <button
                class="btn btn-secondary btn-sm"
                @click="chatStore.newChat()"
              >New Chat</button>
            </div>
          </div>
          <div class="input-row">
            <textarea
              v-model="input"
              class="chat-input"
              placeholder="Ask about your AWS resources..."
              rows="1"
              :disabled="chatStore.isStreaming"
              @keydown.enter.exact.prevent="send"
              @input="autoResize"
            ></textarea>
            <button
              class="send-btn"
              :disabled="!input.trim() || chatStore.isStreaming"
              @click="send"
            >
              <i class="pi pi-send"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()
const router = useRouter()
const input = ref('')
const messagesContainer = ref<HTMLElement | null>(null)
const sidebarCollapsed = ref(false)
const showUsagePanel = ref(false)

// Reactive session stats (uses elapsedTick to keep duration fresh)
const sessionStats = computed(() => {
  void elapsedTick.value // reactive dependency for live updates
  return chatStore.getSessionStats()
})

// Timer for live elapsed tracking
let elapsedTimer: ReturnType<typeof setInterval> | null = null
const elapsedTick = ref(0)

const exampleQuestions = [
  'Show my active recommendations',
  'What are my idle EC2 instances?',
  'Summarize my last scan results',
  'What alarms should I set up?',
]

// Configure marked for safe rendering
marked.setOptions({
  breaks: true,
  gfm: true,
})

function onClickOutsideUsage(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.usage-btn-wrapper')) {
    showUsagePanel.value = false
  }
}

onMounted(() => {
  chatStore.fetchConversations()
  elapsedTimer = setInterval(() => {
    elapsedTick.value++
  }, 100)
  document.addEventListener('click', onClickOutsideUsage)
})

onUnmounted(() => {
  if (elapsedTimer) clearInterval(elapsedTimer)
  document.removeEventListener('click', onClickOutsideUsage)
})

function formatElapsed(startedAt: number): string {
  void elapsedTick.value
  const ms = Date.now() - startedAt
  return (ms / 1000).toFixed(1) + 's'
}

function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

function formatDateTime(val?: string | null): string {
  if (!val) return ''
  try {
    return new Date(val).toLocaleTimeString()
  } catch {
    return ''
  }
}

function confirmDeleteConversation(id: string) {
  if (confirm('Delete this conversation?')) {
    chatStore.deleteConversation(id)
  }
}

function renderMarkdown(content: string): string {
  if (!content) return ''

  let html = marked.parse(content) as string

  // Convert resource ARNs to clickable links
  html = html.replace(
    /\b(arn:aws:[a-zA-Z0-9\-]+:[a-z0-9\-]*:\d{12}:[^\s,)}\]<]+)/g,
    '<a href="#" class="resource-link" data-arn="$1" title="View in Resources">$1</a>',
  )

  // Convert AWS account IDs (12 digits standalone) to links
  html = html.replace(
    /\b(\d{12})\b(?![^<]*>)/g,
    '<a href="#" class="account-link" data-account="$1" title="Filter by account $1">$1</a>',
  )

  return html
}

function formatToolName(name: string): string {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function handleContentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('a')) return
  e.preventDefault()

  const link = target.closest('a') as HTMLAnchorElement

  if (link.classList.contains('resource-link')) {
    const arn = link.dataset.arn
    if (arn) {
      router.push({ path: '/resources', query: { search: arn } })
    }
  } else if (link.classList.contains('account-link')) {
    const account = link.dataset.account
    if (account) {
      router.push({ path: '/resources', query: { account_id: account } })
    }
  }
}

function send() {
  const text = input.value.trim()
  if (!text || chatStore.isStreaming) return
  input.value = ''
  const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement | null
  if (textarea) textarea.style.height = 'auto'
  chatStore.sendMessage(text)
}

function sendExample(q: string) {
  input.value = ''
  chatStore.sendMessage(q)
}

function autoResize(e: Event) {
  const target = e.target as HTMLTextAreaElement
  target.style.height = 'auto'
  target.style.height = Math.min(target.scrollHeight, 120) + 'px'
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// Auto-scroll on new messages
watch(() => chatStore.messages.length, scrollToBottom)

// Auto-scroll during streaming
watch(
  () => chatStore.messages[chatStore.messages.length - 1]?.content,
  scrollToBottom,
)
</script>

<style scoped>
.chat-view {
  height: calc(100vh - var(--topbar-height) - 3rem);
  display: flex;
  flex-direction: column;
}

.chat-layout {
  flex: 1;
  display: flex;
  gap: 0;
  overflow: hidden;
  border: 1px solid var(--surface-border);
  border-radius: 10px;
}

/* Conversation Sidebar */
.conversation-sidebar {
  width: 260px;
  min-width: 260px;
  background: var(--surface-ground);
  border-right: 1px solid var(--surface-border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s, min-width 0.2s;
}

.conversation-sidebar.collapsed {
  width: 44px;
  min-width: 44px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}

.sidebar-title {
  font-weight: 600;
  font-size: 0.85rem;
  flex: 1;
}

.sidebar-toggle {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.25rem;
  font-size: 0.9rem;
  border-radius: 4px;
}

.sidebar-toggle:hover {
  background: var(--surface-card-hover);
  color: var(--text-color);
}

.new-chat-btn {
  background: none;
  border: 1px solid var(--surface-border);
  color: var(--text-color);
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  font-size: 0.78rem;
  border-radius: 6px;
}

.new-chat-btn:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.35rem;
}

.conversation-item {
  padding: 0.55rem 0.65rem;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  margin-bottom: 2px;
}

.conversation-item:hover {
  background: var(--surface-card-hover);
}

.conversation-item.active {
  background: rgba(32, 108, 245, 0.12);
  border: 1px solid rgba(32, 108, 245, 0.3);
}

.conv-title {
  font-size: 0.8rem;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 20px;
}

.conv-meta {
  display: flex;
  gap: 0.5rem;
  font-size: 0.7rem;
  color: var(--text-color-secondary);
  margin-top: 0.2rem;
}

.conv-delete {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.15rem;
  font-size: 0.7rem;
  opacity: 0;
  transition: opacity 0.15s;
  border-radius: 4px;
}

.conversation-item:hover .conv-delete {
  opacity: 1;
}

.conv-delete:hover {
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
}

.no-conversations {
  text-align: center;
  padding: 2rem 1rem;
  color: var(--text-color-secondary);
  font-size: 0.8rem;
}

/* Main Chat */
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--surface-card);
  overflow: hidden;
  min-width: 0;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-color-secondary);
}

.empty-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(32, 108, 245, 0.12);
  color: #5a9aff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  margin-bottom: 1rem;
}

.empty-state h3 {
  font-size: 1.1rem;
  margin-bottom: 0.5rem;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.empty-state p {
  font-size: 0.875rem;
  margin-bottom: 1.5rem;
}

.example-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: center;
  max-width: 600px;
}

.example-btn {
  padding: 0.5rem 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 20px;
  background: var(--surface-ground);
  color: var(--text-color);
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.15s;
}

.example-btn:hover {
  border-color: var(--primary-color);
  color: #fff;
  background: rgba(32, 108, 245, 0.12);
  box-shadow: 0 0 10px rgba(32, 108, 245, 0.15);
}

.message {
  display: flex;
  gap: 0.75rem;
  max-width: 85%;
}

.message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 0.85rem;
}

.message.user .message-avatar {
  background: var(--primary-color);
  color: white;
}

.message.assistant .message-avatar {
  background: var(--surface-card-hover);
  color: var(--text-color);
}

.message-content {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.message-text {
  padding: 0.75rem 1rem;
  border-radius: 12px;
  font-size: 0.875rem;
  line-height: 1.55;
  word-break: break-word;
}

.message.user .message-text {
  background: var(--gradient-brand-horizontal);
  color: white;
  border-bottom-right-radius: 4px;
  white-space: pre-wrap;
}

.message.assistant .message-text {
  background: var(--surface-ground);
  color: var(--text-color);
  border-bottom-left-radius: 4px;
}

.message-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.message-time {
  font-size: 0.7rem;
  color: var(--text-color-secondary);
}

.message.user .message-footer {
  justify-content: flex-end;
}

.model-badge {
  font-size: 0.68rem;
  padding: 0.1rem 0.45rem;
  border-radius: 8px;
  background: rgba(32, 108, 245, 0.12);
  color: #5a9aff;
  font-weight: 500;
}

/* Suggestion Chips */
.suggestion-chips {
  padding: 0.5rem 0 0;
  margin-left: 40px;
}

.suggestion-label {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  margin-bottom: 0.4rem;
  font-weight: 500;
}

.suggestion-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.suggestion-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.45rem 0.85rem;
  border: 1px solid rgba(32, 108, 245, 0.35);
  border-radius: 20px;
  background: rgba(32, 108, 245, 0.08);
  color: #5a9aff;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
}

.suggestion-chip i {
  font-size: 0.7rem;
}

.suggestion-chip:hover {
  background: rgba(32, 108, 245, 0.18);
  border-color: var(--primary-color);
  color: #7bb3ff;
  box-shadow: 0 0 12px rgba(32, 108, 245, 0.15);
  transform: translateY(-1px);
}

/* Markdown rendered content */
.markdown-body :deep(p) {
  margin: 0 0 0.6rem;
  line-height: 1.6;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 0.8rem 0 0.4rem;
  font-weight: 600;
  line-height: 1.3;
}

.markdown-body :deep(h1) { font-size: 1.15rem; }
.markdown-body :deep(h2) { font-size: 1.05rem; }
.markdown-body :deep(h3) { font-size: 0.95rem; }
.markdown-body :deep(h4) { font-size: 0.88rem; }

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.4rem 0;
  padding-left: 1.5rem;
}

.markdown-body :deep(li) {
  margin: 0.2rem 0;
  line-height: 1.5;
}

.markdown-body :deep(code) {
  background: rgba(255, 255, 255, 0.08);
  padding: 0.15rem 0.35rem;
  border-radius: 4px;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.82em;
}

.markdown-body :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 0.85rem 1rem;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.5rem 0;
  font-size: 0.8rem;
  line-height: 1.5;
}

.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.5rem 0;
  font-size: 0.82rem;
}

.markdown-body :deep(th) {
  text-align: left;
  padding: 0.45rem 0.65rem;
  background: rgba(255, 255, 255, 0.04);
  border-bottom: 2px solid var(--surface-border);
  font-weight: 600;
  font-size: 0.78rem;
  text-transform: uppercase;
  color: var(--text-color-secondary);
}

.markdown-body :deep(td) {
  padding: 0.4rem 0.65rem;
  border-bottom: 1px solid var(--surface-border);
}

.markdown-body :deep(tr:hover) {
  background: rgba(32, 108, 245, 0.05);
}

.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--primary-color);
  margin: 0.5rem 0;
  padding: 0.3rem 0.75rem;
  color: var(--text-color-secondary);
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--surface-border);
  margin: 0.75rem 0;
}

.markdown-body :deep(strong) {
  font-weight: 600;
}

/* Resource / Account links */
.markdown-body :deep(.resource-link),
.markdown-body :deep(.account-link) {
  color: #5a9aff;
  text-decoration: none;
  border-bottom: 1px dashed rgba(32, 108, 245, 0.4);
  cursor: pointer;
  transition: all 0.15s;
}

.markdown-body :deep(.resource-link:hover),
.markdown-body :deep(.account-link:hover) {
  color: #7bb3ff;
  border-bottom-color: #5a9aff;
  background: rgba(32, 108, 245, 0.12);
  border-radius: 2px;
}

.markdown-body :deep(.account-link) {
  font-family: 'SF Mono', monospace;
  font-size: 0.82em;
}

/* Tool calls panel */
.tool-calls-panel {
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.25);
  border-radius: 12px;
  padding: 0.85rem 1rem;
  margin-bottom: 0.5rem;
}

.tool-calls-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #facc15;
  font-weight: 500;
  margin-bottom: 0.65rem;
  font-size: 0.85rem;
}

.tool-calls-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.tool-call-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.65rem;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  font-size: 0.8rem;
}

.tool-call-item.running {
  color: #5a9aff;
}

.tool-call-item.success {
  color: #4ade80;
}

.tool-call-item.failed {
  color: #f87171;
}

.tool-icon {
  font-size: 0.85rem;
  width: 18px;
  text-align: center;
}

.tool-name {
  font-weight: 500;
}

.tool-duration {
  font-size: 0.72rem;
  padding: 0.1rem 0.35rem;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-color-secondary);
  font-family: 'SF Mono', monospace;
}

.tool-duration.running {
  color: #5a9aff;
  background: rgba(32, 108, 245, 0.12);
}

.tool-summary {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  margin-left: auto;
}

/* Thinking state */
.thinking-state {
  background: rgba(32, 108, 245, 0.08);
  border: 1px solid rgba(32, 108, 245, 0.2);
}

.thinking-content {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}

.thinking-icon {
  color: #5a9aff;
  font-size: 1rem;
}

.thinking-text {
  color: #5a9aff;
  font-weight: 500;
}

.thinking-subtext {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pi-spin {
  animation: spin 1.5s linear infinite;
}

.input-area {
  padding: 0.75rem 1rem 1rem;
  border-top: 1px solid var(--surface-border);
}

.input-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.model-select {
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.78rem;
  background: var(--surface-ground);
  color: var(--text-color);
}

.input-row {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}

.chat-input {
  flex: 1;
  padding: 0.6rem 0.85rem;
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  font-size: 0.875rem;
  resize: none;
  background: var(--surface-ground);
  color: var(--text-color);
  font-family: inherit;
  line-height: 1.5;
  min-height: 40px;
  max-height: 120px;
}

.chat-input:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.chat-input:disabled {
  opacity: 0.6;
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  border: none;
  background: var(--gradient-brand-horizontal);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  box-shadow: 0 0 16px rgba(32, 108, 245, 0.4);
  transform: scale(1.05);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
}

.btn-secondary {
  background: var(--surface-ground);
  color: var(--text-color);
  border: 1px solid var(--surface-border);
}

.btn-sm {
  padding: 0.3rem 0.6rem;
  font-size: 0.78rem;
}

.input-controls-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}

/* Usage button & panel */
.usage-btn-wrapper {
  position: relative;
}

.usage-btn {
  background: none;
  border: 1px solid var(--surface-border);
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.3rem 0.5rem;
  font-size: 0.78rem;
  border-radius: 6px;
  display: flex;
  align-items: center;
  transition: all 0.15s;
}

.usage-btn:hover,
.usage-btn.active {
  border-color: var(--primary-color);
  color: #5a9aff;
  background: rgba(32, 108, 245, 0.08);
}

.usage-panel {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  width: 220px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 0.75rem;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  z-index: 100;
}

.usage-panel-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.4rem;
}

.usage-panel-divider {
  height: 1px;
  background: var(--surface-border);
  margin: 0.4rem 0;
}

.usage-panel-rows {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.usage-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.78rem;
}

.usage-label {
  color: var(--text-color-secondary);
}

.usage-value {
  color: var(--text-color);
  font-weight: 500;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.75rem;
}

.usage-tokens {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  text-align: center;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
</style>

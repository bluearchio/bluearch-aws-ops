<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useContextStore } from '@/stores/context'
import { usePermissionStore } from '@/stores/permissions'
import { useSetupStore } from '@/stores/setup'
import { useMultiAccountStore } from '@/stores/multiAccount'
import ScanProgressPanel from '@/components/ScanProgressPanel.vue'
import NotificationBell from '@/components/NotificationBell.vue'
import ContextSwitcher from '@/components/ContextSwitcher.vue'

const route = useRoute()
const router = useRouter()
const contextStore = useContextStore()
const permissionStore = usePermissionStore()
const setupStore = useSetupStore()
const multiAccountStore = useMultiAccountStore()
let warmupStarted = false

async function loadContextIfNeeded() {
  if (contextStore.current || contextStore.all.length > 0 || contextStore.loading) return
  await Promise.all([
    contextStore.loadCurrent({ background: true }),
    contextStore.loadAll({ background: true }),
  ])
}

function warmProductStores() {
  if (warmupStarted) return
  warmupStarted = true
  window.setTimeout(async () => {
    await Promise.all([
      permissionStore.load({ background: true }),
      setupStore.runValidation({ background: true }),
      setupStore.loadInfrastructure({ background: true }),
      multiAccountStore.load({ background: true }),
      multiAccountStore.loadTemplateMeta({ background: true }),
    ])
  }, 1500)
}

onMounted(() => {
  void loadContextIfNeeded()
  warmProductStores()
})

interface NavChild {
  path: string
  label: string
}

interface NavItem {
  path: string
  label: string
  icon: string
  children?: NavChild[]
}

const navItems: NavItem[] = [
  { path: '/', label: 'Dashboard', icon: 'pi pi-th-large' },
  {
    path: '/resources',
    label: 'Resources',
    icon: 'pi pi-server',
    children: [
      { path: '/resources', label: 'Resource List' },
      { path: '/resources/map', label: 'Resource Map' },
    ],
  },
  { path: '/recommendations', label: 'Recommendations', icon: 'pi pi-list' },
  { path: '/logs', label: 'Log Analysis', icon: 'pi pi-file' },
  { path: '/scans', label: 'Scans', icon: 'pi pi-sync' },
  { path: '/alarms', label: 'Alarms', icon: 'pi pi-bell' },
  { path: '/optin-hub', label: 'Opt-In Hub', icon: 'pi pi-check-square' },
  { path: '/chat', label: 'AI Chat', icon: 'pi pi-comment' },
  { path: '/audit', label: 'Audit Log', icon: 'pi pi-clock' },
  {
    path: '/setup',
    label: 'Setup',
    icon: 'pi pi-cog',
    children: [
      { path: '/setup', label: 'Overview' },
      { path: '/setup/assume-role', label: 'Assume Role' },
      { path: '/setup/multi-account', label: 'Multi-Account' },
    ],
  },
]

const expandedSections = ref<Set<string>>(new Set())

function toggleSection(path: string) {
  if (expandedSections.value.has(path)) {
    expandedSections.value.delete(path)
  } else {
    expandedSections.value.add(path)
  }
}

function isActive(item: NavItem): boolean {
  if (item.children) {
    return item.children.some((c) => route.path === c.path)
  }
  return route.path === item.path
}

function isChildActive(child: NavChild): boolean {
  return route.path === child.path
}

function isExpanded(item: NavItem): boolean {
  return expandedSections.value.has(item.path) || isActive(item)
}

function handleNavClick(item: NavItem) {
  if (item.children) {
    toggleSection(item.path)
  } else {
    router.push(item.path)
  }
}

</script>

<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-glow"></div>
      <div class="sidebar-header">
        <div class="logo-section">
          <svg class="logo-icon" width="28" height="28" viewBox="0 0 100 100" fill="none">
            <circle cx="50" cy="50" r="45" stroke="#206CF5" stroke-width="5" fill="none"/>
            <circle cx="50" cy="50" r="25" stroke="#19D4D4" stroke-width="3" fill="none"/>
            <polygon points="50,20 70,65 30,65" stroke="#206CF5" stroke-width="4" fill="none"/>
          </svg>
          <div>
            <div class="logo-text text-gradient">BLUEARCH</div>
            <div class="logo-sub">Dashboard</div>
          </div>
        </div>
      </div>

      <nav class="sidebar-nav">
        <template v-for="item in navItems" :key="item.path">
          <!-- Items with children: expandable section -->
          <template v-if="item.children">
            <button
              class="nav-item"
              :class="{ active: isActive(item) }"
              @click="handleNavClick(item)"
            >
              <i :class="item.icon"></i>
              <span>{{ item.label }}</span>
              <i
                class="expand-icon pi"
                :class="isExpanded(item) ? 'pi-chevron-down' : 'pi-chevron-right'"
              ></i>
            </button>
            <div v-if="isExpanded(item)" class="nav-children">
              <router-link
                v-for="child in item.children"
                :key="child.path"
                :to="child.path"
                class="nav-child"
                :class="{ active: isChildActive(child) }"
              >
                {{ child.label }}
              </router-link>
            </div>
          </template>

          <!-- Simple nav items -->
          <router-link
            v-else
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
          >
            <i :class="item.icon"></i>
            <span>{{ item.label }}</span>
          </router-link>
        </template>
      </nav>

      <div class="sidebar-footer">
        <a href="/docs" target="_blank" class="api-docs-link">
          <i class="pi pi-file"></i> API Docs
        </a>
      </div>
    </aside>

    <!-- Main -->
    <div class="app-main">
      <header class="topbar">
        <div class="topbar-glow"></div>
        <div class="page-title text-gradient">
          {{ route.meta?.title || route.name || 'Dashboard' }}
        </div>
        <div class="topbar-right">
          <ContextSwitcher class="topbar-context" />
          <NotificationBell />
          <div class="health-indicator healthy">
            <span class="health-dot"></span>
            <span>Connected</span>
          </div>
        </div>
      </header>

      <main class="app-content">
        <router-view />
      </main>
    </div>

    <ScanProgressPanel />
  </div>
</template>

<style>
.app-layout {
  display: flex;
  min-height: 100vh;
}

/* Sidebar */
.sidebar {
  width: var(--sidebar-width);
  background: var(--surface-ground);
  border-right: 1px solid var(--surface-border);
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  z-index: 100;
}

.sidebar-glow {
  height: 2px;
  background: var(--gradient-border);
  box-shadow: 0 2px 12px rgba(32, 108, 245, 0.3);
}

.sidebar-header {
  padding: 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo-icon {
  flex-shrink: 0;
}

.logo-text {
  font-family: var(--font-heading);
  font-size: 0.95rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.logo-sub {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  margin-top: 1px;
}

.sidebar-nav {
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  color: var(--text-color-secondary);
  text-decoration: none;
  font-size: 0.875rem;
  transition: all 0.2s ease;
  border: none;
  border-left: 2px solid transparent;
  background: none;
  cursor: pointer;
  width: 100%;
  text-align: left;
  font-family: var(--font-body);
}

.nav-item:hover {
  background: rgba(32, 108, 245, 0.08);
  color: var(--text-color);
}

.nav-item.active {
  background: rgba(32, 108, 245, 0.15);
  color: #fff;
  border-image: var(--gradient-border) 1;
}

.nav-item.active i:not(.expand-icon) {
  color: var(--accent-cyan);
}

.nav-item.active > span {
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.nav-item i {
  font-size: 1rem;
  width: 1.25rem;
  text-align: center;
}

.expand-icon {
  margin-left: auto;
  font-size: 0.7rem !important;
  width: auto !important;
  color: var(--text-color-secondary) !important;
  -webkit-text-fill-color: initial !important;
  background: none !important;
}

.nav-children {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-left: 2.85rem;
}

.nav-child {
  display: block;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  color: var(--text-color-secondary);
  text-decoration: none;
  font-size: 0.8rem;
  transition: all 0.2s ease;
}

.nav-child:hover {
  color: var(--text-color);
  background: rgba(32, 108, 245, 0.06);
}

.nav-child.active {
  color: var(--accent-cyan);
  background: rgba(25, 212, 212, 0.08);
}

.sidebar-footer {
  padding: 0.75rem;
  border-top: 1px solid var(--surface-border);
}

.tier-badge {
  padding: 2px 8px;
  margin: 4px 8px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--primary-color);
  border: 1px solid var(--primary-color);
  border-radius: 4px;
  text-align: center;
}

/* Topbar */
.app-main {
  margin-left: var(--sidebar-width);
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.topbar {
  position: fixed;
  top: 0;
  left: var(--sidebar-width);
  right: 0;
  height: var(--topbar-height);
  background: var(--surface-card);
  border-bottom: 1px solid var(--surface-border);
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1.5rem;
}

.topbar-glow {
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--gradient-border);
  box-shadow: 0 1px 8px rgba(32, 108, 245, 0.15);
}

.page-title {
  font-size: 1rem;
  font-weight: 400;
  letter-spacing: 0.04em;
  text-transform: capitalize;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 1rem;
  min-width: 0;
}

.topbar-context {
  flex: 0 1 260px;
  max-width: min(260px, 28vw);
}

.topbar-context .context-trigger {
  max-width: 100%;
}

.topbar-context .context-label {
  min-width: 0;
}

@media (max-width: 1100px) {
  .topbar {
    padding: 0 1rem;
  }

  .topbar-right {
    gap: 0.5rem;
  }

  .topbar-context {
    flex-basis: 180px;
    max-width: 180px;
  }

  .topbar-context .context-label {
    max-width: 120px;
  }

  .health-indicator span,
  .topbar-user {
    display: none;
  }
}

@media (max-width: 760px) {
  .topbar-context {
    flex-basis: 150px;
    max-width: 150px;
  }

  .topbar-context .context-label {
    max-width: 90px;
  }
}

.notification-menu {
  position: relative;
}

.notification-bell {
  position: relative;
  width: 34px;
  height: 34px;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: rgba(32, 108, 245, 0.08);
  color: var(--text-color-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}

.notification-bell:hover {
  color: var(--accent-cyan);
  border-color: rgba(25, 212, 212, 0.4);
  background: rgba(25, 212, 212, 0.1);
}

.notification-count {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  border-radius: 999px;
  padding: 0 4px;
  background: #facc15;
  color: #0a0a0a;
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 16px;
}

.notification-popover {
  position: absolute;
  top: 42px;
  right: 0;
  width: min(420px, calc(100vw - 2rem));
  max-height: 460px;
  overflow: auto;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.45);
  z-index: 200;
}

.notification-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.9rem 1rem;
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color);
  font-weight: 700;
}

.notification-refresh {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
}

.notification-list {
  display: flex;
  flex-direction: column;
}

.notification-item {
  padding: 0.9rem 1rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
}

.notification-item:last-child {
  border-bottom: 0;
}

.notification-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.35rem;
}

.notification-title {
  color: var(--text-color);
  font-weight: 700;
  font-size: 0.84rem;
}

.notification-severity {
  color: #facc15;
  font-size: 0.66rem;
  font-weight: 700;
  text-transform: uppercase;
}

.notification-message {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  line-height: 1.45;
  white-space: pre-wrap;
}

.notification-time {
  color: var(--text-color-secondary);
  font-size: 0.68rem;
  margin-top: 0.45rem;
}

.notification-action {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.65rem;
  color: var(--accent-cyan);
  font-size: 0.76rem;
  font-weight: 700;
  text-decoration: none;
}

.notification-action:hover {
  color: var(--primary-color);
}

.notification-empty {
  padding: 1rem;
  color: var(--text-color-secondary);
  font-size: 0.82rem;
}

.health-indicator {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.health-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--color-danger);
}

.healthy .health-dot {
  background: var(--color-success);
}

/* Content */
.app-content {
  padding: 1.5rem;
  margin-top: var(--topbar-height);
  flex: 1;
}

/* API Docs link in sidebar footer */
.api-docs-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.85rem;
  margin-bottom: 0.5rem;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  text-decoration: none;
  border-radius: 6px;
  transition: all 0.15s;
}
.api-docs-link:hover {
  background: rgba(32, 108, 245, 0.06);
  color: var(--text-color);
}

/* Role badge in topbar */
.role-badge {
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: capitalize;
  font-family: var(--font-mono);
}
.role-admin { background: rgba(32, 108, 245, 0.2); color: #5a9aff; }
.role-operator { background: rgba(25, 212, 212, 0.15); color: #19D4D4; }
.role-viewer { background: rgba(160, 160, 160, 0.15); color: #a0a0a0; }
.role-editor { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
</style>

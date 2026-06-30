<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <svg class="logo-icon" width="28" height="28" viewBox="0 0 100 100" fill="none">
          <circle cx="50" cy="50" r="45" stroke="#206CF5" stroke-width="5" fill="none"/>
          <circle cx="50" cy="50" r="25" stroke="#19D4D4" stroke-width="3" fill="none"/>
          <polygon points="50,20 70,65 30,65" stroke="#206CF5" stroke-width="4" fill="none"/>
        </svg>
        <div>
          <div class="logo-text">BLUEARCH</div>
          <div class="logo-sub">Dashboard</div>
        </div>
      </div>
    </div>

    <nav class="sidebar-nav">
      <template v-for="item in navItems" :key="item.path">
        <!-- Item with children -->
        <template v-if="item.children">
          <router-link
            :to="item.path"
            class="nav-item"
            :class="{ active: isExactActive(item.path) }"
          >
            <i :class="item.icon"></i>
            <span>{{ item.label }}</span>
            <i class="pi sub-chevron" :class="isGroupOpen(item.path) ? 'pi-chevron-down' : 'pi-chevron-right'"></i>
          </router-link>
          <div v-if="isGroupOpen(item.path)" class="sub-nav">
            <router-link
              v-for="child in item.children"
              :key="child.path"
              :to="child.path"
              class="nav-item sub-item"
              :class="{ active: isActive(child.path) }"
            >
              <span>{{ child.label }}</span>
            </router-link>
          </div>
        </template>
        <!-- Simple item -->
        <router-link
          v-else
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
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
      <div class="tier-badge">{{ tier }}</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'

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

defineProps<{
  navItems: NavItem[]
  tier?: string
}>()

const route = useRoute()

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function isExactActive(path: string): boolean {
  return route.path === path
}

function isGroupOpen(parentPath: string): boolean {
  return route.path.startsWith(parentPath)
}
</script>

<style scoped>
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--surface-ground);
  border-right: 1px solid var(--surface-border);
  color: var(--text-color-secondary);
  display: flex;
  flex-direction: column;
  z-index: 100;
}

/* Gradient glow line at top */
.sidebar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--gradient-border);
  box-shadow: 0px 2px 12px rgba(32, 108, 245, 0.4);
}

.sidebar-header {
  padding: 1.25rem 1rem;
  border-bottom: 1px solid var(--surface-border);
}

.logo {
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
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.logo-sub {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  margin-top: 1px;
}

.sidebar-nav {
  flex: 1;
  padding: 0.75rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
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
  border-left: 2px solid transparent;
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

.nav-item i {
  font-size: 1rem;
  width: 20px;
  text-align: center;
}

.nav-item.active i {
  color: var(--accent-cyan);
}

.nav-item.active span {
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.sub-chevron {
  margin-left: auto;
  font-size: 0.65rem !important;
  width: auto !important;
  opacity: 0.5;
}

.sub-nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-left: 0.5rem;
}

.sub-item {
  padding: 0.5rem 0.85rem 0.5rem 2.5rem;
  font-size: 0.82rem;
}

.sidebar-footer {
  padding: 0.75rem 0.5rem;
  border-top: 1px solid var(--surface-border);
}

.api-docs-link {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  transition: all 0.15s;
}

.api-docs-link:hover {
  background: rgba(32, 108, 245, 0.06);
  color: var(--text-color);
}

.tier-badge {
  padding: 2px 8px;
  margin: 4px 16px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--primary-color);
  border: 1px solid var(--primary-color);
  border-radius: 4px;
  text-align: center;
}
</style>

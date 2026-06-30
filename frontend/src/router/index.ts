import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { title: 'Dashboard' },
    },
    {
      path: '/resources',
      name: 'resources',
      component: () => import('@/views/ResourcesView.vue'),
      meta: { title: 'Resources' },
    },
    {
      path: '/resources/map',
      name: 'resource-map',
      component: () => import('@/views/ResourceMapView.vue'),
      meta: { title: 'Resource Map' },
    },
    {
      path: '/resources/:id',
      name: 'resource-detail',
      component: () => import('@/views/ResourceDetailView.vue'),
      meta: { title: 'Resource Detail' },
    },
    {
      path: '/recommendations',
      name: 'recommendations',
      component: () => import('@/views/RecommendationsView.vue'),
      meta: { title: 'Recommendations' },
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('@/views/LogAnalysisView.vue'),
      meta: { title: 'Log Analysis' },
    },
    {
      path: '/scans',
      name: 'scans',
      component: () => import('@/views/ScansView.vue'),
      meta: { title: 'Scans' },
    },
    {
      path: '/alarms',
      name: 'alarms',
      component: () => import('@/views/AlarmsView.vue'),
      meta: { title: 'Alarms' },
    },
    {
      path: '/optin-hub',
      name: 'optin-hub',
      component: () => import('@/views/OptinHubView.vue'),
      meta: { title: 'Opt-In Hub' },
    },
    {
      path: '/accounts',
      redirect: '/setup/multi-account',
    },
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/views/SetupView.vue'),
      meta: { title: 'Setup' },
    },
    {
      path: '/setup/assume-role',
      name: 'assume-role',
      component: () => import('@/views/AssumeRoleView.vue'),
      meta: { title: 'Assume Role' },
    },
    {
      path: '/setup/multi-account',
      name: 'multi-account',
      component: () => import('@/views/MultiAccountView.vue'),
      meta: { title: 'Multi-Account' },
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { title: 'AI Chat' },
    },
    {
      path: '/audit',
      name: 'audit',
      component: () => import('@/views/AuditView.vue'),
      meta: { title: 'Audit Log' },
    },
  ],
})

router.beforeEach(() => {
  return true
})

export default router

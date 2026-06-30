import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

type Tier = 'FREE' | 'PRO' | 'ENTERPRISE'

export const useLicenseStore = defineStore('license', () => {
  const tier = ref<Tier>('ENTERPRISE')
  const info = ref({
    tier: 'enterprise',
    customer: 'local',
    features: {} as Record<string, boolean>,
  })
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isFree = computed(() => false)
  const isPro = computed(() => true)
  const isEnterprise = computed(() => true)

  function isFeatureAllowed(_feature: string): boolean {
    return true
  }

  async function load(_options?: { background?: boolean }) {
    return undefined
  }

  async function activate(_key: string) {
    return undefined
  }

  async function requestUpgrade(_email: string, _accountId: string) {
    return undefined
  }

  return {
    tier,
    info,
    loading,
    error,
    isFree,
    isPro,
    isEnterprise,
    isFeatureAllowed,
    load,
    activate,
    requestUpgrade,
  }
})

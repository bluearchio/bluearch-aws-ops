import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { createCachedLoader, type CachedLoadOptions } from '@/stores/cache'
import type { IamPolicy, InfrastructureStatusResponse } from '@/types/api'

interface SetupCheckItem {
  name: string
  status: 'ok' | 'warning' | 'error'
  message: string
  details?: Record<string, unknown>
}

interface SetupValidateResponse {
  overall: 'healthy' | 'degraded' | 'unhealthy'
  checks: SetupCheckItem[]
}

export const useSetupStore = defineStore('setup', () => {
  const result = ref<SetupValidateResponse | null>(null)
  const validation = result
  const loading = ref(false)

  const infraData = ref<InfrastructureStatusResponse | null>(null)
  const infraLoading = ref(false)

  const iamPolicy = ref<IamPolicy | null>(null)
  const iamPolicyLoading = ref(false)
  const iamLoading = iamPolicyLoading
  const iamPolicyError = ref<string | null>(null)
  const error = ref<string | null>(null)

  const validationLoader = createCachedLoader<SetupValidateResponse>({
    fetcher: api.setupValidate,
    assign: (value) => { result.value = value },
    hasData: () => result.value !== null,
    setLoading: (value) => { loading.value = value },
    setError: (message) => { error.value = message },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to validate setup',
  })

  const infrastructureLoader = createCachedLoader<InfrastructureStatusResponse>({
    fetcher: api.infrastructureStatus,
    assign: (value) => { infraData.value = value },
    hasData: () => infraData.value !== null,
    setLoading: (value) => { infraLoading.value = value },
    setError: (message) => { error.value = message },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load infrastructure status',
  })

  const iamPolicyLoader = createCachedLoader<IamPolicy>({
    fetcher: api.iamPolicy,
    assign: (value) => { iamPolicy.value = value },
    hasData: () => iamPolicy.value !== null,
    setLoading: (value) => { iamPolicyLoading.value = value },
    setError: (message) => {
      iamPolicyError.value = message
      if (message) error.value = message
    },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load IAM policy',
    staleMs: 5 * 60_000,
  })

  function runValidation(options?: CachedLoadOptions) {
    return validationLoader.load(options).catch(() => null)
  }

  function loadInfrastructure(options?: CachedLoadOptions) {
    return infrastructureLoader.load(options).catch(() => null)
  }

  function loadIamPolicy(options?: CachedLoadOptions) {
    return iamPolicyLoader.load(options).catch(() => null)
  }

  async function refreshAll() {
    await Promise.all([
      validationLoader.refresh().catch(() => null),
      infrastructureLoader.refresh().catch(() => null),
    ])
  }

  return {
    result,
    validation,
    iamPolicy,
    loading,
    infraData,
    infraLoading,
    iamPolicyLoading,
    iamLoading,
    iamPolicyError,
    error,
    runValidation,
    loadInfrastructure,
    loadIamPolicy,
    refreshAll,
  }
})

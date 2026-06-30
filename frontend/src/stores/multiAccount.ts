import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { createCachedLoader, type CachedLoadOptions } from '@/stores/cache'
import type {
  AccountRecord,
  AccountValidationResponse,
  StackSetStatusResponse,
  TemplateMetadata,
} from '@/types/api'

interface MultiAccountOverview {
  accounts: AccountRecord[]
  status: StackSetStatusResponse
  validation: AccountValidationResponse
}

const DEFAULT_VALIDATION: AccountValidationResponse = {
  is_management_account: false,
  is_delegated_admin: false,
  can_deploy: true,
}

const TEMPLATE_NAMES = ['cross_account_stack.yaml', 'single_account_role.yaml']

export const useMultiAccountStore = defineStore('multiAccount', () => {
  const stackSetStatus = ref<StackSetStatusResponse | null>(null)
  const accounts = ref<AccountRecord[]>([])
  const statusLoading = ref(false)
  const statusError = ref<string | null>(null)
  const validation = ref<AccountValidationResponse | null>(null)
  const templateMeta = reactive<Record<string, TemplateMetadata>>({})

  const overviewLoader = createCachedLoader<MultiAccountOverview>({
    fetcher: async () => {
      const [validationResponse, statusResponse, accountResponse] = await Promise.all([
        loadValidationSafe(),
        api.multiAccountStatus(),
        api.listAccounts(),
      ])
      return {
        validation: validationResponse,
        status: statusResponse,
        accounts: Array.isArray(accountResponse) ? accountResponse : [],
      }
    },
    assign: (value) => {
      validation.value = value.validation
      stackSetStatus.value = value.status
      accounts.value = value.accounts
    },
    hasData: () => stackSetStatus.value !== null || accounts.value.length > 0 || validation.value !== null,
    setLoading: (value) => { statusLoading.value = value },
    setError: (message) => { statusError.value = message },
    getErrorMessage: (e) => e instanceof Error ? e.message : 'Failed to load status',
  })

  const templateLoader = createCachedLoader<TemplateMetadata[]>({
    fetcher: api.listTemplates,
    assign: (list) => {
      for (const template of list) {
        if (TEMPLATE_NAMES.includes(template.name)) {
          templateMeta[template.name] = template
        }
      }
    },
    hasData: () => Object.keys(templateMeta).length > 0,
    staleMs: 5 * 60_000,
  })

  function load(options?: CachedLoadOptions) {
    return overviewLoader.load(options).catch(() => null)
  }

  function refresh() {
    return overviewLoader.refresh().catch(() => null)
  }

  function loadTemplateMeta(options?: CachedLoadOptions) {
    return templateLoader.load(options).catch(() => null)
  }

  function refreshTemplateMeta() {
    return templateLoader.refresh().catch(() => null)
  }

  async function loadValidationSafe(): Promise<AccountValidationResponse> {
    try {
      return await api.validateAccount()
    } catch {
      return { ...DEFAULT_VALIDATION }
    }
  }

  return {
    accounts,
    stackSetStatus,
    statusError,
    statusLoading,
    templateMeta,
    templateNames: TEMPLATE_NAMES,
    validation,
    load,
    refresh,
    loadTemplateMeta,
    refreshTemplateMeta,
  }
})

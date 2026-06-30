export interface CachedLoadOptions {
  background?: boolean
  force?: boolean
  staleMs?: number
}

interface CachedLoaderConfig<T> {
  assign: (value: T) => void
  fetcher: () => Promise<T>
  hasData: () => boolean
  setError?: (message: string | null) => void
  setLoading?: (loading: boolean) => void
  getErrorMessage?: (error: unknown) => string
  staleMs?: number
}

export function createCachedLoader<T>(config: CachedLoaderConfig<T>) {
  let inFlight: Promise<T> | null = null
  let loadedAt = 0

  async function load(options: CachedLoadOptions = {}): Promise<T | null> {
    const hasCached = loadedAt > 0 || config.hasData()
    const staleMs = options.staleMs ?? config.staleMs ?? 30_000
    const isFresh = hasCached && !options.force && Date.now() - loadedAt < staleMs

    if (isFresh) return null
    if (inFlight) return inFlight

    const blocking = options.background ? !hasCached : true
    if (blocking) config.setLoading?.(true)
    config.setError?.(null)

    inFlight = config.fetcher()
      .then((value) => {
        config.assign(value)
        loadedAt = Date.now()
        return value
      })
      .catch((error) => {
        config.setError?.(config.getErrorMessage?.(error) ?? defaultErrorMessage(error))
        throw error
      })
      .finally(() => {
        inFlight = null
        if (blocking) config.setLoading?.(false)
      })

    return inFlight
  }

  function refresh() {
    return load({ force: true })
  }

  function invalidate() {
    loadedAt = 0
  }

  return { load, refresh, invalidate }
}

function defaultErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Failed to load data'
}

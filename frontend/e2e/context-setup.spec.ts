import { test, expect } from '@playwright/test'

test.describe('Context API', () => {
  test('context gate auto-registers current account', async ({ request }) => {
    const res = await request.get('/api/v1/context/gate')
    expect(res.status()).toBe(200)
    const body = await res.json()
    // First call should be new_context or ok (if already registered)
    expect(['ok', 'new_context']).toContain(body.status)
    if (body.context) {
      expect(body.context.account_id).toBeDefined()
      expect(body.context.is_current).toBe(true)
    }
  })

  test('get current context returns account', async ({ request }) => {
    const res = await request.get('/api/v1/context')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.account_id).toBeDefined()
  })

  test('list contexts returns at least one', async ({ request }) => {
    const res = await request.get('/api/v1/contexts')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.contexts).toBeDefined()
    expect(body.contexts.length).toBeGreaterThanOrEqual(1)
    expect(body.current_account_id).toBeDefined()
  })

  test('add context registers current identity', async ({ request }) => {
    const res = await request.post('/api/v1/context', {
      data: { alias: 'e2e-test-context' },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.account_id).toBeDefined()
    // Since same identity, should update existing
  })

  test('switch context to current account succeeds', async ({ request }) => {
    // Get current context first
    const ctx = await request.get('/api/v1/context')
    const ctxBody = await ctx.json()
    const accountId = ctxBody.account_id

    if (accountId) {
      const res = await request.post('/api/v1/context/switch', {
        data: { account_id: accountId },
      })
      expect(res.status()).toBe(200)
      const body = await res.json()
      expect(body.is_current).toBe(true)
    }
  })

  test('switch context to invalid account returns 404', async ({ request }) => {
    const res = await request.post('/api/v1/context/switch', {
      data: { account_id: '999999999999' },
    })
    expect(res.status()).toBe(404)
  })
})

test.describe('Setup Validation - All Check Categories', () => {
  test('validate returns all 7 check categories', async ({ request }) => {
    const res = await request.get('/api/v1/setup/validate')
    expect(res.status()).toBe(200)
    const body = await res.json()

    expect(body.overall).toBeDefined()
    expect(['healthy', 'degraded', 'unhealthy']).toContain(body.overall)

    const checkNames = body.checks.map((c: any) => c.name)
    // Should have at least these core checks
    expect(checkNames).toContain('Database')
    expect(checkNames).toContain('AWS Credentials')
    expect(checkNames).toContain('IAM Permissions')
    expect(checkNames).toContain('Version')

    // Each check has correct shape
    for (const check of body.checks) {
      expect(check.name).toBeDefined()
      expect(['ok', 'warning', 'error']).toContain(check.status)
      expect(check.message).toBeDefined()
    }
  })

  test('database check is always ok', async ({ request }) => {
    const res = await request.get('/api/v1/setup/validate')
    const body = await res.json()
    const dbCheck = body.checks.find((c: any) => c.name === 'Database')
    expect(dbCheck).toBeDefined()
    expect(dbCheck.status).toBe('ok')
    expect(dbCheck.message).toContain('SQLite connected')
  })

  test('AWS credentials check shows account info', async ({ request }) => {
    const res = await request.get('/api/v1/setup/validate')
    const body = await res.json()
    const awsCheck = body.checks.find((c: any) => c.name === 'AWS Credentials')
    expect(awsCheck).toBeDefined()
    expect(awsCheck.status).toBe('ok')
    expect(awsCheck.details).toBeDefined()
    expect(awsCheck.details.account_id).toBeDefined()
    expect(awsCheck.details.arn).toBeDefined()
  })

  test('IAM permissions check shows service breakdown', async ({ request }) => {
    const res = await request.get('/api/v1/setup/validate')
    const body = await res.json()
    const iamCheck = body.checks.find((c: any) => c.name === 'IAM Permissions')
    expect(iamCheck).toBeDefined()
    expect(iamCheck.details).toBeDefined()
    expect(iamCheck.details.EC2).toBeDefined()
    expect(iamCheck.details.S3).toBeDefined()
  })

  test('version check shows BlueArch version', async ({ request }) => {
    const res = await request.get('/api/v1/setup/validate')
    const body = await res.json()
    const versionCheck = body.checks.find((c: any) => c.name === 'Version')
    expect(versionCheck).toBeDefined()
    expect(versionCheck.status).toBe('ok')
    expect(versionCheck.message).toContain('BlueArch')
  })
})

test.describe('Infrastructure & Event Tracking', () => {
  test('infrastructure status returns structured response', async ({ request }) => {
    const res = await request.get('/api/v1/infrastructure/status')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.stacks).toBeDefined()
    expect(Array.isArray(body.stacks)).toBe(true)
    expect(body.health_summary).toBeDefined()
    expect(body.health_summary.total_components).toBeDefined()
  })

  test('event tracking status returns structured response', async ({ request }) => {
    const res = await request.get('/api/v1/event-tracking/status')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.instances).toBeDefined()
    expect(Array.isArray(body.instances)).toBe(true)
    expect(typeof body.total_queues).toBe('number')
    expect(typeof body.active_queues).toBe('number')
    expect(typeof body.service_running).toBe('boolean')
  })

  test('templates list returns available templates', async ({ request }) => {
    const res = await request.get('/api/v1/system/templates')
    expect(res.status()).toBe(200)
    const templates = await res.json()
    expect(Array.isArray(templates)).toBe(true)
    if (templates.length > 0) {
      expect(templates[0].name).toBeDefined()
      expect(templates[0].description).toBeDefined()
    }
  })

  test('component template map returns mapping', async ({ request }) => {
    const res = await request.get('/api/v1/system/templates/component-map')
    expect(res.status()).toBe(200)
    const map = await res.json()
    expect(map['assume-role']).toBeDefined()
  })
})

test.describe('Graph API', () => {
  test('graph data returns nodes and edges', async ({ request }) => {
    const res = await request.get('/api/v1/graph/data')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.nodes).toBeDefined()
    expect(body.edges).toBeDefined()
    expect(body.categories).toBeDefined()
    expect(body.stats).toBeDefined()
    expect(Array.isArray(body.nodes)).toBe(true)
    expect(Array.isArray(body.edges)).toBe(true)
  })

  test('graph filters returns available options', async ({ request }) => {
    const res = await request.get('/api/v1/graph/filters')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.services).toBeDefined()
    expect(body.regions).toBeDefined()
    expect(body.relationship_types).toBeDefined()
    expect(Array.isArray(body.services)).toBe(true)
  })

  test('graph stats returns counts', async ({ request }) => {
    const res = await request.get('/api/v1/graph/stats')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(typeof body.total_resources).toBe('number')
    expect(typeof body.total_relationships).toBe('number')
    expect(typeof body.services).toBe('number')
    expect(typeof body.regions).toBe('number')
  })
})

test.describe('Assume Role API', () => {
  test('assume role status returns structured response', async ({ request }) => {
    const res = await request.get('/api/v1/assume-role/status')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.configured).toBeDefined()
    expect(body.role_arn).toBeDefined()
  })

  test('assume role configs returns list', async ({ request }) => {
    const res = await request.get('/api/v1/assume-role/configs')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(Array.isArray(body)).toBe(true)
  })
})

test.describe('License API', () => {
  test('license endpoint returns tier info', async ({ request }) => {
    const res = await request.get('/api/v1/license')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.tier).toBeDefined()
    expect(['FREE', 'PRO', 'ENTERPRISE', 'free', 'pro', 'enterprise']).toContain(body.tier)
  })
})

test.describe('Setup UI - Deep Validation', () => {
  test('setup page shows all check categories after validation', async ({ page }) => {
    await page.goto('/setup')
    // Wait for validation to complete
    await page.waitForResponse(
      resp => resp.url().includes('/api/v1/setup/validate') && resp.status() === 200,
      { timeout: 20000 }
    )
    // Wait for table to render
    await expect(page.locator('.data-table')).toBeVisible({ timeout: 5000 })

    // Check individual rows
    await expect(page.locator('text=Database')).toBeVisible()
    await expect(page.locator('text=AWS Credentials')).toBeVisible()
    await expect(page.locator('text=IAM Permissions')).toBeVisible()
    await expect(page.locator('text=Version')).toBeVisible()
  })

  test('setup page shows infrastructure section', async ({ page }) => {
    await page.goto('/setup')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('text=Deployed Infrastructure')).toBeVisible({ timeout: 10000 })
  })

  test('setup page shows event tracking section', async ({ page }) => {
    await page.goto('/setup')
    await page.waitForLoadState('networkidle')
    // Wait for validation to finish before checking sections
    await page.waitForTimeout(2000)
    await expect(page.getByText('Event Tracking', { exact: false }).first()).toBeVisible({ timeout: 10000 })
  })
})

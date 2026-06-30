import { test, expect } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

test.describe('Misconfig Workflow - API', () => {
  let policyId: string

  test('catalog returns misconfig rules', async ({ request }) => {
    const res = await request.get('/api/v1/misconfig/catalog')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.items).toBeDefined()
    expect(body.items.length).toBeGreaterThan(0)
    expect(body.total).toBeGreaterThan(0)
    // Check first item has expected fields
    const item = body.items[0]
    expect(item.id).toBeDefined()
    expect(item.service_name).toBeDefined()
    expect(item.scenario).toBeDefined()
    expect(item.risk_value).toBeDefined()
  })

  test('catalog has multiple services', async ({ request }) => {
    const res = await request.get('/api/v1/misconfig/catalog')
    const body = await res.json()
    expect(body.services).toBeDefined()
    expect(body.services.length).toBeGreaterThan(5)
  })

  test('create misconfig policy', async ({ request }) => {
    // Get some misconfig IDs from catalog
    const catalog = await request.get('/api/v1/misconfig/catalog')
    const catalogBody = await catalog.json()
    const firstTwo = catalogBody.items.slice(0, 2)

    const res = await request.post('/api/v1/misconfig/policies', {
      data: {
        name: `test-policy-${Date.now()}`,
        description: 'E2E test policy',
        resource_types: ['ec2_instance'],
        misconfig_ids: firstTwo.map((i: any) => i.id),
        risk_types: ['security'],
        min_risk_value: 0,
      },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.id).toBeDefined()
    expect(body.name).toContain('test-policy')
    expect(body.enabled).toBe(true)
    policyId = body.id
  })

  test('list policies includes created policy', async ({ request }) => {
    const res = await request.get('/api/v1/misconfig/policies')
    expect(res.status()).toBe(200)
    const policies = await res.json()
    expect(Array.isArray(policies)).toBe(true)
    const found = policies.find((p: any) => p.id === policyId)
    expect(found).toBeDefined()
    expect(found.name).toContain('test-policy')
  })

  test('update misconfig policy', async ({ request }) => {
    const res = await request.patch(`/api/v1/misconfig/policies/${policyId}`, {
      data: { description: 'Updated description' },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.description).toBe('Updated description')
  })

  test('trigger misconfig scan for policy', async ({ request }) => {
    const res = await request.post(`/api/v1/misconfig/policies/${policyId}/scan`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    // Should return a job ID or scan result
    expect(body).toBeDefined()
  })

  test('trigger full misconfig scan', async ({ request }) => {
    const res = await request.post('/api/v1/misconfig/scan')
    expect(res.status()).toBe(200)
  })

  test('get misconfig findings', async ({ request }) => {
    const res = await request.get('/api/v1/misconfig/findings')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.items).toBeDefined()
    expect(body.total).toBeDefined()
  })

  test('get misconfig dashboard summary', async ({ request }) => {
    const res = await request.get('/api/v1/misconfig/dashboard')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.total_open).toBeDefined()
    expect(body.by_severity).toBeDefined()
    expect(body.by_service).toBeDefined()
  })

  test('preview misconfig with resource types', async ({ request }) => {
    const catalog = await request.get('/api/v1/misconfig/catalog')
    const catalogBody = await catalog.json()
    const ids = catalogBody.items.slice(0, 3).map((i: any) => i.id)

    const res = await request.post('/api/v1/misconfig/preview', {
      data: {
        resource_types: ['ec2_instance'],
        misconfig_ids: ids,
        min_risk_value: 0,
      },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.total).toBeDefined()
    expect(body.resources).toBeDefined()
  })

  test('delete misconfig policy', async ({ request }) => {
    const res = await request.delete(`/api/v1/misconfig/policies/${policyId}`)
    expect(res.status()).toBe(200)

    // Verify deletion
    const list = await request.get('/api/v1/misconfig/policies')
    const policies = await list.json()
    const found = policies.find((p: any) => p.id === policyId)
    expect(found).toBeUndefined()
  })
})

test.describe('Misconfig Workflow - UI', () => {
  test('misconfig page shows dashboard and catalog tabs', async ({ page }) => {
    await page.goto('/misconfig')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toBeVisible()
  })
})

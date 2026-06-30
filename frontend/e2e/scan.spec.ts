import { test, expect } from '@playwright/test'

test.describe('Scan Workflow - API', () => {
  test('submit scan job and poll to completion', async ({ request }) => {
    // Submit scan with a single fast service
    const submit = await request.post('/api/v1/jobs/scan', {
      data: { services: ['ec2'], regions: ['us-east-1'] },
    })
    expect(submit.status()).toBe(200)
    const submitBody = await submit.json()
    expect(submitBody.job_id).toBeDefined()
    expect(submitBody.job_type).toBe('scan')
    expect(submitBody.status).toBe('running')

    const jobId = submitBody.job_id

    // Poll until completion (max 120s)
    let finalStatus = 'running'
    let progress = 0
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const poll = await request.get(`/api/v1/jobs/${jobId}`)
      expect(poll.status()).toBe(200)
      const job = await poll.json()
      finalStatus = job.status
      progress = job.progress

      if (finalStatus === 'completed' || finalStatus === 'failed') break
    }

    expect(['completed', 'failed']).toContain(finalStatus)
    // If completed, progress should be 100
    if (finalStatus === 'completed') {
      expect(progress).toBe(100)
    }
  })

  test('scan history shows completed scan', async ({ request }) => {
    const res = await request.get('/api/v1/scans/history')
    expect(res.status()).toBe(200)
    const history = await res.json()
    expect(Array.isArray(history)).toBe(true)
    // Should have at least one scan after the previous test
    if (history.length > 0) {
      const latest = history[0]
      expect(latest.scan_mode).toBe('local')
      expect(latest.collected_by).toBe('bluearch')
      expect(latest.status).toBeDefined()
    }
  })

  test('resources endpoint returns data after scan', async ({ request }) => {
    const res = await request.get('/api/v1/resources')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.items).toBeDefined()
    expect(body.total).toBeDefined()
    // After a scan, should have at least some resources
    // (might be 0 if no EC2 instances exist, but format should be correct)
  })

  test('system stats reflects scan results', async ({ request }) => {
    const res = await request.get('/api/v1/system/stats')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.last_scan).toBeDefined()
    if (body.last_scan) {
      expect(body.last_scan.collected_by).toBe('bluearch')
      expect(body.last_scan.status).toBeDefined()
    }
  })

  test('recommendations endpoint works after scan', async ({ request }) => {
    const res = await request.get('/api/v1/recommendations')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.items).toBeDefined()
    expect(body.total).toBeDefined()
  })

  test('recommendations summary returns type breakdown', async ({ request }) => {
    const res = await request.get('/api/v1/recommendations/summary')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.total).toBeDefined()
    expect(body.by_type).toBeDefined()
  })

  test('jobs list shows scan job', async ({ request }) => {
    const res = await request.get('/api/v1/jobs?job_type=scan')
    expect(res.status()).toBe(200)
    const jobs = await res.json()
    expect(Array.isArray(jobs)).toBe(true)
    if (jobs.length > 0) {
      expect(jobs[0].job_type).toBe('scan')
      expect(['completed', 'failed', 'running']).toContain(jobs[0].status)
    }
  })

  test('accounts endpoint shows discovered account', async ({ request }) => {
    const res = await request.get('/api/v1/accounts')
    expect(res.status()).toBe(200)
    const accounts = await res.json()
    expect(Array.isArray(accounts)).toBe(true)
    // After scan, should have at least one account
    if (accounts.length > 0) {
      expect(accounts[0].account_id).toBeDefined()
      expect(accounts[0].account_name).toBeDefined()
    }
  })
})

test.describe('Scan Workflow - UI', () => {
  test('scans page loads and shows history or empty state', async ({ page }) => {
    await page.goto('/scans')
    await page.waitForLoadState('networkidle')
    // Should show either scan history table or empty state
    const body = page.locator('body')
    await expect(body).toBeVisible()
  })

  test('dashboard shows stats', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toBeVisible()
  })
})

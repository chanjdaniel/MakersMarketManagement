import { execSync } from 'child_process'
import type { Page } from '@playwright/test'
import {
  test,
  expect,
  TEST_USER,
  LoginPage,
  OrganizationsPage,
  BACKEND_URL,
} from './fixtures'
import { loginViaApi } from './helpers/seeds'

// ── Worktree-aware MongoDB container name ──
const MONGO_CONTAINER =
  process.env.E2E_MONGO_CONTAINER || 'conventioner-4-mongodb'

// ── Test user credentials ──
const ORG_MEMBER = {
  email: 'e2e-access-member@example.com',
  password: 'e2eaccessmember123',
}
const OUTSIDER = {
  email: 'e2e-access-outsider@example.com',
  password: 'e2eaccessoutsider123',
}

// ── Helpers ──

function ensureVerifiedUser(email: string, password: string): void {
  const registerCmd =
    `curl -k -s -X POST ${BACKEND_URL}/register-user ` +
    `-H 'Content-Type: application/json' ` +
    `-d '${JSON.stringify({ email, password, organizations: [] })}'`
  const registerOutput = execSync(registerCmd, {
    encoding: 'utf-8',
    timeout: 10000,
  })
  if (
    !registerOutput.includes('successfully') &&
    !registerOutput.includes('already exists')
  ) {
    throw new Error(`Failed to register ${email}: ${registerOutput}`)
  }

  const mongoCmd =
    `db.getSiblingDB("conventioner").users.updateOne(` +
    `{email: "${email}"}, {$set: {email_verified: true}})`
  execSync(
    `docker exec ${MONGO_CONTAINER} mongosh --quiet ` +
      `-u admin -p secret --authenticationDatabase admin ` +
      `--eval '${mongoCmd}'`,
    { encoding: 'utf-8', timeout: 10000 },
  )
}

async function loginAndGoToMarkets(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  const loginPage = new LoginPage(page)
  await loginPage.login(email, password)
  await loginPage.waitForDashboardRedirect()
  await page.goto('/markets')
}

/**
 * Create a unique org for a test and return the TEST_USER's user ID.
 * Returns the new org's ID, name, and the owner's user ID.
 */
async function createTestOrg(
  request: any,
  name: string,
): Promise<{ orgId: string; orgName: string; ownerUserId: string }> {
  const ownerUserId = await loginViaApi(
    request,
    BACKEND_URL,
    TEST_USER.email,
    TEST_USER.password,
  )

  const orgName = `${name} ${Date.now()}`
  const createRes = await request.post(`${BACKEND_URL}/organizations`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Owner-Email': TEST_USER.email,
    },
    data: { name: orgName },
  })
  if (!createRes.ok()) {
    throw new Error(
      `Org creation failed: ${createRes.status()} ${await createRes.text()}`,
    )
  }
  const orgId = (await createRes.json()).organization_id as string
  return { orgId, orgName, ownerUserId }
}

/**
 * GET /markets/{id} for a user. Logs in via API first so the session is valid.
 */
async function apiGetMarket(
  request: any,
  email: string,
  password: string,
  marketId: string,
): Promise<{ status: number; body: unknown }> {
  await loginViaApi(request, BACKEND_URL, email, password)
  const res = await request.get(
    `${BACKEND_URL}/markets/${encodeURIComponent(marketId)}`,
    { headers: { 'X-Owner-Email': email } },
  )
  let body: unknown
  try {
    body = await res.json()
  } catch {
    body = await res.text()
  }
  return { status: res.status(), body }
}

// ═══════════════════════════════════════════════════════════════════════════
// Org-membership visibility (the exact path that was silently broken)
// ═══════════════════════════════════════════════════════════════════════════

test.describe('Market visibility - org membership', () => {
  let marketId: string
  let marketName: string
  let orgId: string

  test.beforeAll(async ({ request }) => {
    ensureVerifiedUser(ORG_MEMBER.email, ORG_MEMBER.password)
    ensureVerifiedUser(OUTSIDER.email, OUTSIDER.password)

    const org = await createTestOrg(request, 'E2E Access Org')

    // Add ORG_MEMBER to the org (org-based VIEWER access, no explicit market role)
    await request.post(`${BACKEND_URL}/organizations/${org.orgId}/members`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: { user_email: ORG_MEMBER.email },
    })

    marketName = `E2E Org Access ${Date.now()}`
    const createRes = await request.post(`${BACKEND_URL}/markets`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: {
        name: marketName,
        creationDate: new Date().toISOString(),
        organizationId: org.orgId,
        roles: { [org.ownerUserId]: 'owner' },
        modificationList: [],
        assignmentObject: {},
      },
    })
    if (!createRes.ok()) {
      throw new Error(
        `Market creation failed: ${createRes.status()} ${await createRes.text()}`,
      )
    }
    marketId = (await createRes.json()).market_id as string
    orgId = org.orgId
  })

  test('org member sees market; outsider does not (paired)', async ({
    page,
    request,
  }) => {
    // ── Positive: org member (no explicit role) sees the market ──
    await loginAndGoToMarkets(page, ORG_MEMBER.email, ORG_MEMBER.password)
    await page.waitForSelector('.markets-view', { timeout: 10000 })

    const memberCard = page
      .locator('[data-testid="market-card"]')
      .filter({ hasText: marketName })
    await expect(memberCard).toBeVisible({ timeout: 10000 })

    // Positive: org member can GET the single market by ID
    const memberGet = await apiGetMarket(
      request,
      ORG_MEMBER.email,
      ORG_MEMBER.password,
      marketId,
    )
    expect(memberGet.status).toBe(200)
    const memberBody = memberGet.body as { market?: { name: string } }
    expect(memberBody.market?.name).toBe(marketName)

    // ── Negative: outsider does NOT see the market ──
    const outsiderPage = await page.context().newPage()
    try {
      await loginAndGoToMarkets(outsiderPage, OUTSIDER.email, OUTSIDER.password)
      await outsiderPage.waitForSelector('.markets-view', { timeout: 10000 })

      const outsiderCard = outsiderPage
        .locator('[data-testid="market-card"]')
        .filter({ hasText: marketName })
      await expect(outsiderCard).not.toBeVisible({ timeout: 5000 })

      const cards = outsiderPage.locator('[data-testid="market-card"]')
      await expect(cards).toHaveCount(0)
    } finally {
      await outsiderPage.close()
    }

    // Negative: outsider gets 404 on the single-market endpoint
    const outsiderGet = await apiGetMarket(
      request,
      OUTSIDER.email,
      OUTSIDER.password,
      marketId,
    )
    expect(outsiderGet.status).toBe(404)
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// Explicit-role visibility (role on the market without org membership)
// ═══════════════════════════════════════════════════════════════════════════

test.describe('Market visibility - explicit role', () => {
  const EXPLICIT_USER = {
    email: 'e2e-access-explicit@example.com',
    password: 'e2eaccessexplicit123',
  }

  let marketId: string
  let marketName: string

  test.beforeAll(async ({ request }) => {
    ensureVerifiedUser(EXPLICIT_USER.email, EXPLICIT_USER.password)
    ensureVerifiedUser(OUTSIDER.email, OUTSIDER.password)

    const org = await createTestOrg(request, 'E2E Explicit Org')

    marketName = `E2E Explicit Role ${Date.now()}`
    const createRes = await request.post(`${BACKEND_URL}/markets`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: {
        name: marketName,
        creationDate: new Date().toISOString(),
        organizationId: org.orgId,
        roles: { [org.ownerUserId]: 'owner' },
        modificationList: [],
        assignmentObject: {},
      },
    })
    if (!createRes.ok()) {
      throw new Error(
        `Market creation failed: ${createRes.status()} ${await createRes.text()}`,
      )
    }
    marketId = (await createRes.json()).market_id as string

    // Give EXPLICIT_USER a viewer role on the market (they are NOT in the org)
    await request.post(`${BACKEND_URL}/markets/${marketId}/roles`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: { user_email: EXPLICIT_USER.email, role: 'viewer' },
    })
  })

  test('user with explicit role sees market; outsider does not (paired)', async ({
    page,
    request,
  }) => {
    // ── Positive: explicit-role user sees the market ──
    await loginAndGoToMarkets(page, EXPLICIT_USER.email, EXPLICIT_USER.password)
    await page.waitForSelector('.markets-view', { timeout: 10000 })

    const roleCard = page
      .locator('[data-testid="market-card"]')
      .filter({ hasText: marketName })
    await expect(roleCard).toBeVisible({ timeout: 10000 })

    const roleGet = await apiGetMarket(
      request,
      EXPLICIT_USER.email,
      EXPLICIT_USER.password,
      marketId,
    )
    expect(roleGet.status).toBe(200)

    // ── Negative: outsider does NOT see the market ──
    const outsiderPage = await page.context().newPage()
    try {
      await loginAndGoToMarkets(outsiderPage, OUTSIDER.email, OUTSIDER.password)
      await outsiderPage.waitForSelector('.markets-view', { timeout: 10000 })

      const outsiderCard = outsiderPage
        .locator('[data-testid="market-card"]')
        .filter({ hasText: marketName })
      await expect(outsiderCard).not.toBeVisible({ timeout: 5000 })
    } finally {
      await outsiderPage.close()
    }

    const outsiderGet = await apiGetMarket(
      request,
      OUTSIDER.email,
      OUTSIDER.password,
      marketId,
    )
    expect(outsiderGet.status).toBe(404)
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// Org membership changes take effect (add → visible, remove → invisible)
// ═══════════════════════════════════════════════════════════════════════════

test.describe('Market visibility - org membership changes', () => {
  let marketId: string
  let marketName: string
  let orgId: string

  test.beforeAll(async ({ request }) => {
    ensureVerifiedUser(ORG_MEMBER.email, ORG_MEMBER.password)

    const org = await createTestOrg(request, 'E2E Membership Org')
    orgId = org.orgId

    marketName = `E2E Membership Chg ${Date.now()}`
    const createRes = await request.post(`${BACKEND_URL}/markets`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: {
        name: marketName,
        creationDate: new Date().toISOString(),
        organizationId: orgId,
        roles: { [org.ownerUserId]: 'owner' },
        modificationList: [],
        assignmentObject: {},
      },
    })
    if (!createRes.ok()) {
      throw new Error(
        `Market creation failed: ${createRes.status()} ${await createRes.text()}`,
      )
    }
    marketId = (await createRes.json()).market_id as string
  })

  test('add user to org grants visibility; remove revokes it', async ({
    page,
    request,
  }) => {
    // ── Phase 1: Before adding to org, ORG_MEMBER does NOT see the market ──
    await loginAndGoToMarkets(page, ORG_MEMBER.email, ORG_MEMBER.password)
    await page.waitForSelector('.markets-view', { timeout: 10000 })

    const cardBefore = page
      .locator('[data-testid="market-card"]')
      .filter({ hasText: marketName })
    await expect(cardBefore).not.toBeVisible({ timeout: 5000 })

    // ── Phase 2: Owner adds ORG_MEMBER to the org via API ──
    await loginViaApi(request, BACKEND_URL, TEST_USER.email, TEST_USER.password)
    const addRes = await request.post(
      `${BACKEND_URL}/organizations/${orgId}/members`,
      {
        headers: {
          'Content-Type': 'application/json',
          'X-Owner-Email': TEST_USER.email,
        },
        data: { user_email: ORG_MEMBER.email },
      },
    )
    if (!addRes.ok()) {
      throw new Error(
        `Add member failed: ${addRes.status()} ${await addRes.text()}`,
      )
    }

    // ── Phase 3: Now ORG_MEMBER sees the market ──
    await page.reload()
    await page.waitForSelector('.markets-view', { timeout: 10000 })

    const cardAfter = page
      .locator('[data-testid="market-card"]')
      .filter({ hasText: marketName })
    await expect(cardAfter).toBeVisible({ timeout: 10000 })

    // ── Phase 4: Owner removes ORG_MEMBER from the org via API ──
    // Need the member's user ID to call the remove endpoint.
    const memberUser = await loginViaApi(
      request,
      BACKEND_URL,
      ORG_MEMBER.email,
      ORG_MEMBER.password,
    )
    await loginViaApi(request, BACKEND_URL, TEST_USER.email, TEST_USER.password)
    const removeRes = await request.delete(
      `${BACKEND_URL}/organizations/${orgId}/users/${memberUser}`,
      {
        headers: {
          'Content-Type': 'application/json',
          'X-Owner-Email': TEST_USER.email,
        },
      },
    )
    if (!removeRes.ok()) {
      throw new Error(
        `Remove member failed: ${removeRes.status()} ${await removeRes.text()}`,
      )
    }

    // ── Phase 5: ORG_MEMBER no longer sees the market ──
    await page.reload()
    await page.waitForSelector('.markets-view', { timeout: 10000 })

    const cardRemoved = page
      .locator('[data-testid="market-card"]')
      .filter({ hasText: marketName })
    await expect(cardRemoved).not.toBeVisible({ timeout: 5000 })

    // ── API confirmation ──
    const getAfter = await apiGetMarket(
      request,
      ORG_MEMBER.email,
      ORG_MEMBER.password,
      marketId,
    )
    expect(getAfter.status).toBe(404)
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// Org deletion does not strand markets visible to wrong people
// ═══════════════════════════════════════════════════════════════════════════

test.describe('Market visibility - org deletion', () => {
  let marketId: string
  let marketName: string
  let orgId: string
  let orgName: string

  test.beforeAll(async ({ request }) => {
    ensureVerifiedUser(ORG_MEMBER.email, ORG_MEMBER.password)

    const org = await createTestOrg(request, 'E2E Delete Org')
    orgId = org.orgId
    orgName = org.orgName

    // Add ORG_MEMBER to the org
    await request.post(`${BACKEND_URL}/organizations/${orgId}/members`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: { user_email: ORG_MEMBER.email },
    })

    marketName = `E2E DeleteOrg ${Date.now()}`
    const createRes = await request.post(`${BACKEND_URL}/markets`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: {
        name: marketName,
        creationDate: new Date().toISOString(),
        organizationId: orgId,
        roles: { [org.ownerUserId]: 'owner' },
        modificationList: [],
        assignmentObject: {},
      },
    })
    if (!createRes.ok()) {
      throw new Error(
        `Market creation failed: ${createRes.status()} ${await createRes.text()}`,
      )
    }
    marketId = (await createRes.json()).market_id as string
  })

  test('deleting org revokes org-based access but owner still sees market via explicit role', async ({
    page,
    request,
  }) => {
    // ── Phase 1: ORG_MEMBER sees the market via org membership ──
    const memberPage = await page.context().newPage()
    try {
      await loginAndGoToMarkets(
        memberPage,
        ORG_MEMBER.email,
        ORG_MEMBER.password,
      )
      await memberPage.waitForSelector('.markets-view', { timeout: 10000 })

      const card = memberPage
        .locator('[data-testid="market-card"]')
        .filter({ hasText: marketName })
      await expect(card).toBeVisible({ timeout: 10000 })
    } finally {
      await memberPage.close()
    }

    // ── Phase 2: Owner deletes the org ──
    const ownerPage = await page.context().newPage()
    try {
      await loginAndGoToMarkets(
        ownerPage,
        TEST_USER.email,
        TEST_USER.password,
      )
      await ownerPage.goto('/organizations')
      await ownerPage.waitForSelector('.organizations-view', { timeout: 10000 })

      const orgsPage = new OrganizationsPage(ownerPage)
      await expect(
        ownerPage.locator('.org-card').filter({ hasText: orgName }),
      ).toBeVisible({ timeout: 5000 })

      const manageButton = ownerPage
        .locator('.org-card')
        .filter({ hasText: orgName })
        .getByTestId('organizations-manage-button')
      await manageButton.click()
      await orgsPage.waitForManageOverlay()

      await orgsPage.deleteOrg()
      await ownerPage.waitForTimeout(500)

      await expect(
        ownerPage.locator('.org-card').filter({ hasText: orgName }),
      ).not.toBeVisible({ timeout: 5000 })
    } finally {
      await ownerPage.close()
    }

    // ── Phase 3: ORG_MEMBER no longer sees the market ──
    const memberPageAfter = await page.context().newPage()
    try {
      await loginAndGoToMarkets(
        memberPageAfter,
        ORG_MEMBER.email,
        ORG_MEMBER.password,
      )
      await memberPageAfter.waitForSelector('.markets-view', {
        timeout: 10000,
      })

      const cardAfter = memberPageAfter
        .locator('[data-testid="market-card"]')
        .filter({ hasText: marketName })
      await expect(cardAfter).not.toBeVisible({ timeout: 5000 })
    } finally {
      await memberPageAfter.close()
    }

    // ── Phase 4: Owner with explicit role STILL sees the market ──
    // This positive twin proves the market exists and the query works.
    // Give TEST_USER explicit owner role on the market so access survives
    // org deletion.
    await loginViaApi(request, BACKEND_URL, TEST_USER.email, TEST_USER.password)
    await request.post(`${BACKEND_URL}/markets/${marketId}/roles`, {
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Email': TEST_USER.email,
      },
      data: { user_email: TEST_USER.email, role: 'owner' },
    })

    await loginAndGoToMarkets(page, TEST_USER.email, TEST_USER.password)
    await page.waitForSelector('.markets-view', { timeout: 10000 })

    const ownerCard = page
      .locator('[data-testid="market-card"]')
      .filter({ hasText: marketName })
    await expect(ownerCard).toBeVisible({ timeout: 10000 })

    // ── API: Owner still accesses; ORG_MEMBER is denied ──
    const ownerGet = await apiGetMarket(
      request,
      TEST_USER.email,
      TEST_USER.password,
      marketId,
    )
    expect(ownerGet.status).toBe(200)

    const memberGet = await apiGetMarket(
      request,
      ORG_MEMBER.email,
      ORG_MEMBER.password,
      marketId,
    )
    expect(memberGet.status).toBe(404)
  })
})

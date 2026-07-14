import type { Page } from '@playwright/test';

import {
  test,
  expect,
  BACKEND_URL,
  TEST_USER,
  ApplyPage,
  ApplicantLoginPage,
  ApplicantDashboardPage,
} from './fixtures';
import {
  seedApplicationsOpenMarket,
  type ApplicantMarketSeed,
} from './helpers/seedApplicantMarket';

/**
 * The public applicant flow, end to end: apply -> code-by-email sign-in -> dashboard.
 *
 * What is being pinned here is what has repeatedly broken: the applicant's answers surviving the
 * two things that unmount the form under them - the redirect to sign in, and a token that expires on
 * Save - and the answers of one applicant never reaching another's application. All three are
 * *cross-view* behavior. They live in the seam between a component ref, sessionStorage, the store,
 * an axios interceptor and the router, and a unit test that mounts one component or calls the store
 * directly cannot fail on any of them. That is precisely how three rounds of half-applied fixes
 * shipped with the unit suite green.
 *
 * No mocking: the market, the form, the phase, the mailed code and the applicant token are all real.
 * The one thing faked is the expiry itself - a 401 on the save, which is exactly what the back end
 * answers 30 minutes in, and waiting for that in a test would take 30 minutes.
 */

const APPLICANT = 'applicant-e2e@example.com';
const OTHER_APPLICANT = 'applicant-e2e-other@example.com';

/** The empty-answer dash the dashboard renders for a field the applicant has not filled in. */
const NO_ANSWER = '—';

let market: ApplicantMarketSeed;

function applyUrl(slug: string): RegExp {
  return new RegExp(`/${slug}/apply$`);
}

function loginUrl(slug: string, redirect: 'apply' | 'dashboard'): RegExp {
  return new RegExp(`/${slug}/applicant-login\\?redirect=${redirect}$`);
}

function dashboardUrl(slug: string): RegExp {
  return new RegExp(`/${slug}/applicant/dashboard$`);
}

/**
 * The applicant's token expires between two keystrokes and they find out on Save. The back end
 * answers that save with a 401, and everything the applicant sees next follows from it: the axios
 * interceptor drops the token, the store ends the session, and the router unmounts the form they
 * were typing into. Only the first save expires - the applicant signs back in and saves for real.
 */
async function expireTheSessionOnTheNextSave(page: Page) {
  let expired = false;
  await page.route('**/applicant/application', async (route) => {
    if (!expired && route.request().method() === 'PUT') {
      expired = true;
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          error: 'Authentication required. Your session may have expired.',
        }),
      });
      return;
    }
    await route.continue();
  });
}

test.describe('Public applicant flow', () => {
  // A market only takes applications once an organizer has published it into `applications_open`,
  // and it can only get there with a form. Both are done through the product's own endpoints.
  test.beforeEach(async ({ request }) => {
    market = await seedApplicationsOpenMarket(
      request,
      BACKEND_URL,
      TEST_USER.email,
      TEST_USER.password,
    );
  });

  test('a first-time applicant keeps their answers through the sign-in redirect, and saves them on the other side', async ({
    page,
  }) => {
    const apply = new ApplyPage(page);
    const login = new ApplicantLoginPage(page);
    const dashboard = new ApplicantDashboardPage(page);

    // The primary path: a stranger with a link, no account, and a form in front of them.
    await apply.goto(market.marketSlug);
    await expect(apply.submitButton).toHaveText('Save & Continue');
    await apply.fillField('business_name', 'Acme Bakery');
    await apply.fillField('product_type', 'Sourdough');
    await apply.submit();

    // The button cannot save before there is a session, so it sends them to make one - and that
    // redirect unmounts the form holding everything they just typed.
    await page.waitForURL(loginUrl(market.marketSlug, 'apply'));
    await login.signIn(market.marketId, APPLICANT);

    // Back on the page they came from, and their answers survived it. They are offered rather than
    // laid into the form: nobody was signed in when they were typed, so this is the applicant who
    // typed them only if the person now at the keyboard says so.
    await page.waitForURL(applyUrl(market.marketSlug));
    await expect(apply.draftOffer).toBeVisible();
    await apply.restoreOfferedDraft();
    await expect(apply.input('business_name')).toHaveValue('Acme Bakery');
    await expect(apply.input('product_type')).toHaveValue('Sourdough');

    await apply.submit();
    await expect(apply.savedBanner).toBeVisible();

    // The server has them, not just the tab: a fresh load and a fresh sign-in read them back.
    await login.goto(market.marketSlug);
    await login.signIn(market.marketId, APPLICANT);
    await page.waitForURL(dashboardUrl(market.marketSlug));
    await expect(dashboard.field('business_name')).toContainText('Acme Bakery');
    await expect(dashboard.field('product_type')).toContainText('Sourdough');
  });

  test('the application form fits a phone, which is what an applicant opens the link on', async ({
    page,
  }) => {
    const apply = new ApplyPage(page);

    await page.setViewportSize({ width: 390, height: 844 });
    await apply.goto(market.marketSlug);

    // The organizer's shell has a 1000px width floor - it renders tables and floorplans - and the
    // public pages used to inherit it, which put every applicant on a page zoomed out and scrolled
    // sideways on the device they most often reach it from.
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(overflows).toBe(false);
    await expect(apply.submitButton).toBeInViewport();
  });

  test('a session that expires mid-edit does not cost the applicant their answers', async ({
    page,
  }) => {
    const login = new ApplicantLoginPage(page);
    const dashboard = new ApplicantDashboardPage(page);

    await login.goto(market.marketSlug);
    await login.signIn(market.marketId, APPLICANT);
    await page.waitForURL(dashboardUrl(market.marketSlug));

    // Asking for a code creates the application, but nothing has been submitted into it yet.
    await expect(dashboard.unsubmittedNotice).toBeVisible();

    await dashboard.startEditing();
    await dashboard.editInput('business_name').fill('Acme Bakery');
    await dashboard.editInput('product_type').fill('Sourdough');

    await expireTheSessionOnTheNextSave(page);
    await dashboard.saveButton.click();

    // The session is over, and the page that held the answers has been unmounted by the redirect.
    await page.waitForURL(loginUrl(market.marketSlug, 'dashboard'));

    await login.signIn(market.marketId, APPLICANT);
    await page.waitForURL(dashboardUrl(market.marketSlug));

    // The interrupted edit is open again, with what they typed still in it.
    await expect(dashboard.editForm).toBeVisible();
    await expect(dashboard.editInput('business_name')).toHaveValue('Acme Bakery');
    await expect(dashboard.editInput('product_type')).toHaveValue('Sourdough');

    // And Save, which is what they were trying to do all along, now works.
    await dashboard.saveButton.click();
    await expect(dashboard.view).toBeVisible();
    await expect(dashboard.field('business_name')).toContainText('Acme Bakery');
  });

  test('answers stranded by an expired session are not handed to the next applicant who signs in', async ({
    page,
  }) => {
    const apply = new ApplyPage(page);
    const login = new ApplicantLoginPage(page);
    const dashboard = new ApplicantDashboardPage(page);

    // A shared tab - the laptop at the market's own front desk, a library terminal. The first
    // applicant applies and signs in on it.
    await apply.goto(market.marketSlug);
    await apply.fillField('business_name', 'Alice Bakery');
    await apply.fillField('product_type', 'Sourdough');
    await apply.submit();
    await page.waitForURL(loginUrl(market.marketSlug, 'apply'));
    await login.signIn(market.marketId, APPLICANT);
    await page.waitForURL(applyUrl(market.marketSlug));
    await apply.restoreOfferedDraft();
    await apply.submit();
    await expect(apply.savedBanner).toBeVisible();

    // They keep editing, and their session expires on the save. Their unsaved answers are held on
    // purpose - that is the one moment they are most needed - and they were typed under a verified
    // session, so the product knows whose they are. They are still in this tab when the applicant
    // walks away from it.
    await apply.fillField('business_name', 'Alice Secret Recipes Ltd');
    await expireTheSessionOnTheNextSave(page);
    await apply.submit();
    await page.waitForURL(loginUrl(market.marketSlug, 'apply'));

    // Somebody else sits down and signs in.
    await login.signIn(market.marketId, OTHER_APPLICANT);
    await page.waitForURL(applyUrl(market.marketSlug));

    // The first applicant's business details are not theirs to read - not in the form, and not even
    // as something to be offered: those answers have an owner, and it is not this applicant.
    await expect(apply.input('business_name')).toHaveValue('');
    await expect(apply.input('product_type')).toHaveValue('');
    await expect(apply.draftOffer).not.toBeVisible();
    await expect(apply.savedBanner).not.toBeVisible();

    // Which the server confirms: their application is untouched.
    await login.goto(market.marketSlug);
    await login.signIn(market.marketId, OTHER_APPLICANT);
    await page.waitForURL(dashboardUrl(market.marketSlug));
    await expect(dashboard.unsubmittedNotice).toBeVisible();
    await expect(dashboard.field('business_name')).toContainText(NO_ANSWER);
  });

  test('answers typed by somebody who never signed in are not saved onto the applicant who does', async ({
    page,
  }) => {
    const apply = new ApplyPage(page);
    const login = new ApplicantLoginPage(page);
    const dashboard = new ApplicantDashboardPage(page);

    // The same shared tab, and the ordinary thing that happens at one: the first applicant fills in
    // the form, presses the button, and walks away from the login screen without signing in. Nobody
    // was signed in while they typed, so nothing the product holds says who they were.
    await apply.goto(market.marketSlug);
    await apply.fillField('business_name', 'Alice Bakery');
    await apply.fillField('product_type', 'Sourdough');
    await apply.submit();
    await page.waitForURL(loginUrl(market.marketSlug, 'apply'));

    // The next person sits down at the login screen that is already on it, and signs in as
    // themselves.
    await login.signIn(market.marketId, OTHER_APPLICANT);
    await page.waitForURL(applyUrl(market.marketSlug));

    // The answers are offered, because they may well be this applicant's own - but they are not put
    // into the form, and above all this page does not finish anybody's save with them. Answers on a
    // screen can be cleared by the person looking at them; answers written onto their application
    // cannot.
    await expect(apply.draftOffer).toBeVisible();
    await expect(apply.input('business_name')).toHaveValue('');
    await expect(apply.savedBanner).not.toBeVisible();

    await apply.discardOfferedDraft();
    await expect(apply.draftOffer).not.toBeVisible();

    // And the server agrees: nothing was written onto the application of the applicant who signed in.
    await login.goto(market.marketSlug);
    await login.signIn(market.marketId, OTHER_APPLICANT);
    await page.waitForURL(dashboardUrl(market.marketSlug));
    await expect(dashboard.unsubmittedNotice).toBeVisible();
    await expect(dashboard.field('business_name')).toContainText(NO_ANSWER);
  });
});

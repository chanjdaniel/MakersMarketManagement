// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';
import axios, { type AxiosRequestConfig } from 'axios';

import ApplicantDashboard from '@/views/ApplicantDashboard.vue';
import { applicantApi } from '@/utils/applicantApi';
import { installApplicantSessionExpiry } from '@/utils/applicantSessionExpiry';
import { useApplicationStore } from '@/stores/application';
import { fetchPublicApplicationForm } from '@/utils/publicApplicationForm';

/**
 * The applicant's token lives 30 minutes, so it expires while they are typing - and the moment it
 * bites is the Save at the end of a long form, which is the worst possible moment to lose the lot.
 *
 * What happens then is not a component's decision: the back end answers 401, the interceptor drops
 * the token and ends the session, and the applicant is redirected to sign in - which unmounts the
 * page and takes every answer held in a component ref with it. So the answers have to be somewhere
 * else *before* the request goes out, and the applicant has to come back to the page that can put
 * them on screen.
 *
 * These drive the real round-trip: a stubbed transport answers the save with the 401 the back end
 * would, so the interceptor, the store and the redirect all run exactly as they do in the browser.
 */

const MARKET = 'summer-market';

vi.mock('@/utils/publicApplicationForm', () => ({
  fetchPublicApplicationForm: vi.fn(),
}));

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { marketSlug: 'summer-market' }, query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}));

const FIELDS = [
  { key: 'business_name', label: 'Business Name', type: 'text', required: true, options: [], order: 0 },
  { key: 'agree', label: 'I agree to the terms', type: 'checkbox', required: true, options: [], order: 1 },
];

const SAVED = { business_name: 'Acme Bakery', agree: true };
const EDITED = { business_name: 'Acme Bakery & Cafe', agree: true };
const APPLICATION = { id: 'app-1', formData: SAVED, status: 'open', submittedAt: '2026-05-01' };

const originalAdapter = applicantApi.defaults.adapter;

function reply(config: AxiosRequestConfig, status: number, data: unknown) {
  const response = { data, status, statusText: '', headers: {}, config } as never;
  if (status >= 400) {
    return Promise.reject(
      new axios.AxiosError('Request failed', String(status), config as never, {}, response),
    );
  }
  return Promise.resolve(response);
}

/**
 * The back end as this flow meets it: sign-in works, reading the application works, and the save is
 * the request whose token has expired.
 */
function backEndWhoseTokenHasExpired() {
  applicantApi.defaults.adapter = ((config: AxiosRequestConfig) => {
    if (config.method === 'post') {
      return reply(config, 200, { token: 'a-token', application: APPLICATION });
    }
    if (config.method === 'get') {
      return reply(config, 200, { application: APPLICATION });
    }
    return reply(config, 401, { error: 'Authentication required. Your session may have expired.' });
  }) as never;
}

/** The router as the expiry handler sees it: the applicant is on `routeName` when the save fails. */
function routerOn(routeName: string) {
  return {
    currentRoute: { value: { name: routeName, params: { marketSlug: MARKET } } },
    push: vi.fn(),
  };
}

async function signIn() {
  const store = useApplicationStore();
  await store.verifyKey(MARKET, 'vendor@example.com', '123456');
  return store;
}

describe('a session that expires mid-save does not cost the applicant their answers', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    sessionStorage.clear();
    vi.clearAllMocks();
    backEndWhoseTokenHasExpired();
    vi.mocked(fetchPublicApplicationForm).mockResolvedValue({
      fields: FIELDS,
      marketName: 'Summer Market',
      phaseLabel: 'Applications Open',
      isOpen: true,
    } as never);
  });

  afterEach(() => {
    applicantApi.defaults.adapter = originalAdapter;
  });

  it('holds the answers before the request goes out, not after it comes back', async () => {
    const store = await signIn();
    let draftWhenTheRequestWasMade: Record<string, unknown> | null = null;
    applicantApi.defaults.adapter = ((config: AxiosRequestConfig) => {
      draftWhenTheRequestWasMade = store.draftAnswers(MARKET);
      return reply(config, 401, { error: 'expired' });
    }) as never;

    const ok = await store.saveApplication(MARKET, EDITED);

    expect(ok).toBe(false);
    // Nothing that runs after this request returns is still on the page that holds these answers:
    // the 401 unmounts it. A draft written in the failure handler is a draft written too late.
    expect(draftWhenTheRequestWasMade).toEqual(EDITED);
    expect(store.draftAnswers(MARKET)).toEqual(EDITED);
  });

  it('ends the session and returns the applicant to the page they were on', async () => {
    const router = routerOn('applicant-dashboard');
    installApplicantSessionExpiry(router as never);
    const store = await signIn();

    await store.saveApplication(MARKET, EDITED);
    await flushPromises();

    expect(store.isAuthenticatedFor(MARKET)).toBe(false);
    expect(router.push).toHaveBeenCalledWith({
      name: 'applicant-login',
      params: { marketSlug: MARKET },
      query: { redirect: 'dashboard' },
    });
  });

  it('returns an applicant whose save expired on the application page to that page', async () => {
    const router = routerOn('apply');
    installApplicantSessionExpiry(router as never);
    const store = await signIn();

    await store.saveApplication(MARKET, EDITED);
    await flushPromises();

    // The application page is where their answers were typed, and where `completePendingSave`
    // finishes the save they asked for. The dashboard could do neither.
    expect(router.push).toHaveBeenCalledWith({
      name: 'applicant-login',
      params: { marketSlug: MARKET },
      query: { redirect: 'apply' },
    });
  });

  it('puts the interrupted edit back on the dashboard when the applicant signs back in', async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    installApplicantSessionExpiry(routerOn('applicant-dashboard') as never);
    await signIn();

    const dashboard = mount(ApplicantDashboard, { global: { plugins: [pinia] } });
    await flushPromises();
    await dashboard.find('[data-testid="applicant-dashboard-edit-btn"]').trigger('click');
    await dashboard
      .find('[data-testid="applicant-dashboard-edit-input-business_name"]')
      .setValue('Acme Bakery & Cafe');
    await dashboard.find('[data-testid="applicant-dashboard-edit"] button').trigger('click');
    await flushPromises();

    // The session is over and the redirect has taken the page with it.
    dashboard.unmount();

    const store = await signIn();
    const reopened = mount(ApplicantDashboard, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(reopened.find('[data-testid="applicant-dashboard-edit"]').exists()).toBe(true);
    expect(
      (reopened
        .find('[data-testid="applicant-dashboard-edit-input-business_name"]')
        .element as HTMLInputElement).value,
    ).toBe('Acme Bakery & Cafe');
    expect(store.draftAnswers(MARKET)).toEqual(EDITED);
  });

  it('drops the draft once the applicant cancels the edit it belonged to', async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = await signIn();

    const dashboard = mount(ApplicantDashboard, { global: { plugins: [pinia] } });
    await flushPromises();
    await dashboard.find('[data-testid="applicant-dashboard-edit-btn"]').trigger('click');
    await dashboard
      .find('[data-testid="applicant-dashboard-edit-input-business_name"]')
      .setValue('Acme Bakery & Cafe');
    const [save, cancel] = dashboard.findAll('[data-testid="applicant-dashboard-edit"] button');
    await save.trigger('click');
    await flushPromises();

    await cancel.trigger('click');

    // Cancelling is the applicant discarding the edit. Kept, the draft would be restored over their
    // saved answers on the next visit - the same data loss, running backwards.
    expect(store.draftAnswers(MARKET)).toBeNull();
  });
});

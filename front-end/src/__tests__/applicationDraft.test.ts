// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';

import ApplicationPage from '@/views/ApplicationPage.vue';
import { applicantApi } from '@/utils/applicantApi';
import { useApplicationStore } from '@/stores/application';
import { fetchPublicApplicationForm } from '@/utils/publicApplicationForm';

/**
 * The application page renders an editable form to a signed-out visitor and a button that says it
 * will save it. It cannot: saving needs a session, so the button sends them to sign in first - and
 * that redirect unmounts the form. The answers have to survive it, or the primary path of this whole
 * feature is a button labelled "Save" that throws away everything a first-time applicant typed.
 *
 * These tests drive the real round-trip: fill in the form, press the button while signed out, then
 * mount the page again the way the router does when the applicant comes back holding a session.
 */

const MARKET = 'summer-market';

vi.mock('@/utils/publicApplicationForm', () => ({
  fetchPublicApplicationForm: vi.fn(),
}));

const push = vi.fn();
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { marketSlug: 'summer-market' }, query: {} }),
  useRouter: () => ({ push }),
}));

/** A checkbox is in here on purpose: an answer that is not a string has to survive the trip too. */
const FIELDS = [
  { key: 'business_name', label: 'Business Name', type: 'text', required: true, options: [], order: 0 },
  { key: 'booth_size', label: 'Booth Size', type: 'select', required: true, options: ['Small', 'Large'], order: 1 },
  { key: 'agree', label: 'I agree to the terms', type: 'checkbox', required: true, options: [], order: 2 },
];

const TYPED_ANSWERS = {
  business_name: 'Acme Bakery',
  booth_size: 'Large',
  agree: true,
};

function mountPage() {
  return mount(ApplicationPage, { global: { plugins: [createPinia()] } });
}

/** The answers the applicant typed into the rendered form, entered through the inputs themselves. */
async function typeAnswers(page: ReturnType<typeof mountPage>) {
  await page.find('[data-testid="apply-input-business_name"]').setValue('Acme Bakery');
  await page.find('[data-testid="apply-input-booth_size"]').setValue('Large');
  await page.find('[data-testid="apply-input-agree"]').setValue(true);
}

describe('answers typed before signing in survive the login redirect', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    sessionStorage.clear();
    vi.clearAllMocks();
    vi.mocked(fetchPublicApplicationForm).mockResolvedValue({
      fields: FIELDS,
      marketName: 'Summer Market',
      phaseLabel: 'Applications Open',
      isOpen: true,
    } as never);
  });

  it('keeps the answers when Save & Continue redirects a signed-out applicant to sign in', async () => {
    const page = mountPage();
    await flushPromises();
    await typeAnswers(page);

    await page.find('[data-testid="apply-form"]').trigger('submit');
    await flushPromises();

    expect(push).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'applicant-login', query: { redirect: 'apply' } }),
    );
    expect(useApplicationStore().draftAnswers(MARKET)).toEqual(TYPED_ANSWERS);
  });

  it('restores them into the form when the applicant comes back signed in', async () => {
    const first = mountPage();
    await flushPromises();
    await typeAnswers(first);
    await first.find('[data-testid="apply-form"]').trigger('submit');
    await flushPromises();
    first.unmount();

    // The applicant verified their code. The back end hands back the application it created for
    // them when they asked for one, which for a first-time applicant is an empty form - so the
    // answers can only come from the draft.
    const pinia = createPinia();
    setActivePinia(pinia);
    vi.spyOn(applicantApi, 'post').mockResolvedValue({
      data: { token: 'a-token', application: { id: 'app-1', formData: {} } },
    });
    const put = vi.spyOn(applicantApi, 'put').mockResolvedValue({
      data: { data: {}, application: { id: 'app-1', formData: {} } },
    } as never);
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');

    const back = mount(ApplicationPage, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(
      (back.find('[data-testid="apply-input-business_name"]').element as HTMLInputElement).value,
    ).toBe('Acme Bakery');
    expect(
      (back.find('[data-testid="apply-input-booth_size"]').element as HTMLSelectElement).value,
    ).toBe('Large');
    expect(
      (back.find('[data-testid="apply-input-agree"]').element as HTMLInputElement).checked,
    ).toBe(true);

    // "Save & Continue" promised a save, and coming back with a session is what it was waiting for.
    expect(put).toHaveBeenCalledWith('/public/markets/summer-market/applicant/application', {
      formData: TYPED_ANSWERS,
    });
    expect(back.find('[data-testid="apply-saved"]').exists()).toBe(true);
    expect(store.draftAnswers(MARKET)).toBeNull();
  });

  it('keeps the answers when a visitor backs out of the login screen without verifying', async () => {
    const first = mountPage();
    await flushPromises();
    await typeAnswers(first);
    await first.find('[data-testid="apply-form"]').trigger('submit');
    await flushPromises();
    first.unmount();

    setActivePinia(createPinia());
    const back = mountPage();
    await flushPromises();

    expect(
      (back.find('[data-testid="apply-input-business_name"]').element as HTMLInputElement).value,
    ).toBe('Acme Bakery');
  });
});

describe('the draft belongs to one market, and to one applicant', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it('does not prefill one market answers into another market form', () => {
    const store = useApplicationStore();

    store.rememberDraftAnswers('market-a', { business_name: 'Acme' });

    expect(store.draftAnswers('market-b')).toBeNull();
  });

  it('keeps the draft when the session merely expires, so signing back in does not cost the answers', async () => {
    vi.spyOn(applicantApi, 'post').mockResolvedValue({
      data: { token: 'a-token', application: { id: 'app-1', formData: {} } },
    });
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');
    store.rememberDraftAnswers(MARKET, { business_name: 'Acme' });

    store.endExpiredSession();

    expect(store.draftAnswers(MARKET)).toEqual({ business_name: 'Acme' });
  });

  it('discards the draft on a deliberate sign-out, so a shared machine does not leak it', async () => {
    vi.spyOn(applicantApi, 'post').mockResolvedValue({
      data: { token: 'a-token', application: { id: 'app-1', formData: {} } },
    });
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');
    store.rememberDraftAnswers(MARKET, { business_name: 'Acme' });

    store.logout();

    expect(store.draftAnswers(MARKET)).toBeNull();
  });

  it('keeps the draft when the save it was waiting for fails', async () => {
    vi.spyOn(applicantApi, 'post').mockResolvedValue({
      data: { token: 'a-token', application: { id: 'app-1', formData: {} } },
    });
    vi.spyOn(applicantApi, 'put').mockRejectedValue(new Error('network down'));
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');
    store.rememberDraftAnswers(MARKET, { business_name: 'Acme' });

    const ok = await store.saveApplication(MARKET, { business_name: 'Acme' });

    expect(ok).toBe(false);
    expect(store.draftAnswers(MARKET)).toEqual({ business_name: 'Acme' });
  });
});

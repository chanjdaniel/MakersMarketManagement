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
 * They survive as an *unowned* draft, and what may be done with one is the other half of these
 * tests. Nobody signed in when they were typed, so the product knows only that they were entered in
 * this tab - and a tab at a shared desk outlives the person who used it. So they are offered back to
 * be accepted on sight, and never written onto an application by the page itself. Answers shown to
 * the wrong person are cleared by that person; answers saved onto the wrong person's application are
 * not.
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

/**
 * The back end as sign-in meets it: a token, and the application it was issued for - which carries
 * the address it belongs to, because an application is identified by (market, email) and the draft
 * that shadows it has to be reconciled against the same pair.
 */
function signInAs(email: string) {
  vi.spyOn(applicantApi, 'post').mockResolvedValue({
    data: {
      token: 'a-token',
      application: { id: `app-${email}`, applicantEmail: email, formData: {} },
    },
  });
}

/** The answers the applicant typed into the rendered form, entered through the inputs themselves. */
async function typeAnswers(page: ReturnType<typeof mountPage>) {
  await page.find('[data-testid="apply-input-business_name"]').setValue('Acme Bakery');
  await page.find('[data-testid="apply-input-booth_size"]').setValue('Large');
  await page.find('[data-testid="apply-input-agree"]').setValue(true);
}

/** Type the form and press "Save & Continue" while signed out, which is what leaves the draft. */
async function typeAndLeaveForTheLoginScreen() {
  const page = mountPage();
  await flushPromises();
  await typeAnswers(page);
  await page.find('[data-testid="apply-form"]').trigger('submit');
  await flushPromises();
  page.unmount();
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
    // Nobody had said who they were, so the draft is owned by nobody - which is what decides
    // everything the page is then allowed to do with it.
    expect(useApplicationStore().draftFor(MARKET)).toEqual({
      answers: TYPED_ANSWERS,
      owned: false,
    });
  });

  it('offers the answers back to the applicant who comes back signed in, and saves nothing until they accept', async () => {
    await typeAndLeaveForTheLoginScreen();

    // The applicant verified their code. The back end hands back the application it created for
    // them when they asked for one, which for a first-time applicant is an empty form - so the
    // answers can only come from the draft.
    const pinia = createPinia();
    setActivePinia(pinia);
    signInAs('vendor@example.com');
    const put = vi.spyOn(applicantApi, 'put').mockResolvedValue({
      data: { application: { id: 'app-1', formData: TYPED_ANSWERS } },
    } as never);
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');

    const back = mount(ApplicationPage, { global: { plugins: [pinia] } });
    await flushPromises();

    // Signing in proves who this applicant is. It proves nothing about who typed answers into this
    // tab before anyone was signed in, so nothing is put into the form and nothing is sent.
    expect(back.find('[data-testid="apply-draft-offer"]').exists()).toBe(true);
    expect(
      (back.find('[data-testid="apply-input-business_name"]').element as HTMLInputElement).value,
    ).toBe('');
    expect(put).not.toHaveBeenCalled();
    expect(back.find('[data-testid="apply-saved"]').exists()).toBe(false);

    // The person at the screen says the answers are theirs, and now they are on screen - all of
    // them, including the ones that are not strings.
    await back.find('[data-testid="apply-draft-restore-button"]').trigger('click');
    expect(
      (back.find('[data-testid="apply-input-business_name"]').element as HTMLInputElement).value,
    ).toBe('Acme Bakery');
    expect(
      (back.find('[data-testid="apply-input-booth_size"]').element as HTMLSelectElement).value,
    ).toBe('Large');
    expect(
      (back.find('[data-testid="apply-input-agree"]').element as HTMLInputElement).checked,
    ).toBe(true);
    expect(back.find('[data-testid="apply-draft-offer"]').exists()).toBe(false);

    // And the save is theirs to press, having read what they are about to submit.
    await back.find('[data-testid="apply-form"]').trigger('submit');
    await flushPromises();

    expect(put).toHaveBeenCalledWith('/public/markets/summer-market/applicant/application', {
      formData: TYPED_ANSWERS,
    });
    expect(back.find('[data-testid="apply-saved"]').exists()).toBe(true);
    expect(store.draftFor(MARKET)).toBeNull();
  });

  it('discards the offered answers when the person at the screen says they are not theirs', async () => {
    await typeAndLeaveForTheLoginScreen();

    const pinia = createPinia();
    setActivePinia(pinia);
    signInAs('someone-else@example.com');
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'someone-else@example.com', '123456');

    const back = mount(ApplicationPage, { global: { plugins: [pinia] } });
    await flushPromises();
    await back.find('[data-testid="apply-draft-discard-button"]').trigger('click');

    // A shared tab must not go on offering one person's answers to everybody who sits down at it.
    expect(back.find('[data-testid="apply-draft-offer"]').exists()).toBe(false);
    expect(store.draftFor(MARKET)).toBeNull();
  });

  it('keeps the answers when a visitor backs out of the login screen without verifying', async () => {
    await typeAndLeaveForTheLoginScreen();

    setActivePinia(createPinia());
    const back = mountPage();
    await flushPromises();
    await back.find('[data-testid="apply-draft-restore-button"]').trigger('click');

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

    expect(store.draftFor('market-b')).toBeNull();
  });

  it('does not stamp answers typed on one market with the address a session on another market was issued to', async () => {
    // A vendor signed in to one market opens another market's application URL. The session names
    // them to the market it was issued for and to no other, so it cannot say whose these answers
    // are - and an owner recorded wrongly here is answers destroyed on the next sign-in.
    signInAs('vendor@example.com');
    const store = useApplicationStore();
    await store.verifyKey('market-a', 'vendor@example.com', '123456');

    store.rememberDraftAnswers('market-b', { business_name: 'Acme' });
    signInAs('their-other-address@example.com');
    await store.verifyKey('market-b', 'their-other-address@example.com', '654321');

    expect(store.draftFor('market-b')).toEqual({
      answers: { business_name: 'Acme' },
      owned: false,
    });
  });

  it('keeps the draft when the session merely expires, so signing back in does not cost the answers', async () => {
    signInAs('vendor@example.com');
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');
    store.rememberDraftAnswers(MARKET, { business_name: 'Acme' });

    store.endExpiredSession();

    // The answers are still in storage, and the applicant they belong to gets them back the moment
    // they are that applicant again - owned, because a verified session is what wrote them.
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');
    expect(store.draftFor(MARKET)).toEqual({
      answers: { business_name: 'Acme' },
      owned: true,
    });
  });

  it('does not hand an expired applicant answers to the next applicant who signs in', async () => {
    // The shared tab: a laptop at the market's own front desk, or a library terminal. The first
    // applicant's session expires mid-save - which deliberately leaves their answers in storage -
    // and somebody else signs in on it.
    signInAs('first@example.com');
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'first@example.com', '123456');
    store.rememberDraftAnswers(MARKET, { business_name: 'First Applicant Bakery' });
    store.endExpiredSession();

    signInAs('second@example.com');
    await store.verifyKey(MARKET, 'second@example.com', '654321');

    // Their business details are not the second applicant's to read, and - on the application page,
    // which finishes the save the button promised - not theirs to have written onto their
    // application either.
    expect(store.draftFor(MARKET)).toBeNull();
  });

  it('does not show a signed-in applicant answers to a visitor who is not signed in', async () => {
    signInAs('vendor@example.com');
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');
    store.rememberDraftAnswers(MARKET, { business_name: 'Acme' });

    store.endExpiredSession();

    // Nobody is signed in, so nobody is known to be the applicant these belong to.
    expect(store.draftFor(MARKET)).toBeNull();
  });

  it('does not make answers typed before sign-in the property of whoever signs in next', async () => {
    const store = useApplicationStore();
    // Nobody has said who they are yet - that is what the login screen is for - and the applicant
    // who typed these can walk away from that screen before the next person sits down at it.
    store.rememberDraftAnswers(MARKET, { business_name: 'Acme' });

    signInAs('vendor@example.com');
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');

    // Still nobody's: readable, so the page can offer them back, and unowned, so no page may
    // restore them by itself or save them onto this applicant's application.
    expect(store.draftFor(MARKET)).toEqual({
      answers: { business_name: 'Acme' },
      owned: false,
    });
  });

  it('discards the draft on a deliberate sign-out, so a shared machine does not leak it', async () => {
    signInAs('vendor@example.com');
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');
    store.rememberDraftAnswers(MARKET, { business_name: 'Acme' });

    store.logout();

    expect(store.draftFor(MARKET)).toBeNull();
  });

  it('keeps the draft when the save it was waiting for fails', async () => {
    signInAs('vendor@example.com');
    vi.spyOn(applicantApi, 'put').mockRejectedValue(new Error('network down'));
    const store = useApplicationStore();
    await store.verifyKey(MARKET, 'vendor@example.com', '123456');

    const ok = await store.saveApplication(MARKET, { business_name: 'Acme' });

    expect(ok).toBe(false);
    expect(store.draftFor(MARKET)).toEqual({
      answers: { business_name: 'Acme' },
      owned: true,
    });
  });
});

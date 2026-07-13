import { describe, it, expect, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';

import { applicantApi } from '@/utils/applicantApi';
import { useApplicationStore } from '@/stores/application';

/**
 * An applicant session is scoped to the market it was issued for. It has to be: every applicant
 * route is per-market, so a session that is merely "signed in" lets an applicant who signed in for
 * market A open market B's public application URL and submit B's answers - which land on A's
 * application, and where the two forms share a field key (`business_name`, `email`) silently
 * overwrite a submitted one. The back end is the authority; this is the guard that keeps the UI
 * from inviting the action.
 */
describe('applicant session is scoped to its market', () => {
  let get: ReturnType<typeof vi.spyOn>;
  let put: ReturnType<typeof vi.spyOn>;

  async function signInFor(slug: string) {
    vi.spyOn(applicantApi, 'post').mockResolvedValue({
      data: { token: 'a-token', application: { id: 'app-1', formData: {} } },
    });
    const store = useApplicationStore();
    await store.verifyKey(slug, 'vendor@example.com', '123456');
    return store;
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
    get = vi.spyOn(applicantApi, 'get').mockResolvedValue({ data: { application: {} } });
    put = vi.spyOn(applicantApi, 'put').mockResolvedValue({ data: { application: {} } });
  });

  it('is authenticated for the market it signed in to', async () => {
    const store = await signInFor('market-a');

    expect(store.isAuthenticatedFor('market-a')).toBe(true);
  });

  it('is not authenticated for any other market', async () => {
    const store = await signInFor('market-a');

    expect(store.isAuthenticatedFor('market-b')).toBe(false);
  });

  it('refuses to save another market answers with this market session', async () => {
    const store = await signInFor('market-a');

    const ok = await store.saveApplication('market-b', { business_name: 'Acme' });

    expect(ok).toBe(false);
    expect(put).not.toHaveBeenCalled();
    expect(store.error).toContain('sign in');
  });

  it('refuses to fetch another market application with this market session', async () => {
    const store = await signInFor('market-a');

    await store.fetchApplication('market-b');

    expect(get).not.toHaveBeenCalled();
  });

  it('saves to the market the session was issued for, by name', async () => {
    const store = await signInFor('market-a');

    const ok = await store.saveApplication('market-a', { business_name: 'Acme' });

    expect(ok).toBe(true);
    expect(put).toHaveBeenCalledWith('/public/markets/market-a/applicant/application', {
      formData: { business_name: 'Acme' },
    });
  });

  it('drops the market with the token when the session ends', async () => {
    const store = await signInFor('market-a');

    store.endExpiredSession();

    expect(store.isAuthenticatedFor('market-a')).toBe(false);
    expect(store.marketSlug).toBeNull();
  });
});

import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { Application } from '@/assets/types/datatypes';
import { getApiErrorMessage } from '@/utils/api';
import { applicantApi, setApplicantToken } from '@/utils/applicantApi';

/** The applicant's application on one market. Both routes name the market they act on. */
function applicationUrl(marketSlug: string): string {
  return `/public/markets/${marketSlug}/applicant/application`;
}

export const useApplicationStore = defineStore('application', () => {
  const token = ref<string | null>(null);
  /**
   * The market the token was issued for. An application belongs to one market, so the session that
   * edits it does too: without this the session is global while every applicant route is per-market,
   * and an applicant signed in for market A who opens market B's public application URL submits B's
   * answers onto A's application - which, where the two forms share a field key, silently overwrites
   * a submitted application with another market's answers. The back end is the authority here (it
   * refuses a token whose market does not match the route); this is what keeps the UI from
   * inviting the action in the first place.
   */
  const marketSlug = ref<string | null>(null);
  const application = ref<Application | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  /**
   * Whether the applicant is signed in *for this market*. Holding a token is not enough, and there
   * is deliberately no market-less "is signed in" to ask instead: every applicant screen belongs to
   * a market, so every authentication question is about one.
   */
  function isAuthenticatedFor(slug: string): boolean {
    return token.value !== null && marketSlug.value === slug;
  }

  async function requestKey(slug: string, email: string): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.post('/public/applicant/request-key', {
        marketSlug: slug,
        email,
      });
      // 200 means the code was sent (or would have been, if the email matched)
      if (!data.message) {
        error.value = 'Unexpected response from server.';
      }
    } catch (err: unknown) {
      error.value = getApiErrorMessage(err, 'Failed to send verification code. Please try again.');
    } finally {
      loading.value = false;
    }
  }

  async function verifyKey(slug: string, email: string, key: string): Promise<boolean> {
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.post('/public/applicant/verify-key', {
        marketSlug: slug,
        email,
        key,
      });
      if (data.token) {
        token.value = data.token;
        marketSlug.value = slug;
        application.value = data.application;
        setApplicantToken(data.token);
        return true;
      }
      error.value = 'No token returned.';
      return false;
    } catch (err: unknown) {
      error.value = getApiErrorMessage(err, 'Verification failed. Please try again.');
      return false;
    } finally {
      loading.value = false;
    }
  }

  /**
   * The market is named rather than taken from the session, so a caller that has drifted onto
   * another market's page cannot send this session's token at it: the request the store will not
   * make is one the back end never has to refuse.
   */
  async function fetchApplication(slug: string): Promise<void> {
    if (!isAuthenticatedFor(slug)) {
      error.value = 'Please sign in to view your application for this market.';
      return;
    }
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.get(applicationUrl(slug));
      application.value = data.application;
    } catch (err: unknown) {
      error.value = getApiErrorMessage(err, 'Failed to load your application.');
    } finally {
      loading.value = false;
    }
  }

  async function saveApplication(
    slug: string,
    formData: Record<string, unknown>,
  ): Promise<boolean> {
    if (!isAuthenticatedFor(slug)) {
      error.value = 'Please sign in to save your application for this market.';
      return false;
    }
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.put(applicationUrl(slug), { formData });
      application.value = data.application;
      return true;
    } catch (err: unknown) {
      error.value = getApiErrorMessage(err, 'Failed to save your application.');
      return false;
    } finally {
      loading.value = false;
    }
  }

  function clearSession() {
    token.value = null;
    marketSlug.value = null;
    application.value = null;
    setApplicantToken(null);
  }

  function logout() {
    clearSession();
    error.value = null;
  }

  /**
   * The applicant's token was refused, so the session is over whether or not they are done with
   * it. Holding on to a token the back end has rejected is what turns an expiry into a dead end:
   * the store keeps reading as authenticated, and every retry re-sends the same dead token.
   */
  function endExpiredSession() {
    clearSession();
    error.value = 'Your session has expired. Please sign in again to continue.';
  }

  return {
    token,
    marketSlug,
    application,
    loading,
    error,
    isAuthenticatedFor,
    requestKey,
    verifyKey,
    fetchApplication,
    saveApplication,
    logout,
    endExpiredSession,
  };
});

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { Application } from '@/assets/types/datatypes';
import { getApiErrorMessage } from '@/utils/api';
import { applicantApi, setApplicantToken } from '@/utils/applicantApi';

export const useApplicationStore = defineStore('application', () => {
  const token = ref<string | null>(null);
  const application = ref<Application | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const isAuthenticated = computed(() => token.value !== null);

  async function requestKey(marketSlug: string, email: string): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.post('/public/applicant/request-key', {
        marketSlug,
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

  async function verifyKey(marketSlug: string, email: string, key: string): Promise<boolean> {
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.post('/public/applicant/verify-key', {
        marketSlug,
        email,
        key,
      });
      if (data.token) {
        token.value = data.token;
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

  async function fetchApplication(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.get('/public/applicant/application');
      application.value = data.application;
    } catch (err: unknown) {
      error.value = getApiErrorMessage(err, 'Failed to load your application.');
    } finally {
      loading.value = false;
    }
  }

  async function saveApplication(formData: Record<string, unknown>): Promise<boolean> {
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.put('/public/applicant/application', { formData });
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
    application,
    loading,
    error,
    isAuthenticated,
    requestKey,
    verifyKey,
    fetchApplication,
    saveApplication,
    logout,
    endExpiredSession,
  };
});

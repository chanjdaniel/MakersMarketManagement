import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { Application } from '@/assets/types/datatypes';
import { getApiErrorMessage } from '@/utils/api';
import { applicantApi, setApplicantToken } from '@/utils/applicantApi';
import { claimDraft, forgetDraft, readDraft, rememberDraft } from '@/utils/applicantDraft';
import { executeRecaptcha } from '@/utils/captcha';

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
  /**
   * The address the token was issued to. An application is identified by (market, email), so the
   * market alone does not say whose answers the session is holding - and a tab is not one applicant:
   * an expired session leaves its draft behind on purpose, and the next person to sign in on that
   * machine is not necessarily the one who typed it. This is what tells the two apart. See
   * `@/utils/applicantDraft`.
   */
  const applicantEmail = ref<string | null>(null);
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

  /**
   * The back end refuses this request without a captcha token: it is public, unauthenticated, and
   * it sends mail to whatever address it is handed, so it carries the same gate the organizer-side
   * signup does. A captcha that cannot be obtained is not a reason to skip the call - the token is
   * scored by the back end, which is the only place that can decide what a bad score means.
   */
  async function requestKey(slug: string, email: string): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const captchaToken = await executeRecaptcha('applicant_request_key').catch(() => '');
      const { data } = await applicantApi.post('/public/applicant/request-key', {
        marketSlug: slug,
        email,
        captchaToken,
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

  /**
   * Carries a captcha token for the same reason `requestKey` does, and the back end refuses this
   * request without one: it is public, unauthenticated, and it spends a per-IP budget that everyone
   * behind a shared address (a hall's wifi, a carrier's CGNAT pool) spends too. A budget a caller
   * can spend without passing the captcha is a budget a script can take away from every real
   * applicant behind that address.
   *
   * Signing in is also the moment any draft on this market becomes decidably this applicant's or
   * somebody else's, so it is where that is settled: they adopt the answers they typed on their way
   * here, and a draft left by a different address - an applicant whose session expired on this same
   * tab - is destroyed rather than left for the prefill to layer over their application. See
   * `claimDraft`.
   */
  async function verifyKey(slug: string, email: string, key: string): Promise<boolean> {
    loading.value = true;
    error.value = null;
    try {
      const captchaToken = await executeRecaptcha('applicant_verify_key').catch(() => '');
      const { data } = await applicantApi.post('/public/applicant/verify-key', {
        marketSlug: slug,
        email,
        key,
        captchaToken,
      });
      if (data.token) {
        token.value = data.token;
        marketSlug.value = slug;
        // The server's copy is the address the token was actually issued to, which is the identity
        // the draft has to be reconciled against.
        applicantEmail.value = data.application?.applicantEmail ?? email;
        application.value = data.application;
        setApplicantToken(data.token);
        claimDraft(slug, applicantEmail.value as string);
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

  /**
   * The draft is written *before* the request, not after it fails, and that ordering is the whole
   * fix. This request is the one that can end the session: the token lives 30 minutes, an applicant
   * filling in a long form will hit an expired one on Save, and the 401 handler drops the token,
   * ends the session and redirects to sign in - which unmounts whichever form was on screen and
   * takes its component-local answers with it. Nothing after the `await` runs on that page again,
   * so a draft written in the `catch` is a draft written into a component that no longer exists.
   *
   * Every save goes through here, so every save is covered by that: the application page's
   * signed-in Save, the save it finishes on the applicant's behalf after they sign in, and the
   * dashboard's edit. A rule kept in each component is a rule the next component forgets.
   */
  async function saveApplication(
    slug: string,
    formData: Record<string, unknown>,
  ): Promise<boolean> {
    if (!isAuthenticatedFor(slug)) {
      error.value = 'Please sign in to save your application for this market.';
      return false;
    }
    rememberDraft(slug, applicantEmail.value, formData);
    loading.value = true;
    error.value = null;
    try {
      const { data } = await applicantApi.put(applicationUrl(slug), { formData });
      application.value = data.application;
      // These answers are the server's now, so the draft has nothing left to protect. A draft that
      // outlived the save it was waiting for would be prefilled over the applicant's own saved
      // answers on their next visit, which is the data loss this exists to prevent, running
      // backwards. A save that *failed* keeps it: that is exactly when it is still needed.
      forgetDraft(slug);
      return true;
    } catch (err: unknown) {
      error.value = getApiErrorMessage(err, 'Failed to save your application.');
      return false;
    } finally {
      loading.value = false;
    }
  }

  /**
   * Answers typed before signing in, kept somewhere that outlives the redirect to the login screen.
   * See `@/utils/applicantDraft`: the application page unmounts on that redirect, and its answers go
   * with it unless something holds them.
   *
   * This is the one save path that never reaches `saveApplication` - there is no session to save
   * into yet - so it is the one that has to hand its answers over itself. It writes an *unowned*
   * draft, because a visitor who has not signed in has not said who they are; the applicant who
   * signs in next on this tab adopts it, which is the applicant who typed it.
   */
  function rememberDraftAnswers(slug: string, formData: Record<string, unknown>): void {
    rememberDraft(slug, applicantEmail.value, formData);
  }

  /**
   * Answers held for whoever is signed in - and only for them. A draft another applicant left on
   * this tab is not readable here, so nothing can prefill it into this applicant's form or save it
   * onto their application.
   */
  function draftAnswers(slug: string): Record<string, unknown> | null {
    return readDraft(slug, applicantEmail.value);
  }

  /**
   * The applicant abandoned the edit those answers belonged to. A draft is what a save or a session
   * left *unfinished*, so one the applicant has finished with by discarding it must go: kept, it
   * would be restored over their saved answers the next time they opened the page, which is the
   * data loss this whole mechanism exists to prevent, pointed the other way.
   */
  function discardDraftAnswers(slug: string): void {
    forgetDraft(slug);
  }

  function clearSession() {
    token.value = null;
    marketSlug.value = null;
    applicantEmail.value = null;
    application.value = null;
    setApplicantToken(null);
  }

  /**
   * A deliberate sign-out, so the draft goes too: an applicant who signs out on a shared machine -
   * a library terminal, a laptop at the market's own front desk - must not leave their half-typed
   * answers to be prefilled into the next person's form.
   *
   * This is why signing out and being signed *out* are different functions. See
   * `endExpiredSession`, which must not do this.
   */
  function logout() {
    const slug = marketSlug.value;
    clearSession();
    if (slug) forgetDraft(slug);
    error.value = null;
  }

  /**
   * The applicant's token was refused, so the session is over whether or not they are done with
   * it. Holding on to a token the back end has rejected is what turns an expiry into a dead end:
   * the store keeps reading as authenticated, and every retry re-sends the same dead token.
   *
   * The draft deliberately survives this. The session is short-lived and expiring mid-form is a
   * normal path, not an edge case - it is the one moment the applicant most needs their answers to
   * still be there when they sign back in. Only a deliberate `logout` discards them.
   *
   * It survives *owned*, and the identity goes with the session, so nothing can read it again until
   * the applicant it belongs to signs back in. That is what keeps "the answers are still here" from
   * meaning "the answers are still here for whoever sits down next": this is exactly the state a
   * shared machine is left in, so the draft outliving the session and the draft belonging to nobody
   * cannot both be true. See `claimDraft`.
   */
  function endExpiredSession() {
    clearSession();
    error.value = 'Your session has expired. Please sign in again to continue.';
  }

  return {
    token,
    marketSlug,
    applicantEmail,
    application,
    loading,
    error,
    isAuthenticatedFor,
    requestKey,
    verifyKey,
    fetchApplication,
    saveApplication,
    rememberDraftAnswers,
    draftAnswers,
    discardDraftAnswers,
    logout,
    endExpiredSession,
  };
});

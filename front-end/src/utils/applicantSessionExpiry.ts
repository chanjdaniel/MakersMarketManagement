import type { Router } from 'vue-router';

import { useApplicationStore } from '@/stores/application';
import { setApplicantSessionExpiredHandler } from '@/utils/applicantApi';

/**
 * What happens when the back end refuses the applicant's token.
 *
 * The token lives 30 minutes, so expiring mid-form is a normal path rather than an edge case: the
 * applicant is most likely to meet it on the Save at the end of a long form, which is the worst
 * possible moment to lose what they typed. Two things have to be true for that not to cost them
 * their answers, and this is one of them.
 *
 * The other is that the answers are already in the draft: `saveApplication` writes it *before* the
 * request goes out, precisely because nothing after the request returns will run on that page - this
 * handler unmounts it. So the only job left here is to send the applicant back to the page they were
 * on, which is the page that can put their answers back on screen. A redirect to a generic landing
 * would strand a draft nobody comes back for.
 *
 * It lives in a module of its own, rather than inline in `main.ts`, so the routing decision it makes
 * is one a test can drive: `main.ts` mounts the app on import, and an app entry point is not a thing
 * a unit test can call.
 */
export function installApplicantSessionExpiry(router: Router): void {
  setApplicantSessionExpiredHandler(() => {
    useApplicationStore().endExpiredSession();

    const from = router.currentRoute.value;
    router.push({
      name: 'applicant-login',
      params: { marketSlug: from.params.marketSlug },
      query: { redirect: from.name === 'apply' ? 'apply' : 'dashboard' },
    });
  });
}

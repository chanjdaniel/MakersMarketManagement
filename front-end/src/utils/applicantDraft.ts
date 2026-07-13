/**
 * Answers an applicant typed before they had a session to save them into.
 *
 * The application page renders an editable form to a signed-out visitor, and its "Save & Continue"
 * button cannot save anything until they have signed in - so it sends them to the login screen
 * first, which unmounts the form and takes every component-local answer with it. The store's
 * `application` is no help: it is the *server's* copy, and for an address that has only just been
 * sent its first code that is an empty form. Something has to outlive the redirect, and this is it.
 *
 * Held in `sessionStorage` rather than only in the store because the login round-trip is not
 * guaranteed to be a router push - a reload, or a code opened in the same tab, would take an
 * in-memory draft with it - and it dies with the tab, which is the right lifetime for answers that
 * were never saved.
 *
 * Keyed by market for the same reason the session is (see `useApplicationStore.marketSlug`): a draft
 * is answers to *one* market's form, and two markets' forms can share field keys, so a market-less
 * draft is one market's answers waiting to be prefilled into another's.
 */

const DRAFT_KEY_PREFIX = 'applicant-draft:';

function draftKey(marketSlug: string): string {
  return `${DRAFT_KEY_PREFIX}${marketSlug}`;
}

/**
 * Storage is not guaranteed: Safari's private mode has historically thrown on write, and a browser
 * configured to refuse site data throws on read. Losing the draft is bad; taking the application
 * form down with it is worse, so every one of these degrades to "there is no draft".
 */
export function rememberDraft(marketSlug: string, formData: Record<string, unknown>): void {
  if (!marketSlug) return;
  try {
    sessionStorage.setItem(draftKey(marketSlug), JSON.stringify(formData));
  } catch {
    // A browser that will not store the draft still gets a working form.
  }
}

export function readDraft(marketSlug: string): Record<string, unknown> | null {
  if (!marketSlug) return null;
  try {
    const raw = sessionStorage.getItem(draftKey(marketSlug));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function forgetDraft(marketSlug: string): void {
  if (!marketSlug) return;
  try {
    sessionStorage.removeItem(draftKey(marketSlug));
  } catch {
    // Nothing to do: the draft is already unreadable to anyone who asks for it.
  }
}

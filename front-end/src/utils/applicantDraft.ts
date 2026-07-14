/**
 * Answers an applicant typed and has not saved yet, kept somewhere that outlives the page.
 *
 * The application page renders an editable form to a signed-out visitor, and its "Save & Continue"
 * button cannot save anything until they have signed in - so it sends them to the login screen
 * first, which unmounts the form and takes every component-local answer with it. The applicant's
 * token expires after 30 minutes, so a Save at the end of a long form does the same thing by a
 * different route: the 401 ends the session and redirects, and the page goes with it. The store's
 * `application` is no help either way: it is the *server's* copy, and what is being protected here
 * is precisely the answers the server does not have.
 *
 * Held in `sessionStorage` rather than only in the store because neither round-trip is guaranteed
 * to be a router push - a reload, or a code opened in the same tab, would take an in-memory draft
 * with it - and it dies with the tab, which is the right lifetime for answers that were never saved.
 *
 * An application is identified by (market, email), and so is a draft of one.
 *
 * The market half is why a draft is not global: a draft is answers to *one* market's form, and two
 * markets' forms can share field keys, so a market-less draft is one market's answers waiting to be
 * prefilled into another's.
 *
 * The email half is why a draft has an owner. A tab is not one applicant: a session that expires
 * deliberately leaves its draft behind (that is the moment the answers are most needed), so a laptop
 * at a convention's own front desk can have one applicant's unsaved answers in storage while the
 * next applicant signs in on it. Owned by nobody, those answers would be prefilled into the new
 * applicant's form and - on the application page, which finishes the save the button promised -
 * written onto their application, with nothing pressed and nothing to warn either of them.
 *
 * So an owned draft is readable only by the applicant who wrote it, and signing in as anyone else
 * destroys it (`claimDraft`). A draft typed before signing in has no email to own it - that is the
 * design, and the whole reason it exists - so it stays unowned and is adopted by the first applicant
 * to sign in on that tab, which is the applicant who typed it.
 */

const DRAFT_KEY_PREFIX = 'applicant-draft:';

/** The applicant a draft belongs to, or `null` for answers typed before there was one. */
type DraftOwner = string | null;

interface StoredDraft {
  email: DraftOwner;
  answers: Record<string, unknown>;
}

function draftKey(marketSlug: string): string {
  return `${DRAFT_KEY_PREFIX}${marketSlug}`;
}

/** Addresses are compared, so they are compared in one spelling. The login screen sends this one. */
function normalizeOwner(email: DraftOwner): DraftOwner {
  const normalized = email?.trim().toLowerCase();
  return normalized ? normalized : null;
}

/**
 * Storage is not guaranteed: Safari's private mode has historically thrown on write, and a browser
 * configured to refuse site data throws on read. Losing the draft is bad; taking the application
 * form down with it is worse, so every one of these degrades to "there is no draft".
 */
function loadDraft(marketSlug: string): StoredDraft | null {
  if (!marketSlug) return null;
  try {
    const raw = sessionStorage.getItem(draftKey(marketSlug));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const { email, answers } = parsed as Partial<StoredDraft>;
    // A draft with no owner recorded at all is not one this build wrote. Treating it as unowned
    // would hand it to whoever signs in next, which is the exposure the owner exists to close.
    if (!answers || typeof answers !== 'object' || Array.isArray(answers)) return null;
    if (email !== null && typeof email !== 'string') return null;
    return { email: normalizeOwner(email), answers: answers as Record<string, unknown> };
  } catch {
    return null;
  }
}

function storeDraft(marketSlug: string, draft: StoredDraft): void {
  try {
    sessionStorage.setItem(draftKey(marketSlug), JSON.stringify(draft));
  } catch {
    // A browser that will not store the draft still gets a working form.
  }
}

/**
 * Hold these answers for `email`, who is `null` when they have not signed in yet. The owner is
 * recorded with the answers rather than folded into the storage key so that a draft belonging to
 * somebody else is *found* and destroyed on the next sign-in, instead of sitting in storage waiting
 * for its owner to come back to a machine they have walked away from.
 */
export function rememberDraft(
  marketSlug: string,
  email: DraftOwner,
  answers: Record<string, unknown>,
): void {
  if (!marketSlug) return;
  storeDraft(marketSlug, { email: normalizeOwner(email), answers });
}

/**
 * The draft `email` is entitled to read, if there is one. `email` is `null` for a visitor who is not
 * signed in, and they are entitled to the unowned draft only: an owned one is a signed-in
 * applicant's unsaved answers, and a signed-out visitor is not known to be them.
 */
export function readDraft(
  marketSlug: string,
  email: DraftOwner,
): Record<string, unknown> | null {
  const draft = loadDraft(marketSlug);
  if (!draft) return null;
  if (draft.email !== null && draft.email !== normalizeOwner(email)) return null;
  return draft.answers;
}

/**
 * An applicant just signed in. Any draft on this market is now decidably theirs or not: an unowned
 * one is the one they typed on their way to the login screen, and they take ownership of it; one
 * owned by another address belongs to somebody who is no longer signed in on this tab, and it is
 * destroyed rather than left for the prefill to find. This is the single point where a draft and an
 * identity are reconciled - doing it at each read would leave the stale answers in storage for the
 * next reader that forgot to check.
 */
export function claimDraft(marketSlug: string, email: string): void {
  const draft = loadDraft(marketSlug);
  if (!draft) return;

  const owner = normalizeOwner(email);
  if (draft.email === null) {
    storeDraft(marketSlug, { email: owner, answers: draft.answers });
    return;
  }
  if (draft.email !== owner) forgetDraft(marketSlug);
}

export function forgetDraft(marketSlug: string): void {
  if (!marketSlug) return;
  try {
    sessionStorage.removeItem(draftKey(marketSlug));
  } catch {
    // Nothing to do: the draft is already unreadable to anyone who asks for it.
  }
}

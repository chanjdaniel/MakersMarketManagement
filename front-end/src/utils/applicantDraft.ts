/**
 * Answers an applicant typed and has not saved yet, kept somewhere that outlives the page.
 *
 * The application page renders an editable form to a signed-out visitor, and its "Continue to sign
 * in" button cannot save anything until they have signed in - so it sends them to the login screen
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
 * The email half is why a draft has an owner, and why the owner is either a verified address or
 * *nobody*. A tab is not one applicant: a session that expires deliberately leaves its draft behind
 * (that is the moment the answers are most needed), so a laptop at a convention's own front desk can
 * hold one applicant's unsaved answers while the next applicant signs in on it.
 *
 * An **owned** draft was written while a verified session was live, so the product knows whose
 * answers those are: only that address can read them back, and signing in as anybody else destroys
 * them (`forgetForeignDraft`). Restoring them, and finishing the save they were interrupted by, is
 * done on that applicant's behalf, because the identity behind them was proved by a mailed code.
 *
 * An **unowned** draft was typed before anyone signed in, which is the whole reason it exists - and
 * the product has *no* evidence about who typed it. The only thing it knows is that the answers were
 * entered in this tab, and a tab at a shared desk outlives the person who used it: an applicant can
 * type, press "Continue to sign in", and walk away from the login screen before the next person sits
 * down. So an unowned draft is never *adopted* by whoever signs in next - it stays unowned, and the
 * line it may not cross is the *write*: nothing saves it onto anybody's application, ever.
 *
 * Short of that write it is restored, visibly, into the form, under a notice saying where the
 * answers came from and that they have not been submitted. Withholding them is not the safe default
 * it looks like: on the ordinary path they are the reader's own - typed a moment ago, on this page,
 * before signing in - and a first-time applicant asked to re-accept what they just pressed a button
 * to keep reads that as the product having lost it. Answers shown to the wrong person are cleared by
 * that person; answers written onto the wrong person's application are not. The line is drawn at the
 * write, not at the display.
 *
 * The exception, and the only one, is an unowned draft over an application that *already* holds saved
 * answers. Restoring would lay a possible stranger's typing over a submitted application, and
 * discarding would throw away answers a possible returning applicant typed a minute ago; nothing here
 * can tell those two apart, and both guesses destroy somebody's work. So neither is made: the saved
 * answers stay in the form, the draft stays in storage, and the applicant is asked. See `draftFor` in
 * the store.
 */

const DRAFT_KEY_PREFIX = 'applicant-draft:';

/** The applicant a draft belongs to, or `null` for answers typed before there was one. */
export type DraftOwner = string | null;

export interface StoredDraft {
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
 * Hold these answers for `email`, who is `null` when nobody is signed in on this market - which is
 * the only honest owner for answers typed by a person who has not said who they are. The owner is
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
 * The draft `email` is entitled to see, if there is one - answers *and* the owner that decides what
 * may be done with them. `email` is `null` for a visitor who is not signed in, and they are entitled
 * to the unowned draft only: an owned one is a signed-in applicant's unsaved answers, and a
 * signed-out visitor is not known to be them.
 *
 * The owner is handed back rather than stripped off here on purpose. A caller that receives bare
 * answers cannot tell whether the product knows who typed them, and the only safe default for that
 * caller - never restore, never save - would throw away the interrupted save this exists to finish.
 * So the distinction travels with the answers, and every caller has to decide about it.
 */
export function readDraft(marketSlug: string, email: DraftOwner): StoredDraft | null {
  const draft = loadDraft(marketSlug);
  if (!draft) return null;
  if (draft.email !== null && draft.email !== normalizeOwner(email)) return null;
  return draft;
}

/**
 * An applicant just signed in, and a draft owned by a *different* address is somebody else's
 * unsaved answers on a machine they are no longer signed in on. It is destroyed here rather than
 * left for a prefill to find: this is the single point where a draft and a proved identity meet, and
 * a check done at each read instead would leave the stale answers in storage for the next reader
 * that forgot to make it.
 *
 * An unowned draft is deliberately left as it is. Signing in proves who *this* applicant is; it
 * proves nothing about who typed answers before anyone was signed in, so the sign-in is not licence
 * to adopt them. They stay unowned, which is what keeps them out of every write; the application
 * page still puts them back on screen, and says so.
 */
export function forgetForeignDraft(marketSlug: string, email: string): void {
  const draft = loadDraft(marketSlug);
  if (!draft || draft.email === null) return;
  if (draft.email !== normalizeOwner(email)) forgetDraft(marketSlug);
}

export function forgetDraft(marketSlug: string): void {
  if (!marketSlug) return;
  try {
    sessionStorage.removeItem(draftKey(marketSlug));
  } catch {
    // Nothing to do: the draft is already unreadable to anyone who asks for it.
  }
}

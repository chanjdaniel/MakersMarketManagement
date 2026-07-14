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
 * So the owner is part of the *storage key*, not a field inside one slot per market. A single slot
 * cannot hold answers belonging to two people, and the second writer would silently win: a stranger
 * typing into the signed-out form would overwrite - with no sign-in, no proved identity, and nobody
 * having read them - the unsaved answers an applicant's expired session had left behind. An
 * ownership model the storage cannot represent is not a model; it is a comment. One slot per (market,
 * owner), plus exactly one per market for "nobody", is what makes each of the rules below something
 * the storage can actually keep.
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

/** Addresses are compared, so they are compared in one spelling. The login screen sends this one. */
function normalizeOwner(email: DraftOwner | undefined): DraftOwner {
  const normalized = email?.trim().toLowerCase();
  return normalized ? normalized : null;
}

/**
 * Every slot this market holds on this tab shares this prefix, which is what lets a sign-in find the
 * drafts of the addresses it displaces. The parts are escaped so the separator cannot be smuggled in
 * through either of them, and one market's prefix cannot be another market's prefix plus an owner.
 */
function marketPrefix(marketSlug: string): string {
  return `${DRAFT_KEY_PREFIX}${encodeURIComponent(marketSlug)}:`;
}

/** The one slot (market, owner) owns. The empty owner is "nobody", and there is one of those. */
function draftKey(marketSlug: string, owner: DraftOwner): string {
  return `${marketPrefix(marketSlug)}${owner ? encodeURIComponent(owner) : ''}`;
}

/**
 * Storage is not guaranteed: Safari's private mode has historically thrown on write, and a browser
 * configured to refuse site data throws on read. Losing the draft is bad; taking the application
 * form down with it is worse, so every one of these degrades to "there is no draft".
 */
function readSlot(marketSlug: string, owner: DraftOwner): StoredDraft | null {
  if (!marketSlug) return null;
  try {
    const raw = sessionStorage.getItem(draftKey(marketSlug, owner));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const { email, answers } = parsed as Partial<StoredDraft>;
    if (!answers || typeof answers !== 'object' || Array.isArray(answers)) return null;
    // The owner is in the key and in the value, so a slot whose two disagree has been written by
    // something that is not this module, and there is no reading it that is not a guess.
    if (normalizeOwner(email) !== owner) return null;
    return { email: owner, answers: answers as Record<string, unknown> };
  } catch {
    return null;
  }
}

function removeSlot(marketSlug: string, owner: DraftOwner): void {
  try {
    sessionStorage.removeItem(draftKey(marketSlug, owner));
  } catch {
    // Nothing to do: the draft is already unreadable to anyone who asks for it.
  }
}

/** Every key this market holds, whoever owns it - the only thing that has to enumerate. */
function marketSlots(marketSlug: string): string[] {
  if (!marketSlug) return [];
  const prefix = marketPrefix(marketSlug);
  try {
    const keys: string[] = [];
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = sessionStorage.key(i);
      if (key?.startsWith(prefix)) keys.push(key);
    }
    return keys;
  } catch {
    return [];
  }
}

function removeKey(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // As above.
  }
}

/**
 * Hold these answers for `email`, who is `null` when nobody is signed in on this market - which is
 * the only honest owner for answers typed by a person who has not said who they are. Each owner
 * writes to their own slot, so a draft written here can never be one written by somebody else: the
 * answers an expired session left behind are still there after a stranger types into the same form
 * on the same tab, and they are still that applicant's.
 */
export function rememberDraft(
  marketSlug: string,
  email: DraftOwner,
  answers: Record<string, unknown>,
): void {
  if (!marketSlug) return;
  const owner = normalizeOwner(email);
  try {
    sessionStorage.setItem(draftKey(marketSlug, owner), JSON.stringify({ email: owner, answers }));
  } catch {
    // A browser that will not store the draft still gets a working form.
  }
}

/**
 * The draft `email` is entitled to see, if there is one - answers *and* the owner that decides what
 * may be done with them. `email` is `null` for a visitor who is not signed in, and they are entitled
 * to the unowned draft only: an owned one is a signed-in applicant's unsaved answers, and a
 * signed-out visitor is not known to be them.
 *
 * A signed-in applicant is entitled to both, so their own draft comes first: it is the one the
 * product can prove is theirs, and the one that carries an interrupted save. The unowned draft is
 * what they get when they have none, which is the ordinary path - they typed it, signed in, and came
 * back for it.
 *
 * The owner is handed back rather than stripped off here on purpose. A caller that receives bare
 * answers cannot tell whether the product knows who typed them, and the only safe default for that
 * caller - never restore, never save - would throw away the interrupted save this exists to finish.
 * So the distinction travels with the answers, and every caller has to decide about it.
 */
export function readDraft(marketSlug: string, email: DraftOwner): StoredDraft | null {
  const owner = normalizeOwner(email);
  if (owner) {
    const owned = readSlot(marketSlug, owner);
    if (owned) return owned;
  }
  return readSlot(marketSlug, null);
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
  const mine = draftKey(marketSlug, normalizeOwner(email));
  const unowned = draftKey(marketSlug, null);
  for (const key of marketSlots(marketSlug)) {
    if (key !== mine && key !== unowned) removeKey(key);
  }
}

/**
 * The applicant has abandoned an edit of *their own*, so the draft holding it goes - and nothing
 * else does. A caller here is speaking about the answers it put in front of this applicant, which on
 * the dashboard are only ever the owned ones (`restorePendingEdits`), so an unowned draft it never
 * showed them is not its to destroy: those answers were typed by whoever was at the keyboard before,
 * this applicant has never seen them, and only a person looking at answers can say they are not
 * theirs.
 */
export function forgetOwnedDraft(marketSlug: string, email: DraftOwner): void {
  const owner = normalizeOwner(email);
  if (!marketSlug || !owner) return;
  removeSlot(marketSlug, owner);
}

/**
 * The applicant is done with the answers this market's pages could have put in front of them: their
 * own draft, and the unowned one the application page restores on sight. Both go - a save that
 * succeeded has taken them to the server, and a "not mine" has thrown them away, and either way a
 * draft left behind is one that would be laid back over the applicant's saved answers on their next
 * visit, which is this mechanism's own data loss running backwards.
 *
 * It does not touch another address's owned draft: that is not this applicant's to end, and nothing
 * has shown it to them. Signing in is where those die (`forgetForeignDraft`), and signing out is
 * where everything does (`forgetAllDrafts`).
 */
export function forgetDraft(marketSlug: string, email: DraftOwner): void {
  if (!marketSlug) return;
  forgetOwnedDraft(marketSlug, email);
  removeSlot(marketSlug, null);
}

/**
 * A deliberate sign-out on a machine that is not the applicant's - which is the case this exists for
 * - so nothing this market holds on this tab is left for the next person to sit down at it, whoever
 * it belonged to.
 */
export function forgetAllDrafts(marketSlug: string): void {
  for (const key of marketSlots(marketSlug)) removeKey(key);
}

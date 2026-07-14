<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { FormField } from '@/assets/types/datatypes';
import ApplicationFormFields from '@/components/application/ApplicationFormFields.vue';
import { getApiErrorMessage } from '@/utils/api';
import { formValidationErrors, sortedFormFields } from '@/utils/applicationForm';
import { fetchPublicApplicationForm } from '@/utils/publicApplicationForm';
import { useApplicationStore, type ApplicantDraft } from '@/stores/application';

const route = useRoute();
const router = useRouter();
const store = useApplicationStore();

const marketSlug = computed(() => (route.params.marketSlug as string) || '');

const fields = ref<FormField[]>([]);
const marketName = ref('');
const phaseLabel = ref('');
const isOpen = ref(false);
const loading = ref(true);
const pageError = ref<string | null>(null);

const formData = ref<Record<string, unknown>>({});
const validationErrors = ref<Record<string, string>>({});
const saving = ref(false);
const saved = ref(false);

const sortedFields = computed(() => sortedFormFields(fields.value));

/** A session is for one market, so holding a token for another one is not being signed in here. */
const signedIn = computed(() => store.isAuthenticatedFor(marketSlug.value));

onMounted(async () => {
  try {
    const form = await fetchPublicApplicationForm(marketSlug.value);
    fields.value = form.fields;
    marketName.value = form.marketName;
    phaseLabel.value = form.phaseLabel;
    isOpen.value = form.isOpen;
  } catch (err: unknown) {
    pageError.value = getApiErrorMessage(err, 'Failed to load the application form.');
    return;
  } finally {
    loading.value = false;
  }

  await completePendingSave();
});

/**
 * The unsaved answers this page put back, as the store last read them out of storage. Held in a ref
 * because storage is not reactive and this page changes it: a save clears it, and clearing the
 * restored answers below settles it.
 */
const draft = ref<ApplicantDraft | null>(null);

/** Dismissing the notice says "yes, these are mine" - it does not throw the answers away. */
const draftNoticeDismissed = ref(false);

/** The applicant answered the question below: the unowned answers are theirs, so they go in. */
const contestedDraftAccepted = ref(false);

/**
 * Unowned answers, and a saved application to lay them over. Both are somebody's, the product cannot
 * say whether it is the same somebody, and either way of guessing throws away answers that a person
 * typed - so the form keeps showing what the server holds, the draft is left where it is, and the
 * one party who knows is asked. See `draftFor` in the store.
 */
const contestedDraft = computed(
  () => !!draft.value?.contested && !contestedDraftAccepted.value,
);

/**
 * Answers were put into the form that the product cannot prove belong to whoever is reading it: they
 * were typed before anyone signed in, so all that is known of their author is that they used this
 * tab, and a tab at a shared desk is not a person. Restoring them is what the applicant who typed
 * them is owed; saying so, in front of the one person who can tell, is what the applicant who did
 * not is owed. See `@/utils/applicantDraft`.
 */
const restoredDraftNotice = computed(
  () =>
    !!draft.value &&
    !draft.value.owned &&
    !contestedDraft.value &&
    !draftNoticeDismissed.value,
);

function readDraft() {
  draft.value = store.draftFor(marketSlug.value);
}

/** The saved answers, which are only this page's to show when the session that holds them is here. */
function savedAnswers(): Record<string, unknown> {
  return signedIn.value ? { ...(store.application?.formData ?? {}) } : {};
}

/** "They are mine": the unowned answers go into the form, over the saved ones. Nothing is sent. */
function acceptContestedDraft() {
  contestedDraftAccepted.value = true;
  formData.value = { ...savedAnswers(), ...(draft.value?.answers ?? {}) };
  validationErrors.value = {};
}

// Prefill from what this applicant has already put into this market's form, from either of the two
// places it can be.
//
// The store's `application` is the server's copy. It belongs to the market its session was issued
// for, so it is only this page's to prefill from when that is this market: an application read under
// any other condition is another market's answers, copied into this form wherever the two forms
// share a field key.
//
// The draft is answers typed on this page and not yet saved, and it goes back into the form whether
// or not the product knows whose it is. Answers on a screen are answers a person can read and clear;
// what an unowned draft may not do is reach the *server* on somebody's behalf - see
// `completePendingSave`. Withholding them until asked for cost the first-time applicant, on the
// product's primary path, the answers they had just pressed a button to keep.
//
// The one draft this merge will not make that decision for is a contested one - unowned answers over
// an application that already has saved ones. There the saved answers stand, untouched, and the
// applicant is asked; see `contestedDraft`.
watch(
  () => (signedIn.value ? store.application : null),
  (app) => {
    readDraft();
    const merged = {
      ...(app?.formData ?? {}),
      ...(contestedDraft.value ? {} : draft.value?.answers ?? {}),
    };
    if (Object.keys(merged).length > 0) {
      formData.value = merged;
    }
  },
  { immediate: true },
);

/**
 * The applicant pressed Save while signed in, the request 401'd on an expired token, and they signed
 * back in as the same address and were sent here. The save is still owed to them: the watcher above
 * has already put their answers back into the form, and this finishes the sentence the button
 * started, because a mailed code proved the draft in storage is theirs.
 *
 * It runs for an owned draft and nothing else. An unowned one was typed by whoever was at this
 * keyboard before any sign-in, and the applicant now signed in is not known to be that person - so
 * saving it here would write a stranger's answers onto their application with nothing pressed. That
 * is the one thing that cannot be undone by the person who sees it happen, so it is the one thing
 * this page will not do: an unowned draft is put in front of them, said so, and left for them to
 * submit or clear.
 *
 * A save that fails leaves the draft alone (see `saveApplication`), so nothing is lost by trying:
 * the answers stay on screen, the error says why, and the button is there to try again.
 */
async function completePendingSave() {
  if (!signedIn.value || !isOpen.value) return;
  if (!draft.value?.owned) return;

  if (!validateAll()) return;

  saving.value = true;
  try {
    const ok = await store.saveApplication(marketSlug.value, formData.value);
    if (ok) saved.value = true;
  } finally {
    saving.value = false;
    readDraft();
  }
}

/**
 * The person at the screen has said the unowned answers are not theirs - either of the restored ones
 * ("not mine") or of the contested ones ("keep my saved answers"), which are the same sentence about
 * the same answers. The form goes back to what the server holds for them - nothing at all if they
 * have saved nothing - and the draft is destroyed rather than left to be put in front of the next
 * person to sit down at a shared tab.
 *
 * This is the only thing that deletes an unowned draft, and a person deciding about their own screen
 * is the only thing entitled to.
 */
function clearRestoredDraft() {
  store.discardDraftAnswers(marketSlug.value);
  draft.value = null;
  formData.value = savedAnswers();
  validationErrors.value = {};
}

function validateAll(): boolean {
  validationErrors.value = formValidationErrors(sortedFields.value, formData.value);
  return Object.keys(validationErrors.value).length === 0;
}

function clearFieldError(field: FormField) {
  if (validationErrors.value[field.key]) {
    validationErrors.value = { ...validationErrors.value, [field.key]: '' };
  }
}

/**
 * The button says what pressing it does. Signed out, it cannot save - there is nothing to save into
 * until the applicant has proved who they are - so it does not claim to: it takes them to sign in,
 * holding what they typed, and the Save they were promised is the one waiting for them on the other
 * side. A button labelled "Save" that saves nothing is how an applicant walks away from an
 * application that was never submitted, believing it was.
 */
const submitLabel = computed(() => {
  if (!signedIn.value) return 'Continue to sign in';
  return saving.value ? 'Saving...' : 'Save Application';
});

async function submitForm() {
  if (!validateAll()) return;

  saving.value = true;
  try {
    // If already authenticated for this market, save directly
    if (signedIn.value) {
      const ok = await store.saveApplication(marketSlug.value, formData.value);
      if (ok) saved.value = true;
      readDraft();
    } else {
      // Signing in is a redirect, and a redirect unmounts this form. The answers are handed to the
      // store *before* that happens, or the button that offers to carry the applicant to sign-in is
      // the one that loses everything they typed on the way.
      store.rememberDraftAnswers(marketSlug.value, formData.value);
      router.push({
        name: 'applicant-login',
        params: { marketSlug: marketSlug.value },
        query: { redirect: 'apply' },
      });
    }
  } finally {
    saving.value = false;
  }
}

function goToLogin() {
  router.push({
    name: 'applicant-login',
    params: { marketSlug: marketSlug.value },
    query: { redirect: 'dashboard' },
  });
}
</script>

<template>
  <div class="apply-page" data-testid="apply-page">
    <div v-if="loading" class="apply-loading" data-testid="apply-loading">
      Loading application form...
    </div>

    <div v-else-if="pageError" class="apply-error" data-testid="apply-error">
      <h2>Unable to Load Application</h2>
      <p>{{ pageError }}</p>
    </div>

    <template v-else>
      <header class="apply-header">
        <h1 data-testid="apply-market-name">Apply for {{ marketName || marketSlug }}</h1>
        <div class="phase-badge" :class="{ open: isOpen }" data-testid="apply-phase-badge">
          {{ isOpen ? 'Applications Open' : `Market Status: ${phaseLabel}` }}
        </div>
      </header>

      <div v-if="!isOpen" class="apply-closed" data-testid="apply-closed">
        <p>
          Applications are not currently open for this market.
          The market is in the <strong>{{ phaseLabel }}</strong> phase.
        </p>
      </div>

      <template v-else>
        <div v-if="!sortedFields.length" class="apply-no-form" data-testid="apply-no-form">
          <p>This market does not have an application form yet.</p>
        </div>

        <form
          v-else
          class="apply-form"
          @submit.prevent="submitForm"
          data-testid="apply-form"
        >
          <div v-if="saved" class="apply-saved" data-testid="apply-saved">
            Your application has been saved. You can return to
            <a href="#" @click.prevent="goToLogin">view or edit it</a> at any time.
          </div>

          <!-- Answers typed in this browser before anyone signed in, and an application already
               saved for the applicant who just did. They may be the same person - a returning vendor
               retyping their answers on the public link, which is the only URL they have - or a
               shared desk, where the answers are a stranger's and the saved application is this
               applicant's. Both are somebody's, so neither is touched and the question goes to the
               only party who can answer it. -->
          <div v-if="contestedDraft" class="apply-draft-notice" data-testid="apply-draft-choice">
            <p class="apply-draft-notice-text">
              Answers were entered on this device before you signed in, and you already have an
              application saved. We cannot tell whether you typed them, so
              <strong>nothing has been changed</strong> - the form below shows your saved answers.
            </p>
            <div class="apply-draft-notice-actions">
              <button
                type="button"
                class="apply-draft-keep-btn"
                @click="acceptContestedDraft"
                data-testid="apply-draft-choice-use-button"
              >
                They're mine - use them
              </button>
              <button
                type="button"
                class="apply-draft-clear-btn"
                @click="clearRestoredDraft"
                data-testid="apply-draft-choice-keep-saved-button"
              >
                Keep my saved answers
              </button>
            </div>
          </div>

          <!-- Answers typed in this browser before anyone signed in. They are back in the form,
               because they are almost always the answers of the person now reading it - but this
               device may be shared, and the product holds no evidence of who typed them, so it says
               so rather than submitting them for anybody. -->
          <div v-else-if="restoredDraftNotice" class="apply-draft-notice" data-testid="apply-draft-notice">
            <p class="apply-draft-notice-text">
              We put back the answers entered on this device before signing in.
              <strong>They have not been submitted yet</strong> - check them over and press
              "{{ submitLabel }}"{{ signedIn ? ' to submit them.' : ' to sign in and save them.' }}
            </p>
            <div class="apply-draft-notice-actions">
              <button
                type="button"
                class="apply-draft-keep-btn"
                @click="draftNoticeDismissed = true"
                data-testid="apply-draft-keep-button"
              >
                They're mine
              </button>
              <button
                type="button"
                class="apply-draft-clear-btn"
                @click="clearRestoredDraft"
                data-testid="apply-draft-clear-button"
              >
                Not mine - clear them
              </button>
            </div>
          </div>

          <ApplicationFormFields
            v-model="formData"
            :fields="sortedFields"
            :errors="validationErrors"
            prefix="apply"
            @field-change="clearFieldError"
          />

          <div v-if="store.error && !saving" class="apply-server-error" data-testid="apply-server-error">
            {{ store.error }}
          </div>

          <div class="apply-actions">
            <button
              type="submit"
              class="apply-submit-btn"
              :disabled="saving || !sortedFields.length"
              data-testid="apply-submit-button"
            >
              {{ submitLabel }}
            </button>
          </div>
        </form>
      </template>

      <!-- An applicant's own application outlives the window to change it, and the states the
           dashboard exists to show them are reachable only after that window closes. So the way
           back to it is not part of the open-applications branch. -->
      <div class="apply-returning" data-testid="apply-returning">
        Already applied?
        <a href="#" @click.prevent="goToLogin">Sign in to view your application</a>
      </div>
    </template>
  </div>
</template>

<style scoped>
.apply-page {
  max-width: 640px;
  margin: 40px auto;
  padding: 0 16px;
}

.apply-loading {
  text-align: center;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #999);
  padding: 40px;
}

.apply-error h2 {
  font-family: 'Merge One';
  font-size: 20px;
  color: var(--mm-red, #cc0000);
  margin-bottom: 8px;
}

.apply-error p {
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #666);
}

.apply-header {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 8px;
}

.apply-header h1 {
  font-family: 'Merge One';
  font-size: 24px;
  color: var(--mm-black);
  margin: 0;
}

.phase-badge {
  font-family: 'Outfit Regular';
  font-size: 12px;
  border-radius: 4px;
  padding: 4px 10px;
  background: #f0f0f0;
  color: var(--mm-grey, #666);
}

.phase-badge.open {
  background: var(--mm-green);
  color: white;
}

.apply-closed {
  background: #fff3cd;
  border: 1px solid #ffc107;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 24px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: #664d03;
}

.apply-no-form {
  text-align: center;
  padding: 40px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #999);
}

.apply-saved {
  background: #d4edda;
  border: 1px solid #28a745;
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 16px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: #155724;
}

.apply-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.apply-draft-notice {
  background: #e7f1ff;
  border: 1px solid #86b7fe;
  border-radius: 6px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.apply-draft-notice-text {
  margin: 0;
  font-family: 'Outfit Regular';
  font-size: 14px;
  line-height: 1.5;
  color: #084298;
}

.apply-draft-notice-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.apply-draft-keep-btn,
.apply-draft-clear-btn {
  border-radius: 5px;
  padding: 8px 16px;
  cursor: pointer;
  font-family: 'Merge One';
  font-size: 14px;
}

.apply-draft-keep-btn {
  background: var(--mm-green);
  color: white;
  border: none;
}

.apply-draft-clear-btn {
  background: transparent;
  color: #084298;
  border: 1px solid #86b7fe;
}

.apply-server-error {
  background: #f8d7da;
  border: 1px solid var(--mm-red, #cc0000);
  border-radius: 6px;
  padding: 12px 16px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: #721c24;
}

.apply-actions {
  display: flex;
  gap: 12px;
  padding-top: 8px;
}

.apply-submit-btn {
  background: var(--mm-green);
  color: white;
  border: none;
  border-radius: 5px;
  padding: 10px 24px;
  cursor: pointer;
  font-family: 'Merge One';
  font-size: 16px;
}

.apply-submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.apply-returning {
  margin-top: 24px;
  text-align: center;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #666);
}

.apply-returning a {
  color: var(--mm-green);
  text-decoration: none;
}

.apply-returning a:hover {
  text-decoration: underline;
}
</style>

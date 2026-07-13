<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useApplicationStore } from '@/stores/application';
import ApplicationFormFields from '@/components/application/ApplicationFormFields.vue';
import { getApiErrorMessage } from '@/utils/api';
import { formValidationErrors, sortedFormFields } from '@/utils/applicationForm';
import { fetchPublicApplicationForm } from '@/utils/publicApplicationForm';
import type { FormField } from '@/assets/types/datatypes';

const route = useRoute();
const router = useRouter();
const store = useApplicationStore();

const marketSlug = computed(() => (route.params.marketSlug as string) || '');
const loading = ref(true);
const editing = ref(false);

const formData = ref<Record<string, unknown>>({});
const validationErrors = ref<Record<string, string>>({});
const saving = ref(false);

// Application form fields for display and editing
const fields = ref<FormField[]>([]);
const marketName = ref('');
const phaseLabel = ref('');
const isOpen = ref(false);
const formError = ref<string | null>(null);

const sortedFields = computed(() => sortedFormFields(fields.value));

// The form fetch failing is fatal to this view even when the application itself loaded: without
// the field list the view branch renders a status and no answers, which reads as an empty
// application rather than a failure.
const loadError = computed(
  () => formError.value || (store.application ? null : store.error),
);

async function loadAll() {
  // A token for another market is not a session here: it would fetch that market's application and
  // render its answers against this market's labels.
  if (!store.isAuthenticatedFor(marketSlug.value)) {
    router.push({
      name: 'applicant-login',
      params: { marketSlug: marketSlug.value },
    });
    return;
  }

  loading.value = true;
  formError.value = null;
  try {
    await store.fetchApplication(marketSlug.value);
    // Fetch the form separately for display fields
    const form = await fetchPublicApplicationForm(marketSlug.value);
    fields.value = form.fields;
    marketName.value = form.marketName;
    phaseLabel.value = form.phaseLabel;
    isOpen.value = form.isOpen;
  } catch (err: unknown) {
    formError.value = getApiErrorMessage(
      err,
      'Failed to load the application form. Please try again.',
    );
  } finally {
    loading.value = false;
  }

  restorePendingEdits();
}

/**
 * The applicant pressed Save, the session had expired, and they signed back in and were sent here.
 * Their answers were written to the draft before that request went out (see `saveApplication`), so
 * they still exist - and this is what puts them back on screen, in the edit form they were typing
 * into, over the answers the server still has. Without it the draft would sit in storage while the
 * page rendered the stale saved copy, which is the data loss it exists to prevent, one step later.
 *
 * The save is not re-attempted for them: unlike the application page, where the applicant pressed a
 * button that promised to sign them in *and* save, an edit here is theirs to finish. The answers are
 * in front of them and Save is one press away.
 *
 * Only while the market is still open, because that is the only time an edit could be saved at all -
 * and the edit form is not reachable otherwise.
 */
function restorePendingEdits() {
  if (!isOpen.value || !store.application) return;

  const draft = store.draftAnswers(marketSlug.value);
  if (!draft || Object.keys(draft).length === 0) return;

  formData.value = { ...(store.application.formData || {}), ...draft };
  editing.value = true;
}

onMounted(loadAll);

// An application document exists from the moment the applicant asks for a login code, with the
// status the pipeline starts every application in. That is not a submission, and `submittedAt` -
// which the back end stamps on the first save and never again - is the only thing that records
// one. Reading the status alone headlines an untouched form as "Submitted" directly above a meta
// line reading "Not yet submitted".
const isSubmitted = computed(() => Boolean(store.application?.submittedAt));

// The status here is the applicant-facing one the server decided (`applicant_visible_status`): a
// reviewer's verdict never reaches this component, so there is nothing to hide at this layer and
// deliberately no second list of statuses to hide it with. Masking in a label was never masking -
// the payload still carried the verdict, and this component wrote it into the DOM.
const statusLabel = computed(() => {
  const s = store.application?.status;
  if (s === 'open' && !isSubmitted.value) return 'Not Submitted';
  const labels: Record<string, string> = {
    open: 'Submitted',
    under_review: 'Under Review',
    assignment_sent: 'Offer Sent',
    vendor_accepted: 'Confirmed',
    vendor_refused: 'Declined',
    cancelled: 'Cancelled',
  };
  return labels[s || ''] || (s || 'Unknown');
});

function startEditing() {
  formData.value = { ...(store.application?.formData || {}) };
  editing.value = true;
}

function cancelEditing() {
  // Cancelling is the applicant discarding these answers, so the draft holding them goes too -
  // otherwise the edit they just abandoned would be restored over their saved answers on the next
  // visit. See `discardDraftAnswers`; only an unfinished save leaves a draft behind.
  store.discardDraftAnswers(marketSlug.value);
  editing.value = false;
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

async function saveEdits() {
  if (!validateAll()) return;
  saving.value = true;
  const ok = await store.saveApplication(marketSlug.value, formData.value);
  saving.value = false;
  if (ok) editing.value = false;
}

function logout() {
  store.logout();
  router.push({
    name: 'apply',
    params: { marketSlug: marketSlug.value },
  });
}

function getFieldValue(field: FormField): string {
  const v = store.application?.formData?.[field.key];
  if (v === undefined || v === null || v === '') return '\u2014';
  if (Array.isArray(v)) return v.length ? v.join(', ') : '\u2014';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}
</script>

<template>
  <div class="dashboard-page" data-testid="applicant-dashboard-page">
    <header class="dash-header">
      <h1>Your Application</h1>
      <!-- The status belongs to the application, so it cannot be on screen before the application
           is: rendered outside the load guard it paints an "Unknown" chip on every visit, and
           leaves it above the error when the load fails - reporting a status for an application
           the page could not load. -->
      <span
        v-if="!loading && !loadError && store.application"
        class="dash-status"
        :class="{ 'dash-status-pending': !isSubmitted }"
        :data-testid="`applicant-dashboard-status-${store.application.status}`"
      >
        {{ statusLabel }}
      </span>
    </header>

    <p class="dash-market" data-testid="applicant-dashboard-market">
      {{ marketName || marketSlug }}
    </p>

    <div v-if="loading" class="dash-loading" data-testid="applicant-dashboard-loading">
      Loading your application...
    </div>

    <div v-else-if="loadError" class="dash-error" data-testid="applicant-dashboard-error">
      <p>{{ loadError }}</p>
      <button class="dash-btn dash-btn-primary" @click="loadAll()">Retry</button>
    </div>

    <template v-else-if="store.application">
      <!-- View mode -->
      <div v-if="!editing" class="dash-view" data-testid="applicant-dashboard-view">
        <p
          v-if="!isSubmitted"
          class="dash-unsubmitted"
          data-testid="applicant-dashboard-unsubmitted"
        >
          You have not submitted an application yet.
          {{ isOpen
            ? 'Fill in the form and save it to apply.'
            : `Applications are not open for this market (${phaseLabel} phase).` }}
        </p>

        <div
          v-for="field in sortedFields"
          :key="field.key"
          class="dash-field"
          :data-testid="`applicant-dashboard-field-${field.key}`"
        >
          <span class="dash-field-label">{{ field.label }}</span>
          <span class="dash-field-value">{{ getFieldValue(field) }}</span>
        </div>

        <div class="dash-meta">
          <span class="dash-meta-item">
            Submitted:
            {{ store.application.submittedAt
              ? new Date(store.application.submittedAt).toLocaleDateString()
              : 'Not yet submitted' }}
          </span>
          <span class="dash-meta-item">
            Updated:
            {{ store.application.updatedAt
              ? new Date(store.application.updatedAt).toLocaleDateString()
              : '\u2014' }}
          </span>
        </div>

        <div class="dash-actions">
          <button
            v-if="isOpen"
            class="dash-btn dash-btn-primary"
            @click="startEditing"
            data-testid="applicant-dashboard-edit-btn"
          >
            {{ isSubmitted ? 'Edit Application' : 'Complete Application' }}
          </button>
          <button
            class="dash-btn dash-btn-secondary"
            @click="logout"
            data-testid="applicant-dashboard-logout-btn"
          >
            Sign Out
          </button>
        </div>
      </div>

      <!-- Edit mode -->
      <div v-else class="dash-edit" data-testid="applicant-dashboard-edit">
        <div v-if="store.error" class="dash-error" data-testid="applicant-dashboard-server-error">
          {{ store.error }}
        </div>

        <ApplicationFormFields
          v-model="formData"
          :fields="sortedFields"
          :errors="validationErrors"
          prefix="applicant-dashboard-edit"
          @field-change="clearFieldError"
        />

        <div class="dash-actions">
          <button class="dash-btn dash-btn-primary" :disabled="saving" @click="saveEdits">
            {{ saving ? 'Saving...' : 'Save' }}
          </button>
          <button class="dash-btn dash-btn-secondary" @click="cancelEditing">
            Cancel
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dashboard-page {
  max-width: 640px;
  margin: 40px auto;
  padding: 0 16px;
}

.dash-header {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  flex-wrap: wrap;
  gap: 8px;
}

.dash-header h1 {
  font-family: 'Merge One';
  font-size: 24px;
  color: var(--mm-black);
  margin: 0;
}

.dash-status {
  font-family: 'Outfit Regular';
  font-size: 13px;
  border-radius: 4px;
  padding: 4px 10px;
  background: var(--mm-green);
  color: white;
}

.dash-status-pending {
  background: #f0f0f0;
  color: var(--mm-grey, #666);
}

.dash-unsubmitted {
  background: #fff3cd;
  border: 1px solid #ffc107;
  border-radius: 6px;
  padding: 12px 16px;
  margin: 0;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: #664d03;
}

.dash-market {
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #666);
  margin: 0 0 24px;
}

.dash-loading,
.dash-error {
  text-align: center;
  padding: 40px;
  font-family: 'Outfit Regular';
  font-size: 14px;
}

.dash-error p {
  color: var(--mm-red, #cc0000);
}

.dash-view,
.dash-edit {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dash-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dash-field-label {
  font-family: 'Outfit Regular';
  font-size: 12px;
  color: var(--mm-grey, #666);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.dash-field-value {
  font-family: 'Outfit Regular';
  font-size: 15px;
  color: var(--mm-black);
  word-break: break-word;
}

.dash-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 0;
  border-top: 1px solid var(--mm-grey, #eee);
  border-bottom: 1px solid var(--mm-grey, #eee);
}

.dash-meta-item {
  font-family: 'Outfit Regular';
  font-size: 12px;
  color: var(--mm-grey, #999);
}

.dash-actions {
  display: flex;
  flex-direction: row;
  gap: 12px;
  margin-top: 12px;
}

.dash-btn {
  padding: 10px 20px;
  border-radius: 5px;
  cursor: pointer;
  font-family: 'Merge One';
  font-size: 14px;
  border: none;
}

.dash-btn-primary {
  background: var(--mm-green);
  color: white;
}

.dash-btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dash-btn-secondary {
  background: transparent;
  color: var(--mm-grey, #666);
  border: 1px solid var(--mm-grey, #ccc);
}
</style>

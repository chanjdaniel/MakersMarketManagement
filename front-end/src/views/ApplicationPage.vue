<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { FormField } from '@/assets/types/datatypes';
import ApplicationFormFields from '@/components/application/ApplicationFormFields.vue';
import { getApiErrorMessage } from '@/utils/api';
import { formValidationErrors, sortedFormFields } from '@/utils/applicationForm';
import { fetchPublicApplicationForm } from '@/utils/publicApplicationForm';
import { useApplicationStore } from '@/stores/application';

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
  } finally {
    loading.value = false;
  }
});

// Prefill from the store if the applicant just verified. The application in the store belongs to
// the market its session was issued for, so it is only this page's to prefill from when that is
// this market: an application read under any other condition is another market's answers, copied
// into this form wherever the two forms share a field key.
watch(
  () => (signedIn.value ? store.application : null),
  (app) => {
    if (app?.formData && Object.keys(app.formData).length > 0) {
      formData.value = { ...app.formData };
    }
  },
  { immediate: true },
);

function validateAll(): boolean {
  validationErrors.value = formValidationErrors(sortedFields.value, formData.value);
  return Object.keys(validationErrors.value).length === 0;
}

function clearFieldError(field: FormField) {
  if (validationErrors.value[field.key]) {
    validationErrors.value = { ...validationErrors.value, [field.key]: '' };
  }
}

async function submitForm() {
  if (!validateAll()) return;

  saving.value = true;
  try {
    // If already authenticated for this market, save directly
    if (signedIn.value) {
      const ok = await store.saveApplication(marketSlug.value, formData.value);
      if (ok) saved.value = true;
    } else {
      // Not yet logged in -- redirect to login flow with market slug
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
              {{ saving ? 'Saving...' : (signedIn ? 'Save Application' : 'Save & Continue') }}
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

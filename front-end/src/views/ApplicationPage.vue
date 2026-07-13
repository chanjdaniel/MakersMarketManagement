<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { FormField, ApplicationForm } from '@/assets/types/datatypes';
import ApplicationFormFields from '@/components/application/ApplicationFormFields.vue';
import { getApiErrorMessage } from '@/utils/api';
import { applicantApi } from '@/utils/applicantApi';
import { formValidationErrors, sortedFormFields } from '@/utils/applicationForm';
import { useApplicationStore } from '@/stores/application';

const route = useRoute();
const router = useRouter();
const store = useApplicationStore();

const marketSlug = computed(() => (route.params.marketSlug as string) || '');

const applicationForm = ref<ApplicationForm | null>(null);
const phaseLabel = ref('');
const isOpen = ref(false);
const loading = ref(true);
const pageError = ref<string | null>(null);

const formData = ref<Record<string, unknown>>({});
const validationErrors = ref<Record<string, string>>({});
const saving = ref(false);
const saved = ref(false);

const sortedFields = computed(() => sortedFormFields(applicationForm.value?.fields ?? []));

onMounted(async () => {
  try {
    const { data } = await applicantApi.get(
      `/public/markets/${marketSlug.value}/application-form`,
    );
    if (data.application_form) {
      applicationForm.value = { fields: data.application_form.fields };
    }
    phaseLabel.value = data.phase_label || '';
    isOpen.value = data.is_open === true;
  } catch (err: unknown) {
    pageError.value = getApiErrorMessage(err, 'Failed to load the application form.');
  } finally {
    loading.value = false;
  }
});

// Prefill from store if the user just verified
watch(
  () => store.application,
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
    // If already authenticated, save directly
    if (store.isAuthenticated) {
      const ok = await store.saveApplication(formData.value);
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
        <h1>Apply for {{ marketSlug }}</h1>
        <div class="phase-badge" :class="{ open: isOpen }" data-testid="apply-phase-badge">
          {{ isOpen ? 'Applications Open' : `Market Status: ${phaseLabel}` }}
        </div>
      </header>

      <div v-if="!isOpen" class="apply-closed" data-testid="apply-closed">
        <p>
          Applications are not currently open for this market.
          The market is in the <strong>{{ phaseLabel }}</strong> phase.
        </p>
        <p v-if="store.isAuthenticated">
          You can still
          <a href="#" @click.prevent="goToLogin">view your existing application</a>.
        </p>
      </div>

      <template v-else>
        <div v-if="!applicationForm?.fields?.length" class="apply-no-form" data-testid="apply-no-form">
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
              {{ saving ? 'Saving...' : (store.isAuthenticated ? 'Save Application' : 'Save & Continue') }}
            </button>
          </div>
        </form>

        <div class="apply-returning">
          Already applied?
          <a href="#" @click.prevent="goToLogin">Sign in to view your application</a>
        </div>
      </template>
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

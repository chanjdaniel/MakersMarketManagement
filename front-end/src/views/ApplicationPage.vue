<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { FormField, ApplicationForm } from '@/assets/types/datatypes';
import { applicantApi } from '@/utils/applicantApi';
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

const sortedFields = computed(() => {
  if (!applicationForm.value?.fields) return [];
  return [...applicationForm.value.fields].sort((a, b) => a.order - b.order);
});

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
    const msg =
      (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
    pageError.value = msg || 'Failed to load the application form.';
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

function getFieldError(field: FormField): string {
  return validationErrors.value[field.key] || '';
}

function validateField(field: FormField): string {
  const value = formData.value[field.key];
  if (field.required && (value === undefined || value === null || (typeof value === 'string' && value.trim() === ''))) {
    return `${field.label} is required.`;
  }
  return '';
}

function validateAll(): boolean {
  const errors: Record<string, string> = {};
  if (!sortedFields.value.length) return true;
  for (const field of sortedFields.value) {
    const err = validateField(field);
    if (err) errors[field.key] = err;
  }
  validationErrors.value = errors;
  return Object.keys(errors).length === 0;
}

function onFieldChange(field: FormField, value: unknown) {
  formData.value = { ...formData.value, [field.key]: value };
  // Clear error on change
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

          <div
            v-for="field in sortedFields"
            :key="field.key"
            class="apply-field"
            :data-testid="`apply-field-${field.key}`"
          >
            <label class="apply-label" :for="`field-${field.key}`">
              {{ field.label }}
              <span v-if="field.required" class="apply-required">*</span>
            </label>

            <p v-if="field.helpText" class="apply-help">{{ field.helpText }}</p>

            <!-- text / email -->
            <input
              v-if="field.type === 'text' || field.type === 'email'"
              :id="`field-${field.key}`"
              class="apply-input"
              :class="{ error: getFieldError(field) }"
              :type="field.type === 'email' ? 'email' : 'text'"
              :value="(formData[field.key] as string) || ''"
              @input="onFieldChange(field, ($event.target as HTMLInputElement).value)"
              :data-testid="`apply-input-${field.key}`"
            />

            <!-- number -->
            <input
              v-else-if="field.type === 'number'"
              :id="`field-${field.key}`"
              class="apply-input"
              :class="{ error: getFieldError(field) }"
              type="number"
              :value="(formData[field.key] as string) || ''"
              @input="onFieldChange(field, ($event.target as HTMLInputElement).value)"
              :data-testid="`apply-input-${field.key}`"
            />

            <!-- date -->
            <input
              v-else-if="field.type === 'date'"
              :id="`field-${field.key}`"
              class="apply-input"
              :class="{ error: getFieldError(field) }"
              type="date"
              :value="(formData[field.key] as string) || ''"
              @input="onFieldChange(field, ($event.target as HTMLInputElement).value)"
              :data-testid="`apply-input-${field.key}`"
            />

            <!-- checkbox -->
            <label
              v-else-if="field.type === 'checkbox'"
              class="apply-checkbox-label"
            >
              <input
                type="checkbox"
                :checked="!!formData[field.key]"
                @change="onFieldChange(field, ($event.target as HTMLInputElement).checked)"
                :data-testid="`apply-input-${field.key}`"
              />
              <span>Yes</span>
            </label>

            <!-- select -->
            <select
              v-else-if="field.type === 'select'"
              :id="`field-${field.key}`"
              class="apply-input"
              :class="{ error: getFieldError(field) }"
              :value="(formData[field.key] as string) || ''"
              @change="onFieldChange(field, ($event.target as HTMLSelectElement).value)"
              :data-testid="`apply-input-${field.key}`"
            >
              <option value="">-- Select --</option>
              <option v-for="opt in field.options" :key="opt" :value="opt">
                {{ opt }}
              </option>
            </select>

            <!-- multi_select -->
            <div
              v-else-if="field.type === 'multi_select'"
              class="apply-multiselect"
              :class="{ error: getFieldError(field) }"
            >
              <label
                v-for="opt in field.options"
                :key="opt"
                class="apply-checkbox-label"
              >
                <input
                  type="checkbox"
                  :checked="((formData[field.key] as string[]) || []).includes(opt)"
                  @change="(e: Event) => {
                    const checked = (e.target as HTMLInputElement).checked;
                    const current = [...((formData[field.key] as string[]) || [])];
                    onFieldChange(
                      field,
                      checked ? [...current, opt] : current.filter((v: string) => v !== opt),
                    );
                  }"
                  :data-testid="`apply-input-${field.key}-${opt}`"
                />
                <span>{{ opt }}</span>
              </label>
            </div>

            <div v-else class="apply-unsupported">
              Unknown field type: {{ field.type }}
            </div>

            <p
              v-if="getFieldError(field)"
              class="apply-field-error"
              :data-testid="`apply-error-${field.key}`"
            >
              {{ getFieldError(field) }}
            </p>
          </div>

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

.apply-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.apply-label {
  font-family: 'Outfit Regular';
  font-size: 14px;
  font-weight: bold;
  color: var(--mm-black);
}

.apply-required {
  color: var(--mm-red, #cc0000);
}

.apply-help {
  font-family: 'Outfit Regular';
  font-size: 12px;
  color: var(--mm-grey, #666);
  margin: 0;
}

.apply-input {
  height: 36px;
  padding: 4px 10px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  border: 1px solid var(--mm-grey, #b0b0b0);
  border-radius: 5px;
  background: white;
}

.apply-input.error {
  border-color: var(--mm-red, #cc0000);
}

.apply-checkbox-label {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-black);
  cursor: pointer;
}

.apply-multiselect {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--mm-grey, #ddd);
  border-radius: 5px;
  background: white;
}

.apply-multiselect.error {
  border-color: var(--mm-red, #cc0000);
}

.apply-field-error {
  font-family: 'Outfit Regular';
  font-size: 12px;
  color: var(--mm-red, #cc0000);
  margin: 2px 0 0;
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

.apply-unsupported {
  font-family: 'Outfit Regular';
  font-size: 12px;
  color: var(--mm-red, #cc0000);
  font-style: italic;
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

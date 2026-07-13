<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useApplicationStore } from '@/stores/application';
import { applicantApi } from '@/utils/applicantApi';
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
const applicationForm = ref<FormField[]>([]);
const phaseLabel = ref('');
const isOpen = ref(false);

const sortedFields = computed(() => {
  return [...applicationForm.value].sort((a, b) => a.order - b.order);
});

async function loadAll() {
  if (!store.isAuthenticated) {
    router.push({
      name: 'applicant-login',
      params: { marketSlug: marketSlug.value },
    });
    return;
  }

  loading.value = true;
  try {
    await store.fetchApplication();
    // Fetch the form separately for display fields
    const { data } = await applicantApi.get(
      `/public/markets/${marketSlug.value}/application-form`,
    );
    if (data.application_form?.fields) {
      applicationForm.value = data.application_form.fields;
    }
    phaseLabel.value = data.phase_label || '';
    isOpen.value = data.is_open === true;
  } finally {
    loading.value = false;
  }
}

onMounted(loadAll);

const statusLabel = computed(() => {
  const s = store.application?.status;
  const labels: Record<string, string> = {
    open: 'Submitted',
    under_review: 'Under Review',
    reviewer_approved: 'Approved',
    reviewer_rejected: 'Not Accepted',
    unassigned: 'Not Assigned',
    assigned: 'Assigned',
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
  editing.value = false;
  validationErrors.value = {};
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
  for (const field of sortedFields.value) {
    const err = validateField(field);
    if (err) errors[field.key] = err;
  }
  validationErrors.value = errors;
  return Object.keys(errors).length === 0;
}

function onFieldChange(field: FormField, value: unknown) {
  formData.value = { ...formData.value, [field.key]: value };
  if (validationErrors.value[field.key]) {
    validationErrors.value = { ...validationErrors.value, [field.key]: '' };
  }
}

async function saveEdits() {
  if (!validateAll()) return;
  saving.value = true;
  const ok = await store.saveApplication(formData.value);
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
  if (v === undefined || v === null) return '\u2014';
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}

function getFieldError(field: FormField): string {
  return validationErrors.value[field.key] || '';
}
</script>

<template>
  <div class="dashboard-page" data-testid="applicant-dashboard-page">
    <header class="dash-header">
      <h1>Your Application</h1>
      <span
        class="dash-status"
        :data-testid="`applicant-dashboard-status-${store.application?.status}`"
      >
        {{ statusLabel }}
      </span>
    </header>

    <p class="dash-market" data-testid="applicant-dashboard-market">
      {{ marketSlug }}
    </p>

    <div v-if="loading" class="dash-loading" data-testid="applicant-dashboard-loading">
      Loading your application...
    </div>

    <div v-else-if="store.error && !store.application" class="dash-error" data-testid="applicant-dashboard-error">
      <p>{{ store.error }}</p>
      <button class="dash-btn dash-btn-primary" @click="loadAll()">Retry</button>
    </div>

    <template v-else-if="store.application">
      <!-- View mode -->
      <div v-if="!editing" class="dash-view" data-testid="applicant-dashboard-view">
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
            Edit Application
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

        <div
          v-for="field in sortedFields"
          :key="field.key"
          class="dash-field"
        >
          <label :for="`edit-${field.key}`" class="dash-field-label dash-field-label-big">
            {{ field.label }}
            <span v-if="field.required" class="dash-required">*</span>
          </label>

          <!-- text / email -->
          <input
            v-if="field.type === 'text' || field.type === 'email'"
            :id="`edit-${field.key}`"
            class="dash-input"
            :class="{ error: getFieldError(field) }"
            :type="field.type === 'email' ? 'email' : 'text'"
            :value="(formData[field.key] as string) || ''"
            @input="onFieldChange(field, ($event.target as HTMLInputElement).value)"
          />

          <!-- number -->
          <input
            v-else-if="field.type === 'number'"
            :id="`edit-${field.key}`"
            class="dash-input"
            :class="{ error: getFieldError(field) }"
            type="number"
            :value="(formData[field.key] as string) || ''"
            @input="onFieldChange(field, ($event.target as HTMLInputElement).value)"
          />

          <!-- date -->
          <input
            v-else-if="field.type === 'date'"
            :id="`edit-${field.key}`"
            class="dash-input"
            :class="{ error: getFieldError(field) }"
            type="date"
            :value="(formData[field.key] as string) || ''"
            @input="onFieldChange(field, ($event.target as HTMLInputElement).value)"
          />

          <!-- checkbox -->
          <label v-else-if="field.type === 'checkbox'" class="dash-checkbox-label">
            <input
              type="checkbox"
              :checked="!!formData[field.key]"
              @change="onFieldChange(field, ($event.target as HTMLInputElement).checked)"
            />
            <span>Yes</span>
          </label>

          <!-- select -->
          <select
            v-else-if="field.type === 'select'"
            :id="`edit-${field.key}`"
            class="dash-input"
            :class="{ error: getFieldError(field) }"
            :value="(formData[field.key] as string) || ''"
            @change="onFieldChange(field, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">-- Select --</option>
            <option v-for="opt in field.options" :key="opt" :value="opt">
              {{ opt }}
            </option>
          </select>

          <!-- multi_select -->
          <div v-else-if="field.type === 'multi_select'" class="dash-multiselect" :class="{ error: getFieldError(field) }">
            <label v-for="opt in field.options" :key="opt" class="dash-checkbox-label">
              <input
                type="checkbox"
                :checked="((formData[field.key] as string[]) || []).includes(opt)"
                @change="(e: Event) => {
                  const checked = (e.target as HTMLInputElement).checked;
                  const current = [...((formData[field.key] as string[]) || [])];
                  onFieldChange(field, checked ? [...current, opt] : current.filter((v: string) => v !== opt));
                }"
              />
              <span>{{ opt }}</span>
            </label>
          </div>

          <p v-if="getFieldError(field)" class="dash-field-error">
            {{ getFieldError(field) }}
          </p>
        </div>

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

.dash-field-label-big {
  font-size: 14px;
  color: var(--mm-black);
  text-transform: none;
  font-weight: bold;
}

.dash-field-value {
  font-family: 'Outfit Regular';
  font-size: 15px;
  color: var(--mm-black);
  word-break: break-word;
}

.dash-required {
  color: var(--mm-red, #cc0000);
}

.dash-input {
  height: 36px;
  padding: 4px 10px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  border: 1px solid var(--mm-grey, #b0b0b0);
  border-radius: 5px;
}

.dash-input.error {
  border-color: var(--mm-red, #cc0000);
}

.dash-checkbox-label {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  cursor: pointer;
}

.dash-multiselect {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--mm-grey, #ddd);
  border-radius: 5px;
  background: white;
}

.dash-multiselect.error {
  border-color: var(--mm-red, #cc0000);
}

.dash-field-error {
  font-family: 'Outfit Regular';
  font-size: 12px;
  color: var(--mm-red, #cc0000);
  margin: 2px 0 0;
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

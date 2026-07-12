<script setup lang="ts">
import { computed, onMounted, reactive, nextTick, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import ElementSettingContainer from '@/components/elements/ElementSettingContainer.vue';
import ElementSetupColumns from '@/components/elements/ElementSetupColumns.vue';
import ElementMarketDates from '@/components/elements/ElementMarketDates.vue';
import ElementAssignmentPriority from '@/components/elements/ElementAssignmentPriority.vue';
import ElementAssignmentOptions from '@/components/elements/ElementAssignmentOptions.vue';
import ElementTierSetup from '@/components/elements/ElementTierSetup.vue';
import ElementLocationSetup from '@/components/elements/ElementLocationSetup.vue';
import ElementSectionSetup from '@/components/elements/ElementSectionSetup.vue';
import ChoosePathOverlay from '@/components/floorplan/ChoosePathOverlay.vue';
import { type SetupObject, type Market, type ApplicationForm } from '@/assets/types/datatypes';
import { api, getApiErrorMessage, getApiErrorStatus } from '@/utils/api';
import FormBuilder from '@/components/application/FormBuilder.vue';
import FormPreview from '@/components/application/FormPreview.vue';

const router = useRouter();

const showPathChoice = ref(false);
const activeTab = ref<'form' | 'setup'>('setup');

const market = ref<Market | null>(null);
const applicationForm = ref<ApplicationForm | null>(null);
const formSaveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle');
const formErrorMessage = ref<string | null>(null);
const formLockReason = ref<string | null>(null);
const formLoadError = ref<string | null>(null);
const formLocked = computed(() => formLockReason.value !== null);
/**
 * Only edit a form we know to be editable. A failed load leaves the lock state unknown, and
 * assuming "editable" there invites the organizer to rework a locked form and lose it to a 409.
 */
const formEditable = computed(() => !formLocked.value && formLoadError.value === null);
const setupObject = reactive<SetupObject>({
    colNames: [],
    colValues: [],
    colInclude: [],
    enumPriorityOrder: [],
    priority: [],
    marketDates: [],
    tiers: [],
    locations: [],
    sections: [],
    assignmentOptions: {
        maxAssignmentsPerVendor: null,
        maxHalfTableProportionPerSection: null,
        emailColNameIdx: null,
        tableChoiceColNameIdx: null,
        tableShareEmailColNameIdx: null,
        maxDaysColNameIdx: null,
    },
});

const pageIdx = ref(0);
const maxPageIdx = 2;

function parseFiniteInt(v: unknown): number | null {
    if (v === null || v === undefined || v === '') return null;
    const n = typeof v === 'string' ? parseInt(v, 10) : Number(v);
    return Number.isFinite(n) ? Math.floor(n) : null;
}

function parseFiniteNumber(v: unknown): number | null {
    if (v === null || v === undefined || v === '') return null;
    const n = typeof v === 'string' ? parseFloat(v) : Number(v);
    return Number.isFinite(n) ? n : null;
}

/** True when required Assignment Options are set (Assign enabled). Max days column mapping is optional. */
const assignmentOptionsComplete = computed(() => {
    const ao = setupObject.assignmentOptions;
    const numCols = setupObject.colNames.length;
    const numMarketDates = setupObject.marketDates.length;

    const maxPer = parseFiniteInt(ao.maxAssignmentsPerVendor);
    if (maxPer === null || maxPer < 1) return false;
    if (numMarketDates > 0 && maxPer > numMarketDates) return false;

    const halfProp = parseFiniteNumber(ao.maxHalfTableProportionPerSection);
    if (halfProp === null || halfProp < 0 || halfProp > 100) return false;

    const idxValid = (idx: number | null | undefined) =>
        idx !== null &&
        idx !== undefined &&
        Number.isInteger(idx) &&
        idx >= 0 &&
        numCols > 0 &&
        idx < numCols;

    if (!idxValid(ao.emailColNameIdx)) return false;
    if (!idxValid(ao.tableChoiceColNameIdx)) return false;
    if (!idxValid(ao.tableShareEmailColNameIdx)) return false;
    // maxDaysColNameIdx optional: null = backend applies no per-vendor max-days cap from CSV

    return true;
});

onMounted(() => {
    // create setup object

    market.value = JSON.parse(localStorage.getItem("market") || "null");
    if (market.value && market.value.setupObject) {
        Object.assign(setupObject, market.value.setupObject);

    } else {
        const inputDataJSON = localStorage.getItem("upload") || "{}";
        const inputData = JSON.parse(inputDataJSON);

        const colNames = Array.isArray(inputData?.data?.meta?.fields) ? inputData.data.meta.fields : [];
        const colInclude = new Array(colNames.length).fill(false);
        const uploadObjectJSON = localStorage.getItem("upload") || "{}";
        const uploadObject = JSON.parse(uploadObjectJSON);
        const uploadColNames = uploadObject.data.meta.fields;
        const uploadRows = uploadObject.data.data;
        const colValuesList: string[][] = [];
        const enumPriorityOrder: string[][] = [];
        for (let i = 0; i < colNames.length; i++) {

            const columnValues: string[] = [];
            for (let j = 0; j < uploadRows.length; j++) {
                const uploadColName = uploadColNames[i];
                const uploadRow = uploadObject.data.data[j];
                columnValues.push(uploadRow[uploadColName]);
            }
            colValuesList.push([...new Set(columnValues.filter(v => v != null))]);
            enumPriorityOrder.push([]);
        }

        const newSetupObject: SetupObject = {
            colNames: colNames,
            colValues: colValuesList,
            colInclude: colInclude,
            enumPriorityOrder: enumPriorityOrder,
            priority: [],
            marketDates: [],
            tiers: [],
            locations: [],
            sections: [],
            assignmentOptions: {
                maxAssignmentsPerVendor: null,
                maxHalfTableProportionPerSection: null,
                emailColNameIdx: null,
                tableChoiceColNameIdx: null,
                tableShareEmailColNameIdx: null,
                maxDaysColNameIdx: null,
            },
        };

        Object.assign(setupObject, newSetupObject);
        market.value!.setupObject = newSetupObject;
        localStorage.setItem("market", JSON.stringify(market.value));
    }

    // retrieve view state
    const setupPageIdx = JSON.parse(localStorage.getItem("setupPageIdx") || "null");
    pageIdx.value = setupPageIdx === null ? 0 : setupPageIdx;

    // Paint the cached form immediately, then reconcile with the server, which also
    // tells us whether the form is still editable.
    applicationForm.value = market.value?.applicationForm ?? null;
    loadApplicationForm();
});

/** The market document is the single source of truth for the form; keep it in step. */
function adoptApplicationForm(form: ApplicationForm | null) {
    applicationForm.value = form;
    if (market.value) {
        market.value.applicationForm = form ?? undefined;
        localStorage.setItem("market", JSON.stringify(market.value));
    }
}

async function loadApplicationForm() {
    if (!market.value?.id) return;
    formLoadError.value = null;
    try {
        const response = await api.get(`/markets/${market.value.id}/application-form`);
        adoptApplicationForm(response.data?.application_form ?? null);
        formLockReason.value = response.data?.lock_reason ?? null;
    } catch (err: unknown) {
        formLoadError.value = getApiErrorMessage(
            err,
            'Could not load the application form. Retry before editing it.',
        );
    }
}

/** A form with no fields yet is an untouched starting state, not a mistake to flag. */
const formIsEmpty = computed(() => (applicationForm.value?.fields ?? []).length === 0);

/** The charset the back-end holds field keys to; they become document keys on every answer. */
const FIELD_KEY_PATTERN = /^[a-z0-9_]+$/;

/**
 * Field keys and select options are the primary key and the persisted values of every
 * applicant's answers, so the back-end rejects blank, duplicate, or unaddressable ones. Say so
 * before the organizer clicks Save.
 */
const formValidationError = computed<string | null>(() => {
    const fields = applicationForm.value?.fields ?? [];

    const seen = new Set<string>();
    for (const field of fields) {
        const key = (field.key ?? '').trim();
        if (!field.label?.trim()) return 'Every field needs a label.';
        if (!key) return `Field "${field.label}" needs a key.`;
        if (!FIELD_KEY_PATTERN.test(key)) {
            return `Key "${key}" is invalid. Use lowercase letters, numbers, and underscores only.`;
        }
        if (seen.has(key)) return `Duplicate field key "${key}". Keys must be unique.`;
        seen.add(key);

        if (field.type === 'select' || field.type === 'multi_select') {
            if (field.options.length === 0) {
                return `Field "${field.label}" is a ${field.type} and needs at least one option.`;
            }
            const seenOptions = new Set<string>();
            for (const option of field.options) {
                const value = option.trim();
                if (!value) return `Field "${field.label}" has a blank option.`;
                if (seenOptions.has(value)) {
                    return `Field "${field.label}" repeats the option "${value}". Options must be unique.`;
                }
                seenOptions.add(value);
            }
        }
    }
    return null;
});

const canSaveForm = computed(
    () =>
        formEditable.value &&
        !formIsEmpty.value &&
        formValidationError.value === null &&
        formSaveStatus.value !== 'saving',
);

async function saveApplicationForm() {
    if (!market.value?.id || !canSaveForm.value) return;
    formSaveStatus.value = 'saving';
    formErrorMessage.value = null;
    try {
        const response = await api.put(
            `/markets/${market.value.id}/application-form`,
            applicationForm.value,
        );
        formSaveStatus.value = 'saved';
        if (response.data?.application_form) {
            adoptApplicationForm(response.data.application_form);
        }
        setTimeout(() => { if (formSaveStatus.value === 'saved') formSaveStatus.value = 'idle'; }, 2000);
    } catch (err: unknown) {
        formSaveStatus.value = 'error';
        formErrorMessage.value = getApiErrorMessage(err, 'Failed to save form');
        // A 409 means the server locked the form under us; stop presenting the rejected edits as
        // editable, and put back the form applicants will actually see.
        if (getApiErrorStatus(err) === 409) {
            formLockReason.value = formErrorMessage.value;
            await loadApplicationForm();
        }
    }
}

const updateMarket = async () => {
    localStorage.setItem("market", JSON.stringify(market.value));
    await api.put('/markets/' + market.value!.id, market.value);
}

const handleDiscordWebhookInput = (event: Event) => {
    if (!market.value) return;
    const value = (event.target as HTMLInputElement).value;
    const trimmed = value.trim();
    market.value.discordWebhookUrl = trimmed === '' ? null : value;
    localStorage.setItem('market', JSON.stringify(market.value));
};

const handleUpdateSetupObject = (newSetupObject: SetupObject) => {
    nextTick(() => {
        if (market.value) {
            Object.assign(setupObject, newSetupObject);
            market.value.setupObject = newSetupObject;
            localStorage.setItem("market", JSON.stringify(market.value));
        }
    });
};

const handleNext = async () => {
    pageIdx.value = pageIdx.value === maxPageIdx ? maxPageIdx : pageIdx.value + 1;
    localStorage.setItem("setupPageIdx", JSON.stringify(pageIdx.value));
    await updateMarket();
}
const handleBack = async () => {
    pageIdx.value = pageIdx.value === 0 ? 0 : pageIdx.value - 1;
    localStorage.setItem("setupPageIdx", JSON.stringify(pageIdx.value));
    await updateMarket();
}
const handleAssign = async () => {
    if (!assignmentOptionsComplete.value) {
        return;
    }
    await updateMarket();

    const response = await api.get('/markets/' + market.value!.id + '/assignment')

    const assignedMarket: Market = response.data;
    market.value = assignedMarket;
    await updateMarket();

    router.push("/assignment-results");
}

function handlePathChoice(path: 'manual' | 'floorplan') {
  showPathChoice.value = false
  if (path === 'floorplan') {
    router.push({
      path: '/floorplan-editor',
      query: { marketId: market.value?.id },
    })
  }
  // For 'manual': just hide overlay, existing text-based UI is already underneath
}

// Show path choice overlay when entering sections page with empty sections
watch(pageIdx, (newIdx) => {
  if (
    newIdx === 1 &&
    setupObject.sections.length === 0 &&
    (!setupObject.floorplans || setupObject.floorplans.length === 0)
  ) {
    showPathChoice.value = true
  }
})

</script>

<template>
    <div class="market-setup-view">
        <ChoosePathOverlay v-if="showPathChoice" @select="handlePathChoice" />
        <div class="market-setup-body">
            <div class="settings-container">
                <div class="settings-header">
                    <h1>Settings</h1>
                    <div class="tab-bar">
                        <button
                            :class="['tab-button', { active: activeTab === 'form' }]"
                            @click="activeTab = 'form'"
                            data-testid="market-setup-form-tab"
                        >
                            Application Form
                        </button>
                        <button
                            :class="['tab-button', { active: activeTab === 'setup' }]"
                            @click="activeTab = 'setup'"
                            data-testid="market-setup-setup-tab"
                        >
                            Market Setup
                        </button>
                    </div>
                </div>

                <!-- Application Form Tab -->
                <div v-if="activeTab === 'form'" class="settings-body">
                    <div class="double-column-body">
                        <ElementSettingContainer>
                            <template #setting-title>
                                <h2>Form Builder</h2>
                            </template>
                            <template #setting-content>
                                <div class="form-builder-container">
                                    <div
                                        v-if="formLocked"
                                        class="form-lock-banner"
                                        data-testid="form-builder-lock-banner"
                                    >
                                        {{ formLockReason }}
                                    </div>
                                    <div
                                        v-else-if="formLoadError"
                                        class="form-load-error-banner"
                                        data-testid="form-builder-load-error"
                                    >
                                        <span>{{ formLoadError }}</span>
                                        <button
                                            class="retry-button"
                                            @click="loadApplicationForm()"
                                            data-testid="form-builder-retry-button"
                                        >
                                            Retry
                                        </button>
                                    </div>
                                    <FormBuilder
                                        :applicationForm="applicationForm"
                                        :readonly="!formEditable"
                                        @update:applicationForm="(form: ApplicationForm) => applicationForm = form"
                                    />
                                    <div v-if="formEditable" class="form-save-row">
                                        <button
                                            class="done-button"
                                            :disabled="!canSaveForm"
                                            @click="saveApplicationForm()"
                                            data-testid="form-builder-save-button"
                                        >
                                            {{ formSaveStatus === 'saving' ? 'Saving...' : 'Save Form' }}
                                        </button>
                                        <span
                                            v-if="formValidationError"
                                            class="save-status error"
                                            data-testid="form-builder-validation-error"
                                        >
                                            {{ formValidationError }}
                                        </span>
                                        <span
                                            v-else-if="formSaveStatus === 'saved'"
                                            class="save-status success"
                                            data-testid="form-builder-save-success"
                                        >
                                            Saved
                                        </span>
                                        <span
                                            v-else-if="formSaveStatus === 'error'"
                                            class="save-status error"
                                            data-testid="form-builder-save-error"
                                        >
                                            {{ formErrorMessage }}
                                        </span>
                                    </div>
                                </div>
                            </template>
                        </ElementSettingContainer>
                        <ElementSettingContainer>
                            <template #setting-title>
                                <h2>Preview</h2>
                            </template>
                            <template #setting-content>
                                <FormPreview :applicationForm="applicationForm" />
                            </template>
                        </ElementSettingContainer>
                    </div>
                </div>

                <!-- Market Setup Tab (existing wizard) -->
                <div v-if="activeTab === 'setup'" class="settings-body">
                    <template v-if="pageIdx === 0">
                        <div class="double-column-body">
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Manage Columns</h2>
                                </template>
                                <template #setting-content>
                                    <ElementSetupColumns :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Market Dates</h2>
                                </template>
                                <template #setting-content>
                                    <ElementMarketDates :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                        </div>
                    </template>

                    <template v-else-if="pageIdx === 1">
                        <div class="triple-column-body">
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Tier Setup</h2>
                                </template>
                                <template #setting-content>
                                    <ElementTierSetup :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Location Setup</h2>
                                </template>
                                <template #setting-content>
                                    <ElementLocationSetup :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Section Setup</h2>
                                </template>
                                <template #setting-content>
                                    <ElementSectionSetup :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                        </div>
                    </template>

                    <template v-else-if="pageIdx === 2">
                        <div class="double-column-body-asymmetric">
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Assignment Priority</h2>
                                </template>
                                <template #setting-content>
                                    <ElementAssignmentPriority :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Assignment Options</h2>
                                </template>
                                <template #setting-content>
                                    <ElementAssignmentOptions :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                        </div>
                    </template>

                    <template v-else>
                        <h1>Something went wrong!</h1>
                    </template>
                </div>
            </div>
            <div v-if="activeTab === 'setup'" class="discord-webhook-row">
                <label class="discord-webhook-label" for="discord-webhook-url">Discord webhook URL</label>
                <input
                    id="discord-webhook-url"
                    type="url"
                    class="discord-webhook-input"
                    placeholder="https://discord.com/api/webhooks/..."
                    :value="market?.discordWebhookUrl ?? ''"
                    @input="handleDiscordWebhookInput"
                    @change="updateMarket"
                    data-testid="market-setup-discord-webhook-input"
                />
            </div>
            <div v-if="activeTab === 'setup'" style="width: 100%; display: flex; flex-direction: row; justify-content: space-between;">
                <div>
                    <button v-if="pageIdx !== 0" class="done-button" @click="handleBack" data-testid="market-setup-back-button">Back</button>
                </div>
                <div>
                    <button
                        v-if="pageIdx === maxPageIdx"
                        type="button"
                        class="done-button"
                        :disabled="!assignmentOptionsComplete"
                        :title="assignmentOptionsComplete ? '' : 'Complete required assignment options (max assignments, proportion, and column mappings; Max days is optional)'"
                        @click="handleAssign"
                        data-testid="market-setup-assign-button"
                    >
                        Assign
                    </button>
                    <button v-else class="done-button" @click="handleNext" data-testid="market-setup-next-button">Next</button>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.market-setup-view {
    width: 100%;
    min-width: 1000px;
    flex: 1;

    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}

.market-setup-body {
    width: 80%;
    height: 80%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}

.settings-container {
    align-self: stretch;
    flex: 1;
    background-color: white;
    box-shadow: 0px 0px 4px 5px rgba(0, 0, 0, 0.25);
    display: flex;
    flex-direction: column;
}

.settings-right-container {
    display: grid;
    grid-template-rows: 48% 4% 48%;
}

.settings-header {
    align-self: stretch;
    height: 50px;
    background-color: var(--mm-black);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    padding: 0 20px;
}

.tab-bar {
    display: flex;
    flex-direction: row;
    gap: 2px;
}

.tab-button {
    padding: 6px 16px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    font-family: 'Outfit Regular';
    font-size: 14px;
    color: #999;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
}

.tab-button:hover {
    color: #ddd;
}

.tab-button.active {
    color: white;
    border-bottom-color: var(--mm-green);
}

.settings-body {
    align-self: stretch;
    flex-grow: 1;
    display: flex;
    gap: 30px;
    padding: 40px;
    min-height: 0;
    flex: 1;
}

.single-column-body {
    align-self: stretch;
    flex-grow: 1;
    display: grid;
    grid-template-columns: 1fr;
    gap: 30px;
    min-height: 0;
    flex: 1;
}

.double-column-body {
    align-self: stretch;
    flex-grow: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 30px;
    min-height: 0;
    flex: 1;
}

.double-column-body-asymmetric {
    align-self: stretch;
    flex-grow: 1;
    display: grid;
    grid-template-columns: 3fr 2fr;
    gap: 30px;
    min-height: 0;
    flex: 1;
}

.triple-column-body {
    align-self: stretch;
    flex-grow: 1;
    display: grid;
    grid-template-columns: 1fr 1fr 2fr;
    gap: 30px;
    min-height: 0;
    flex: 1;
}

h1 {
    font-family: 'Outfit Regular';
    text-align: center;
    font-size: 30px;
    color: white;
}

h2 {
    font-family: 'Merge One';
    text-align: left;
    font-size: 20px;
    color: white;
}

.done-button {
    margin-top: 15px;
    width: 100px;
    height: 35px;

    background: var(--mm-green);
    border-radius: 5px;
    border: none;

    font-family: 'Merge One';
    font-style: normal;
    font-weight: 400;
    font-size: 20px;
    line-height: 15px;
    text-align: center;

    color: #FFFFFF;
}

.done-button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
}

.discord-webhook-row {
    width: 100%;
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 12px;
    margin-top: 15px;
}

.discord-webhook-label {
    font-family: 'Outfit Regular';
    font-size: 14px;
    color: var(--mm-black);
    white-space: nowrap;
}

.discord-webhook-input {
    flex: 1;
    height: 32px;
    padding: 4px 10px;
    font-family: 'Outfit Regular';
    font-size: 14px;
    border: 1px solid var(--mm-grey, #b0b0b0);
    border-radius: 5px;
    background-color: white;
}

.form-builder-container {
    display: flex;
    flex-direction: column;
    gap: 10px;
    height: 100%;
    overflow-y: auto;
}

.form-save-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 12px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--mm-grey, #eee);
}

.form-lock-banner {
    font-family: 'Outfit Regular';
    font-size: 13px;
    line-height: 1.4;
    color: #7a5200;
    background: #fff6e0;
    border: 1px solid #f0d089;
    border-radius: 6px;
    padding: 10px 12px;
}

.form-load-error-banner {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-family: 'Outfit Regular';
    font-size: 13px;
    line-height: 1.4;
    color: #8a1f1f;
    background: #fdeaea;
    border: 1px solid #f0a9a9;
    border-radius: 6px;
    padding: 10px 12px;
}

.retry-button {
    flex-shrink: 0;
    background: none;
    border: 1px solid #8a1f1f;
    color: #8a1f1f;
    border-radius: 4px;
    padding: 3px 12px;
    cursor: pointer;
    font-family: 'Outfit Regular';
    font-size: 12px;
}

.retry-button:hover {
    background: #8a1f1f;
    color: white;
}

.save-status {
    font-family: 'Outfit Regular';
    font-size: 13px;
}

.save-status.success {
    color: var(--mm-green);
}

.save-status.error {
    color: var(--mm-red, #cc0000);
}
</style>
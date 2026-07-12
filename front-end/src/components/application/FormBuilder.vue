<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import draggable from 'vuedraggable';
import { type FormField, type ApplicationForm } from '@/assets/types/datatypes';
import FormFieldEditor from './FormFieldEditor.vue';
import IconAddRound from '@/components/icons/IconAddRound.vue';
import IconClickDrag from '@/components/icons/IconClickDrag.vue';

const props = defineProps<{
  applicationForm: ApplicationForm | null;
}>();

const emit = defineEmits<{
  'update:applicationForm': [form: ApplicationForm];
}>();

const fields = ref<FormField[]>(props.applicationForm?.fields ?? []);

watch(
  () => props.applicationForm,
  (newForm) => {
    if (newForm) {
      fields.value = [...newForm.fields];
    }
  },
  { deep: true },
);

watch(
  fields,
  (newFields) => {
    emit('update:applicationForm', {
      fields: newFields,
      publishedAt: props.applicationForm?.publishedAt,
    });
  },
  { deep: true },
);

const nextOrder = computed(() =>
  fields.value.length > 0
    ? Math.max(...fields.value.map((f) => f.order)) + 1
    : 0,
);

function addField() {
  const idx = fields.value.length + 1;
  const newField: FormField = {
    key: `field_${idx}`,
    label: '',
    type: 'text',
    required: false,
    options: [],
    helpText: undefined,
    order: nextOrder.value,
  };
  fields.value.push(newField);
}

function removeField(index: number) {
  fields.value.splice(index, 1);
}

function updateField(index: number, field: FormField) {
  fields.value[index] = field;
}

function onDragEnd() {
  fields.value.forEach((f, i) => {
    f.order = i;
  });
  emit('update:applicationForm', {
    fields: fields.value,
    publishedAt: props.applicationForm?.publishedAt,
  });
}

const fieldCount = computed(() => fields.value.length);
</script>

<template>
  <div class="form-builder" data-testid="form-builder">
    <div class="builder-header">
      <span class="field-count">
        {{ fieldCount }} field{{ fieldCount !== 1 ? 's' : '' }}
      </span>
      <button
        class="add-field-btn"
        @click="addField"
        data-testid="form-builder-add-field-button"
      >
        <IconAddRound /> Add Field
      </button>
    </div>

    <div v-if="fields.length === 0" class="empty-state" data-testid="form-builder-empty">
      <p>No fields yet. Click "Add Field" to start building your application form.</p>
    </div>

    <draggable
      v-else
      v-model="fields"
      item-key="order"
      handle=".drag-handle"
      ghost-class="drag-ghost"
      @end="onDragEnd"
      data-testid="form-builder-field-list"
    >
      <template #item="{ element, index }">
        <div class="field-item">
          <div class="drag-handle" data-testid="form-builder-drag-handle">
            <IconClickDrag />
          </div>
          <div class="field-card">
            <div class="field-card-header">
              <span class="field-ordinal">{{ index + 1 }}.</span>
              <span class="field-label-preview">{{ element.label || '(untitled)' }}</span>
              <span class="field-type-badge">{{ element.type }}</span>
              <span v-if="element.required" class="required-badge">required</span>
              <button
                class="remove-btn"
                @click="removeField(index)"
                data-testid="form-builder-remove-field-button"
              >
                Remove
              </button>
            </div>
            <FormFieldEditor
              :field="element"
              :index="index"
              @update:field="(f: FormField) => updateField(index, f)"
              @remove="removeField(index)"
            />
          </div>
        </div>
      </template>
    </draggable>
  </div>
</template>

<style scoped>
.form-builder {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.builder-header {
  display: flex;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
}

.field-count {
  font-family: 'Outfit Regular';
  font-size: 13px;
  color: var(--mm-grey, #666);
}

.add-field-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--mm-green);
  color: white;
  border: none;
  border-radius: 5px;
  padding: 6px 14px;
  cursor: pointer;
  font-family: 'Merge One';
  font-size: 14px;
}

.empty-state {
  text-align: center;
  padding: 40px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #999);
}

.field-item {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 8px;
}

.drag-handle {
  cursor: grab;
  padding: 10px 4px;
  color: var(--mm-grey, #999);
  display: flex;
  align-items: center;
}

.drag-handle:active {
  cursor: grabbing;
}

.field-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-card-header {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

.field-ordinal {
  font-family: 'Outfit Regular';
  font-size: 13px;
  font-weight: bold;
  color: var(--mm-black);
}

.field-label-preview {
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-black);
  flex: 1;
}

.field-type-badge {
  font-family: 'Outfit Regular';
  font-size: 11px;
  background: #e8e8e8;
  color: #555;
  border-radius: 3px;
  padding: 1px 6px;
}

.required-badge {
  font-family: 'Outfit Regular';
  font-size: 11px;
  background: var(--mm-red, #cc0000);
  color: white;
  border-radius: 3px;
  padding: 1px 6px;
}

.remove-btn {
  background: none;
  border: 1px solid var(--mm-red, #cc0000);
  color: var(--mm-red, #cc0000);
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-family: 'Outfit Regular';
  font-size: 12px;
}

.remove-btn:hover {
  background: var(--mm-red, #cc0000);
  color: white;
}

.drag-ghost {
  opacity: 0.4;
}
</style>

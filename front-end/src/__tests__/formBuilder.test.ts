import { describe, it, expect, vi, afterEach } from 'vitest';
import { defineComponent, h, ref } from 'vue';
import { mount } from '@vue/test-utils';

import FormBuilder from '@/components/application/FormBuilder.vue';
import type { ApplicationForm } from '@/assets/types/datatypes';

/** Mirrors how MarketSetupView owns the form: child emits, parent re-feeds it as a prop. */
function mountWithParent(initial: ApplicationForm | null, readonly = false) {
  const form = ref<ApplicationForm | null>(initial);

  const Parent = defineComponent({
    setup() {
      return () =>
        h(FormBuilder, {
          applicationForm: form.value,
          readonly,
          'onUpdate:applicationForm': (next: ApplicationForm) => {
            form.value = next;
          },
        });
    },
  });

  return { wrapper: mount(Parent), form };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('FormBuilder', () => {
  it('does not re-enter its own updates when the parent feeds the form back', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { wrapper, form } = mountWithParent(null);

    await wrapper.get('[data-testid="form-builder-add-field-button"]').trigger('click');
    await wrapper.get('[data-testid="form-field-label-input"]').setValue('Business Name');
    await wrapper.get('[data-testid="form-builder-add-field-button"]').trigger('click');

    expect(form.value?.fields).toHaveLength(2);
    const recursive = warn.mock.calls.filter((c) =>
      String(c[0]).includes('Maximum recursive updates'),
    );
    expect(recursive).toEqual([]);
  });

  it('derives the key from the label on blur', async () => {
    const { wrapper, form } = mountWithParent(null);

    await wrapper.get('[data-testid="form-builder-add-field-button"]').trigger('click');
    expect(form.value?.fields[0].key).toBe('');

    const label = wrapper.get('[data-testid="form-field-label-input"]');
    await label.setValue('Business Name!');
    await label.trigger('blur');

    expect(form.value?.fields[0].key).toBe('business_name');
  });

  it('never overwrites a hand-edited key', async () => {
    const { wrapper, form } = mountWithParent(null);

    await wrapper.get('[data-testid="form-builder-add-field-button"]').trigger('click');
    await wrapper.get('[data-testid="form-field-key-input"]').setValue('custom_key');

    const label = wrapper.get('[data-testid="form-field-label-input"]');
    await label.setValue('Business Name');
    await label.trigger('blur');

    expect(form.value?.fields[0].key).toBe('custom_key');
  });

  it('gives each added field a distinct key once labelled, even after a removal', async () => {
    const { wrapper, form } = mountWithParent(null);

    const addField = async (labelText: string) => {
      await wrapper.get('[data-testid="form-builder-add-field-button"]').trigger('click');
      const labels = wrapper.findAll('[data-testid="form-field-label-input"]');
      const last = labels[labels.length - 1];
      await last.setValue(labelText);
      await last.trigger('blur');
    };

    await addField('Alpha');
    await addField('Beta');
    await wrapper.findAll('[data-testid="form-builder-remove-field-button"]')[0].trigger('click');
    await addField('Gamma');

    const keys = form.value!.fields.map((f) => f.key);
    expect(keys).toEqual(['beta', 'gamma']);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('renumbers order contiguously as fields are added and removed', async () => {
    const { wrapper, form } = mountWithParent(null);

    for (let i = 0; i < 3; i++) {
      await wrapper.get('[data-testid="form-builder-add-field-button"]').trigger('click');
    }
    await wrapper.findAll('[data-testid="form-builder-remove-field-button"]')[1].trigger('click');

    expect(form.value!.fields.map((f) => f.order)).toEqual([0, 1]);
  });

  it('emits nothing and hides the editing affordances when readonly', async () => {
    const existing: ApplicationForm = {
      fields: [
        { key: 'shop', label: 'Shop', type: 'text', required: true, options: [], order: 0 },
      ],
    };
    const { wrapper, form } = mountWithParent(existing, true);

    expect(wrapper.find('[data-testid="form-builder-add-field-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="form-builder-remove-field-button"]').exists()).toBe(false);

    const label = wrapper.get('[data-testid="form-field-label-input"]');
    expect(label.attributes('disabled')).toBeDefined();
    await label.setValue('Tampered');

    expect(form.value!.fields[0].label).toBe('Shop');
  });
});

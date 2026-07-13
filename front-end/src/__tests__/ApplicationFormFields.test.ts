// @vitest-environment happy-dom
import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';

import ApplicationFormFields from '@/components/application/ApplicationFormFields.vue';
import type { FormField } from '@/assets/types/datatypes';

/**
 * Both applicant surfaces render the form through this one component, so a field type reaching the
 * applicant is proved once, here. Two copies of the type switch drifted before this existed: a
 * type one copy knew rendered there as an input and on the other page as a bare label with no
 * control - and a required one blocked Save with an error the applicant had no way to clear.
 */
function field(over: Partial<FormField> = {}): FormField {
  return {
    key: 'shop_name',
    label: 'Shop Name',
    type: 'text',
    required: false,
    options: [],
    order: 0,
    ...over,
  };
}

function mountFields(fields: FormField[], modelValue: Record<string, unknown> = {}) {
  return mount(ApplicationFormFields, {
    props: { fields, modelValue, prefix: 'apply' },
  });
}

describe('ApplicationFormFields', () => {
  it('renders a control for every field type the builder can produce', () => {
    const types: [string, string][] = [
      ['text', 'input[type="text"]'],
      ['email', 'input[type="email"]'],
      ['number', 'input[type="number"]'],
      ['date', 'input[type="date"]'],
      ['checkbox', 'input[type="checkbox"]'],
      ['select', 'select'],
      ['multi_select', 'input[type="checkbox"]'],
    ];

    for (const [type, selector] of types) {
      const wrapper = mountFields([
        field({ type, key: 'f', options: type.includes('select') ? ['A', 'B'] : [] }),
      ]);
      expect(wrapper.find(selector).exists(), `${type} renders no control`).toBe(true);
      expect(wrapper.find('.form-unsupported').exists(), `${type} is unsupported`).toBe(false);
    }
  });

  it('names an unknown field type instead of rendering a label with no control', () => {
    const wrapper = mountFields([field({ type: 'signature', key: 'sig' })]);

    expect(wrapper.get('[data-testid="apply-unsupported-sig"]').text()).toContain('signature');
  });

  it('reports every answer back to the view it is rendered in', async () => {
    const wrapper = mountFields([field()]);

    await wrapper.get('[data-testid="apply-input-shop_name"]').setValue('Acme');

    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({ shop_name: 'Acme' });
    expect(wrapper.emitted('field-change')).toHaveLength(1);
  });

  it('adds and removes multi_select options without dropping the others', async () => {
    const wrapper = mountFields(
      [field({ type: 'multi_select', key: 'days', options: ['Fri', 'Sat'] })],
      { days: ['Fri'] },
    );

    await wrapper.get('[data-testid="apply-input-days-Sat"]').setValue(true);
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({ days: ['Fri', 'Sat'] });

    await wrapper.get('[data-testid="apply-input-days-Fri"]').setValue(false);
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({ days: [] });
  });

  it('renders the fields in the order the organizer set, and shows their errors', () => {
    const wrapper = mountFields(
      [field({ key: 'b', label: 'Second', order: 1 }), field({ key: 'a', label: 'First', order: 0 })],
      {},
    );
    expect(wrapper.findAll('.form-label').map((l) => l.text())).toEqual(['First', 'Second']);

    const withError = mount(ApplicationFormFields, {
      props: {
        fields: [field({ key: 'a', required: true })],
        modelValue: {},
        errors: { a: 'Shop Name is required.' },
        prefix: 'apply',
      },
    });
    expect(withError.get('[data-testid="apply-error-a"]').text()).toBe('Shop Name is required.');
  });
});

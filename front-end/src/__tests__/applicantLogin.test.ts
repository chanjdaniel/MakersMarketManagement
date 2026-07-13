// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ApplicantLogin from '@/views/ApplicantLogin.vue'
import { useApplicationStore } from '@/stores/application'

vi.mock('@/utils/publicApplicationForm', () => ({
  fetchPublicApplicationForm: vi.fn().mockResolvedValue({ marketName: 'Test Market' }),
}))

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { marketSlug: 'test-market' }, query: {} }),
  useRouter: () => ({ push }),
}))

/**
 * The back end sends at most one code per address per minute, and it answers a request inside that
 * window with the same accepted message a real send gets - it has to, because only an address that
 * already has a live code can be cooled down, so a distinguishable answer there would tell an
 * unauthenticated caller which addresses are on the organizer's applicant list.
 *
 * So this screen is the only place that can be honest about it, and these are the two halves of
 * being honest: never claim a code was sent that was not, and never offer a button whose only
 * effect would be to make that claim.
 */
describe('ApplicantLogin', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  async function signInWith(email: string) {
    const wrapper = mount(ApplicantLogin)
    const store = useApplicationStore()
    const requestKey = vi.spyOn(store, 'requestKey').mockResolvedValue(undefined)

    await wrapper.find('[data-testid="applicant-login-email-input"]').setValue(email)
    await wrapper.find('[data-testid="applicant-login-request-btn"]').trigger('click')
    await flushPromises()

    return { wrapper, store, requestKey }
  }

  it('does not claim a code was sent to an address that may not have applied', async () => {
    const { wrapper } = await signInWith('vendor@example.com')

    const instruction = wrapper.find('[data-testid="applicant-login-key-step"]').text()
    expect(instruction).toContain('If an application exists for')
    expect(instruction).toContain('vendor@example.com')
    expect(instruction).not.toContain('We sent a 6-digit code')
  })

  it('will not resend inside the cooldown, because the back end would send nothing', async () => {
    const { wrapper, requestKey } = await signInWith('vendor@example.com')
    expect(requestKey).toHaveBeenCalledTimes(1)

    const resend = wrapper.find('[data-testid="applicant-login-resend-btn"]')
    expect(resend.attributes('disabled')).toBeDefined()
    expect(resend.text()).toContain('Resend code in')

    await resend.trigger('click')
    await flushPromises()

    expect(requestKey).toHaveBeenCalledTimes(1)
  })

  it('counts the cooldown down and then lets the applicant ask again', async () => {
    const { wrapper, requestKey } = await signInWith('vendor@example.com')

    expect(wrapper.find('[data-testid="applicant-login-resend-btn"]').text()).toContain('60s')

    vi.advanceTimersByTime(59_000)
    await flushPromises()
    expect(wrapper.find('[data-testid="applicant-login-resend-btn"]').text()).toContain('1s')

    vi.advanceTimersByTime(1_000)
    await flushPromises()
    const resend = wrapper.find('[data-testid="applicant-login-resend-btn"]')
    expect(resend.attributes('disabled')).toBeUndefined()
    expect(resend.text()).toBe('Resend code')

    await resend.trigger('click')
    await flushPromises()
    expect(requestKey).toHaveBeenCalledTimes(2)
  })

  it('holds the same address to the cooldown after "use a different email"', async () => {
    const { wrapper, requestKey } = await signInWith('vendor@example.com')
    await wrapper.find('[data-testid="applicant-login-back-btn"]').trigger('click')

    const send = wrapper.find('[data-testid="applicant-login-request-btn"]')
    expect(send.attributes('disabled')).toBeDefined()
    expect(send.text()).toContain('Code already sent')

    await wrapper.find('[data-testid="applicant-login-email-input"]').setValue('other@example.com')
    await wrapper.find('[data-testid="applicant-login-request-btn"]').trigger('click')
    await flushPromises()

    expect(requestKey).toHaveBeenCalledTimes(2)
    expect(requestKey).toHaveBeenLastCalledWith('test-market', 'other@example.com')
  })
})

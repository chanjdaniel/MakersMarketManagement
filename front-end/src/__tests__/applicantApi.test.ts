import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AxiosError, AxiosHeaders } from 'axios';

/**
 * The applicant's token is short-lived, so it expiring mid-form is a normal path. Nothing else
 * ends the session: if a rejected token survives its 401, the store still reads as authenticated,
 * every retry re-sends the same dead token, and the applicant is stuck on a screen whose only
 * button cannot work.
 */
describe('applicant api session expiry', () => {
  let mod: typeof import('@/utils/applicantApi');
  let onExpired: ReturnType<typeof vi.fn>;

  function rejection(url: string, status: number) {
    const error = new AxiosError('failed', undefined, { headers: new AxiosHeaders(), url });
    error.response = {
      status,
      statusText: '',
      data: {},
      headers: {},
      config: { headers: new AxiosHeaders() },
    };
    return error;
  }

  async function reject(error: AxiosError) {
    const handlers = (
      mod.applicantApi.interceptors.response as unknown as {
        handlers: { rejected: (err: unknown) => unknown }[];
      }
    ).handlers;
    await expect(handlers[0].rejected(error)).rejects.toBe(error);
  }

  beforeEach(async () => {
    vi.resetModules();
    mod = await import('@/utils/applicantApi');
    onExpired = vi.fn();
    mod.setApplicantSessionExpiredHandler(onExpired);
    mod.setApplicantToken('a-live-token');
  });

  it('ends the session when the token is refused', async () => {
    await reject(rejection('/public/applicant/application', 401));

    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it('drops the refused token, so a retry cannot re-send it', async () => {
    await reject(rejection('/public/applicant/application', 401));

    const config = { headers: new AxiosHeaders() };
    const request = (
      mod.applicantApi.interceptors.request as unknown as {
        handlers: { fulfilled: (config: unknown) => unknown }[];
      }
    ).handlers;
    await request[0].fulfilled(config);

    expect(config.headers.get('Authorization')).toBeUndefined();
  });

  it('leaves the session alone when the login endpoint refuses a wrong code', async () => {
    await reject(rejection('/public/applicant/verify-key', 401));

    expect(onExpired).not.toHaveBeenCalled();
  });

  it('leaves the session alone on any other failure', async () => {
    await reject(rejection('/public/applicant/application', 403));

    expect(onExpired).not.toHaveBeenCalled();
  });
});

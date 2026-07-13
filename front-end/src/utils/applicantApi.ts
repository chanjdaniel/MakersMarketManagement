import axios from 'axios';

/** The applicant login endpoints, which answer 401 for a bad code rather than for a dead session. */
const APPLICANT_LOGIN_PATHS = [
  '/public/applicant/request-key',
  '/public/applicant/verify-key',
];

let _token: string | null = null;
let _onSessionExpired: (() => void) | null = null;

/** Set the application-scoped JWT for use by all applicant API calls.
 * Called by the application Pinia store after successful login. */
export function setApplicantToken(token: string | null): void {
  _token = token;
}

/**
 * What to do when the application-scoped token is rejected. Registered once at app start
 * (`main.ts`), which is where both the store and the router are reachable.
 */
export function setApplicantSessionExpiredHandler(handler: (() => void) | null): void {
  _onSessionExpired = handler;
}

/** Axios instance for applicant endpoints. Sends the application-scoped JWT
 * as a Bearer token. The token is stored in memory only (not localStorage)
 * to avoid XSS exfiltration. */
export const applicantApi = axios.create({
  baseURL: import.meta.env.VITE_FLASK_HOST,
  withCredentials: true,
});

applicantApi.interceptors.request.use((config) => {
  if (_token) {
    config.headers.set('Authorization', `Bearer ${_token}`);
  }
  return config;
});

/**
 * The token is short-lived, so a session expiring while the applicant is filling in a form is a
 * normal path, not an edge case, and this is the only thing that ends it. Without it the store
 * still reads as authenticated after expiry: every retry re-sends the same dead token, and the
 * applicant sits on a screen whose only button cannot work. A 401 from the login endpoints is a
 * wrong code, not a dead session, and must not sign anyone out.
 */
applicantApi.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = axios.isAxiosError(error) ? (error.config?.url ?? '') : '';
    const isLoginCall = APPLICANT_LOGIN_PATHS.some((path) => url.includes(path));
    if (
      _token &&
      !isLoginCall &&
      axios.isAxiosError(error) &&
      error.response?.status === 401
    ) {
      _token = null;
      _onSessionExpired?.();
    }
    return Promise.reject(error);
  },
);

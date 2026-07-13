import axios from 'axios';

let _token: string | null = null;

/** Set the application-scoped JWT for use by all applicant API calls.
 * Called by the application Pinia store after successful login. */
export function setApplicantToken(token: string | null): void {
  _token = token;
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

export function getApiErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    return err.response?.data?.error || fallback;
  }
  return fallback;
}

export function getApiErrorStatus(err: unknown): number | null {
  return axios.isAxiosError(err) ? (err.response?.status ?? null) : null;
}

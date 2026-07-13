import type { FormField } from '@/assets/types/datatypes';
import { applicantApi } from '@/utils/applicantApi';

/** What every applicant-facing screen needs to know about a market before it can render. */
export interface PublicApplicationForm {
  /** The market's name. The applicant knows the market by this; the slug is a URL detail. */
  marketName: string;
  fields: FormField[];
  phaseLabel: string;
  isOpen: boolean;
}

/**
 * The one public endpoint an applicant screen can read a market from, normalized once. All three
 * applicant views need the same four things from it, and the response is snake_case where the rest
 * of the front-end is camelCase, so the mapping is written here rather than three times.
 */
export async function fetchPublicApplicationForm(
  marketSlug: string,
): Promise<PublicApplicationForm> {
  const { data } = await applicantApi.get(`/public/markets/${marketSlug}/application-form`);
  return {
    marketName: data.market_name || '',
    fields: data.application_form?.fields ?? [],
    phaseLabel: data.phase_label || '',
    isOpen: data.is_open === true,
  };
}

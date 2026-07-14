import { execFileSync } from 'node:child_process';
import type { APIRequestContext } from '@playwright/test';

import { ensureTestOrgAuthenticated, loginViaApi, marketNameToSlug } from './seeds';

/**
 * The market an applicant can actually apply to: published past `draft`, in `applications_open`,
 * with a form to fill in. Everything the public applicant flow needs, and nothing else - no CSV, no
 * vendors, no assignment.
 *
 * The form is written through `PUT /markets/<id>/application-form`, which is its only writer on an
 * existing market, and the phase is moved with the transition endpoint, which is the only thing that
 * moves it. Nothing here writes a market document by hand: a seed that reached this state some other
 * way would be testing a state the product cannot produce.
 */

export interface ApplicantMarketSeed {
  marketId: string;
  marketName: string;
  marketSlug: string;
  orgId: string;
}

/** Two required fields, so a save that skipped validation is a save the test would notice. */
export const APPLICATION_FIELDS = [
  {
    key: 'business_name',
    label: 'Business Name',
    type: 'text',
    required: true,
    options: [],
    order: 0,
  },
  {
    key: 'product_type',
    label: 'What do you sell?',
    type: 'text',
    required: true,
    options: [],
    order: 1,
  },
];

export async function seedApplicationsOpenMarket(
  request: APIRequestContext,
  baseURL: string,
  email: string,
  password: string,
): Promise<ApplicantMarketSeed> {
  const userId = await loginViaApi(request, baseURL, email, password);
  const orgId = await ensureTestOrgAuthenticated(request, baseURL, email);

  const marketName = `E2E Applicant ${Date.now()}`;
  const createRes = await request.post(`${baseURL}/markets`, {
    headers: { 'Content-Type': 'application/json', 'X-Owner-Email': email },
    data: {
      name: marketName,
      creationDate: new Date().toISOString(),
      organizationId: orgId,
      roles: { [userId]: 'owner' },
      modificationList: [],
      assignmentObject: {},
    },
  });
  if (!createRes.ok()) {
    throw new Error(`Market creation failed: ${createRes.status()} ${await createRes.text()}`);
  }
  const { market_id: marketId } = (await createRes.json()) as { market_id: string };

  const formRes = await request.put(`${baseURL}/markets/${marketId}/application-form`, {
    headers: { 'Content-Type': 'application/json', 'X-Owner-Email': email },
    data: { fields: APPLICATION_FIELDS },
  });
  if (!formRes.ok()) {
    throw new Error(`Application form save failed: ${formRes.status()} ${await formRes.text()}`);
  }

  // The form is what the guard on this edge demands, so it goes in first. Applications are open only
  // past this point: `request-key` creates an application for a new address in this phase and in no
  // other, which is what makes a first-time applicant's sign-in possible at all.
  const transitionRes = await request.post(`${baseURL}/markets/${marketId}/transition`, {
    headers: { 'Content-Type': 'application/json', 'X-Owner-Email': email },
    data: { toPhase: 'applications_open' },
  });
  if (!transitionRes.ok()) {
    throw new Error(
      `Market transition failed: ${transitionRes.status()} ${await transitionRes.text()}`,
    );
  }

  return { marketId, marketName, marketSlug: marketNameToSlug(marketName), orgId };
}

/**
 * The six-digit code the back end just mailed - read from the challenge document it wrote, because
 * the e2e stack sends no mail (`DISABLE_EMAIL`) and, mail or not, an inbox is not something a test
 * can open. `auth.spec.ts` reads password-reset tokens the same way.
 *
 * The code is the applicant's whole identity proof, so a test that could not read it could not sign
 * anyone in - and every behavior this flow exists for lives on the other side of that sign-in.
 */
export function readApplicantLoginCode(marketId: string, email: string): string {
  const container = process.env.E2E_MONGO_CONTAINER || 'conventioner_mongodb';
  const filter = JSON.stringify({ market_id: marketId, email });

  const out = execFileSync(
    'docker',
    [
      'exec',
      container,
      'mongosh',
      'mongodb://admin:secret@localhost:27017/conventioner?authSource=admin',
      '--quiet',
      '--eval',
      `print(db.applicant_login_codes.findOne(${filter})?.code ?? '')`,
    ],
    { encoding: 'utf-8' },
  );

  const code = out.trim().split('\n').pop()?.trim() || '';
  if (!/^\d{6}$/.test(code)) {
    throw new Error(
      `No login code was issued for ${email} on market ${marketId} (mongosh said: ${out.trim()})`,
    );
  }
  return code;
}

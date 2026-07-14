import type { Locator, Page } from '@playwright/test';

import { readApplicantLoginCode } from '../helpers/seedApplicantMarket';

/**
 * The applicant's sign-in screen: an address, a six-digit code mailed to it, and no password.
 *
 * `signIn()` reads the code out of the challenge document the back end wrote, which is the only
 * place a test can get it - the stack sends no mail, and an inbox is not something Playwright can
 * open. Everything else here is the real screen, driven the way an applicant drives it.
 */
export class ApplicantLoginPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(marketSlug: string) {
    await this.page.goto(`/${marketSlug}/applicant-login`);
    await this.emailInput.waitFor();
  }

  get emailInput(): Locator {
    return this.page.getByTestId('applicant-login-email-input');
  }

  get requestButton(): Locator {
    return this.page.getByTestId('applicant-login-request-btn');
  }

  get keyInput(): Locator {
    return this.page.getByTestId('applicant-login-key-input');
  }

  get verifyButton(): Locator {
    return this.page.getByTestId('applicant-login-verify-btn');
  }

  get error(): Locator {
    return this.page.getByTestId('applicant-login-error');
  }

  /** Ask for a code, and hand back the one the back end issued. */
  async requestCode(marketId: string, email: string): Promise<string> {
    await this.emailInput.fill(email);
    await this.requestButton.click();
    await this.keyInput.waitFor();
    return readApplicantLoginCode(marketId, email);
  }

  async enterCode(code: string) {
    await this.keyInput.fill(code);
    await this.verifyButton.click();
  }

  /** The whole sign-in, from the address to a live session. */
  async signIn(marketId: string, email: string) {
    const code = await this.requestCode(marketId, email);
    await this.enterCode(code);
  }
}

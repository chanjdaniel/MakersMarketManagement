import type { Locator, Page } from '@playwright/test';

/** The public application page: `/:marketSlug/apply`, reachable with no account and no session. */
export class ApplyPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(marketSlug: string) {
    await this.page.goto(`/${marketSlug}/apply`);
    await this.form.waitFor();
  }

  get form(): Locator {
    return this.page.getByTestId('apply-form');
  }

  get marketName(): Locator {
    return this.page.getByTestId('apply-market-name');
  }

  input(key: string): Locator {
    return this.page.getByTestId(`apply-input-${key}`);
  }

  async fillField(key: string, value: string) {
    await this.input(key).fill(value);
  }

  get submitButton(): Locator {
    return this.page.getByTestId('apply-submit-button');
  }

  async submit() {
    await this.submitButton.click();
  }

  /** Shown only after the answers have reached the server. */
  get savedBanner(): Locator {
    return this.page.getByTestId('apply-saved');
  }

  /**
   * Answers typed in this browser before anyone signed in. The page will not put them into the form
   * or save them by itself - it cannot know who typed them - so it offers them, and a person says.
   */
  get draftOffer(): Locator {
    return this.page.getByTestId('apply-draft-offer');
  }

  async restoreOfferedDraft() {
    await this.page.getByTestId('apply-draft-restore-button').click();
  }

  async discardOfferedDraft() {
    await this.page.getByTestId('apply-draft-discard-button').click();
  }
}

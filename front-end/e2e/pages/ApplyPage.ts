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
   * Shown when answers typed in this browser before anyone signed in have been put back into the
   * form. The page restores them - they are almost always this applicant's - but it cannot know who
   * typed them, so it says so and will not submit them for anybody.
   */
  get draftNotice(): Locator {
    return this.page.getByTestId('apply-draft-notice');
  }

  async clearRestoredDraft() {
    await this.page.getByTestId('apply-draft-clear-button').click();
  }
}

# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Branch Model

- `dev` is the default/integration branch: all feature PRs target `dev`.
- `main` is the deploy-only branch: it auto-deploys, and is reached ONLY by promoting `dev` → `main` as a deliberate, versioned release.
- Never commit directly to `main`. Never open PRs targeting `main` (except the release-please Release PR, which is automated).

## Release Process

- Release management uses [release-please](https://github.com/googleapis/release-please) (GitHub Action `googleapis/release-please-action@v5`).
- Release type is `simple` (conventional-commits-driven; no per-language package file parsing).
- Workflow triggers on push to `main` (`.github/workflows/release-please.yml`).
- When `dev` is promoted to `main`, release-please opens a Release PR with version bump + CHANGELOG.
- Merging the Release PR creates a git tag (e.g., `v0.1.0`) and a GitHub Release.
- All commits MUST follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, etc.).
- Baseline seed: `0.0.0` in `.release-please-manifest.json`; the first release is pinned to `v0.1.0` via `release-as: 0.1.0` in `release-please-config.json`. Remove that `release-as` field after `v0.1.0` ships, after which versions follow conventional commits (`feat:` → minor, `fix:` → patch, breaking → major).
- Full release docs: `docs/RELEASING.md`.

## Tech Stack

- Front-end: Vue 3 + Vite + TypeScript (in `front-end/`), PrimeVue UI components, Pinia state management.
- Back-end: Python 3.11 / Flask + MongoDB (in `back-end/`).
- Testing: Vitest (unit) + Playwright (e2e) for front-end; pytest for back-end.
- CI: `.github/workflows/test.yml` runs on `dev` and `main` for both PRs and pushes.

## E2E Testing Patterns

- **data-testid convention**: `viewname-element` (e.g. `login-email-input`, `markets-create-button`).
  No product behavior changes - purely additive test infrastructure.
- **Page Object Model**: Located under `front-end/e2e/pages/`.
  Each page object wraps Playwright `getByTestId()` selectors and exposes action methods.
  New pages should follow the existing `LoginPage`, `NewMarketPage`, `MarketSetupPage`,
  `AssignmentResultsPage`, `OrganizationsPage`, `ManageMarketPage` patterns.
- **Fixtures**: `front-end/e2e/fixtures.ts` provides `TEST_USER`, `authenticatedPage`,
  re-exports page objects for convenience, and exposes `BACKEND_URL`
  (via `detectBackendPort()`) for direct API calls.
- **API-level seeding**: `front-end/e2e/helpers/seeds.ts` exports `seedMarketWithVendors()`
  which creates markets and uploads vendor CSV via the back-end API.
  `front-end/e2e/helpers/seedAssignedMarket.ts` exports `seedAssignedMarket()`, which
  also configures the market `setupObject` and triggers assignment via the API.
  Requires a verified test user (created by `scripts/seed_fixture.sh`).
- **Markets require an organization**: `POST /markets` rejects a payload with no
  `organizationId`, an unknown organization, or an organization the caller is not a
  member of (400 each).
  Anything that creates a market must therefore attach one: `seeds.ts` exports
  `ensureTestOrgAuthenticated()` (already-logged-in request context) and
  `ensureTestOrg()` (logs in first), both of which reuse the user's first organization
  or create `E2E Test Org`, and the seed helpers return it as `orgId`.
  Specs that create a market through the UI must call `ensureTestOrg()` in `beforeAll`,
  otherwise the overlay's org dropdown is empty and submit stays disabled.
- **Test user creation**: The back-end `/register-user` endpoint does NOT set `email_verified`,
  so users created through it cannot log in.
  Test users must be created via `back-end/create_test_user.py` which sets `email_verified=True`.
  `scripts/seed_fixture.sh` creates two verified users: `TEST_EMAIL` (owns `Seed Test Org`)
  and `NO_ORG_EMAIL` (`e2e-noorg@example.com`), which is deliberately left in no organization
  so `new-market-org.spec.ts` can exercise the zero-org fallback.
  A spec needing users beyond those two calls `ensureVerifiedUser()`
  (`front-end/e2e/helpers/verifiedUser.ts`) in `beforeAll`, which runs that same script inside
  the back-end container; do not hand-roll the user document, and do not switch to
  `/register-user`.
- **Run E2E**: `./scripts/seed_fixture.sh` then `cd front-end && npm run test:e2e`.
  Playwright config auto-detects worktree port via `detectFrontendPort()`.

### Floorplan Workflow E2E

- **Deterministic - no AI mocking needed.** Despite the "Floorplan AI" name,
  the front-end wizard makes no LLM/vision calls. Table auto-placement
  (`POST /floorplans/place-tables`, `back-end/services/placement_service.py`)
  is a pure geometry solver (Shapely + `pyckingsolver`). The
  Gemini/GPT vision endpoint (`POST /floorplans/analyze`,
  `back-end/api/floorplans_analysis.py`) exists but is not wired into the
  front-end workflow (walls are drawn by hand). Consequence: the flow can be
  exercised end-to-end for real in CI with no API keys and no stubbing.
- **Konva canvas interactions and coverage gap.** The wizard's three canvas
  steps have different testability:
  - Calibration line drawing IS drivable with real Playwright `page.mouse`
    drags on the Konva stage (see `FloorplanWorkflowPage.drawCalibrationLine()`).
  - Section-grouping (Konva "lasso" selection) and the `FloorplanEditor` step
    are NOT reliably drivable via simulated mouse events.
    `floorplan.spec.ts` drives Pinia store state directly via `page.evaluate`
    for those steps (`groupAllTablesIntoSection()`), and uses
    `snapshotPlacedTables()` to assert table state persists across wizard steps.
  - **Coverage gap**: section grouping and editor canvas interactions are
    validated at the state level, not as real user gestures. Anyone extending
    floorplan coverage should account for this.
- **Artifacts** (PR #18 pattern to follow):
  - Page object: `front-end/e2e/pages/FloorplanWorkflowPage.ts`
  - Spec: `front-end/e2e/floorplan.spec.ts`
  - Fixture: `front-end/e2e/fixtures/test-floorplan.png` (800×600 PNG)
- **Save-path null-tolerance**: `POST /floorplans/save-to-market`
  (`back-end/api/floorplans_save.py`) handles a null `setupObject` on the
  market doc (the manual-setup path leaves it null). The fix uses
  `isinstance(existing_setup, dict)` to branch between updating the existing
  object and seeding a fresh one.
- **Editor-mount table preservation**: `FloorplanEditor.vue`'s
  `loadBackgroundImage()` only calls `store.initFloorplan()` when no floorplan
  exists yet, spreading the existing store data (`placedTables`, `tableTypes`,
  `sections`, `walls`, `obstacles`, scale) into the init so forward wizard
  progression keeps auto-placed tables; when a floorplan already exists it just
  refreshes the background image fields. This replaced an earlier
  snapshot/restore workaround in the e2e page object.

## E2E Seed Helpers for Published Markets

- `seedPublishedMarketWithAssignments()` in `front-end/e2e/helpers/seeds.ts` creates a fully
  published market with vendor assignments ready for check-in, vendor browsing, and table filtering tests.
- The back-end assignment algorithm (`assign_market`) requires `enum_priority_order` to have one
  entry (empty list) per column in `col_names`. Omitting this causes an `IndexError`.
- Publishing is `POST /markets/{id}/transition` with `{ toPhase: 'archived' }`, never a PUT of
  `isDraft: false` - `isDraft` is derived from `phase` and a PUT body cannot set it.
- After publishing, with a configured `setup_object`, you must fetch the
  computed assignment via `GET /markets/{id}/assignment` and store it back via PUT.
  The stored `assignmentObject.vendorAssignments` is what `record_attendance` reads at check-in time.

## CSV Field Runtime Coupling (Conventioner sharp edge)

- `col_name` and `col_name_idx` on `MarketDateObject` (in `back-end/datatypes.py`) are
  used at runtime in two places that CANNOT be removed until Phase 5 of Conventioner:
  - `back-end/api/attendance.py:67-75` - `record_attendance()` builds date aliases from
    `md.get("col_name")`. Without it, public check-in for existing markets breaks.
  - `back-end/assignment/assignment.py:53` - `_calculate_date_flexibility()` resolves
    dates via `market_date.col_name`. Without it, the solver fails for existing markets.
- These fields are kept Optional with `None` defaults on the Pydantic models during
  Phases 1-4. New application-based markets leave them `None`. Existing CSV-backed
  markets retain their values.
- The same backward-compat strategy applies to the other CSV-derived fields on
  `SetupObject`, `PriorityObject`, and `AssignmentOptionObject`: keep them Optional,
  remove them in Phase 5 when the solver adapter and attendance redesign land.
- Do NOT delete `is_draft` from the `Market` model, and do not make it writable again. It is a
  `@computed_field` derived strictly from `phase` (true iff `phase == draft`), kept on the
  document only because it is the fallback `phase_from_market_document()` uses for a market
  written before `phase` existed. See Phase Transitions below.

## Application Form Lock (Conventioner sharp edge)

- **Applications are stored snake_case**, unlike markets and organizations, which are
  camelCased on write. The market foreign key is `market_id`, NOT `marketId`.
  `back-end/api/applications.py` is the single owner of the collection and every reader and
  writer must go through it. A writer that stored the market reference under any other key
  would silently disable the D9 lock below - the count would just return 0.
- **The D9 lock has one source of truth**: `application_form_lock_reason()` in
  `back-end/api/markets.py`. A market's application form is editable only in `draft` phase
  and only while no application exists for it; once an applicant has submitted, the form is
  frozen for good.
- **`Market.application_form` is server-owned on update.** `PUT /markets/<id>/application-form`
  is its only writer on an existing market; `update_market()` re-applies the stored form over
  whatever a market PUT body carried. Do not "fix" that by letting a market PUT write the form
  - it is what makes the lock unbypassable. `POST /markets` may carry a form, and it runs
  through the same validator.
- E2E reaches the locked state with `seedApplication()`
  (`front-end/e2e/helpers/seedApplication.ts`), which writes the document straight into Mongo
  via `mongosh`, because no applicant-facing submit endpoint exists yet.

## Public Applicant Endpoints (Conventioner sharp edge)

- **The back end refuses to boot, anywhere, without `SECRET_KEY`, `RECAPTCHA_SECRET_KEY`, and
  `TRUSTED_PROXY_HOPS`** (`verify_public_endpoint_defenses()` in `back-end/app.py`).
  All three defend `/public/applicant/*`, which is unauthenticated, writes to the database, and sends
  mail from the product's domain, and all three silently degrade to nothing when unset:
  `verify_recaptcha` passes every caller with no secret, and a rate limit keyed on `remote_addr`
  behind a proxy is one shared budget that locks out every real applicant instead of bounding an
  attacker.
  Set `TRUSTED_PROXY_HOPS` to the number of proxies of our own a request passes through
  (0 = Flask exposed directly, 1 on Vercel); ProxyFix then reads exactly that many `X-Forwarded-For`
  entries from the right, which is the part a client cannot forge.
  The check runs all three and the refusal names *every* variable that is missing, in one message:
  stopping at the first would cost the operator a redeploy per variable.
  This is a boot-time deploy contract - a deployment missing one serves nothing, organizer app
  included - so it is written down where the promotion is: `docs/RELEASING.md`, "Required Production
  Environment". Keep that table in step with the check.
- **There is no fallback signing secret, and there must never be one again**
  (`back-end/utils/secret_key.py` is the only reader of `SECRET_KEY`).
  It signs both the Flask session cookie and the application-scoped applicant JWT
  (`utils/application_token.py`), so it is what makes an applicant token mean anything - and a token
  reads and overwrites any applicant's application, past the one-time code, the captcha, and every
  rate limit.
  It used to default to a literal committed to this repository, which is to say a published key that
  anyone reading the source could sign with.
  A secret with a default is not a secret: do not add one back "for dev".
  Under `ALLOW_INSECURE_LOCAL_DEV` an unconfigured process signs with a *random per-process* key
  instead, which cannot be forged against and cannot quietly become the key a deployment ships with;
  the cost is that a restart invalidates that process's sessions and tokens, which is the right price
  for declining to configure a key.
- **The escape hatch is `ALLOW_INSECURE_LOCAL_DEV`, and it is the only one** (`back-end/utils/deployment.py`).
  It defaults to off, so the secure state is the one you get by forgetting.
  Do NOT re-gate any of this on `FLASK_ENV`: that is where the check was, and it made the check dead
  code, because `back-end/Dockerfile` sets `FLASK_ENV=development` and nothing overrides it - so
  every deployment built from our own image was exempt from precisely the check that existed for it.
  A security control must never key on a variable whose default is the insecure value.
  `docker-compose.yml` sets the hatch (it *is* the dev stack) and logs every defense it turns off;
  nothing else in the repo sets it.
- **Nothing these endpoints do may differ between an address that has applied and one that has not**
  - not the status, not the body, not the attempt counter, and not, within the bound below, the time
  on the clock.
  Who applied is the organizer's private data.
  That is why the login challenge is a collection of its own rather than a field on the application
  (`_challenge_for` in `back-end/api/applicants.py`): a counter that lived on the application would
  be present for an applicant and absent for a stranger, and every refusal that read it would say so.
- **The OTP mail is sent synchronously, inside a fixed response-time floor**
  (`KEY_REQUEST_FLOOR_SECONDS`), not handed to a background thread.
  The send is a Resend round-trip that happens only for a real applicant, so awaiting it *nakedly*
  leaks the applicant list on the clock - but deferring it to an in-process thread is worse, because
  this product documents a serverless target (`SESSION_TYPE=null` "for Vercel serverless") where the
  context is frozen the moment the response is written and the thread may never run at all.
  Delivering the code matters more than the side-channel; the floor buys both.
  Its clock starts where the two paths *diverge* (after the captcha, the rate limits, and the market
  lookup), not at the top of the request: those steps run identically for every caller and leak
  nothing, but they are not free, and a floor measured from before them is a floor a slow captcha
  round-trip can spend - which puts the send straight back on the response clock and reopens the
  oracle under exactly the tail latency an attacker can afford to wait for.
- **The floor is charged only where the send actually branches** (`_key_request_floor`), which means
  never in `applications_open`.
  In that phase an address with no application gets one, so *every* caller pays for a send and there
  is no difference to bury - and a floor charged there would be a blocking `time.sleep` held over the
  busiest hour this product has, with hundreds of vendors signing in the minute applications open,
  each one holding a worker (or a billed serverless invocation) for the length of it.
  The later phases take no new applications, so the send happens only for an address already on the
  list: that is the branch, and those phases are the quiet ones.
  Truthful bounds, none of which may be dropped from this note:
  the floor equalizes the two paths only as long as the send fits inside it (an overrun goes back on
  the clock);
  in `applications_open` a first-time address still costs one extra Mongo insert, and a request for an
  address whose code was issued within `KEY_RESEND_COOLDOWN_SECONDS` returns without a send and so
  returns faster - which says a code was asked for recently, not that the address has applied (in that
  phase, asking is what creates the application).
  Do not write "the clock says nothing" without those caveats.
- **One applicant is one application, and the unique index is what holds that**
  ((`market_id`, `applicant_email`, `application_type`), built by
  `ApplicationsApi.ensure_application_indexes()` and by
  `migrations/create_applications_collection.py`).
  `request_applicant_key` reads the applicant list before it writes to it, so without the index two
  concurrent requests for one new address each insert an application - deliberately raced, or a
  double-tapped button. Only one is ever reachable again; the other sits on the organizer's list,
  double-counting that applicant through review, assignment, and the D9 lock.
  Creation therefore goes through `find_or_create_application()`, a conditional upsert that hands the
  loser of the race the winner's document. Never insert an application document directly.
  The same holds for the login-challenge store's unique index on (`market_id`, `email`)
  (`ApplicantsApi.ensure_login_code_indexes()`): it is what makes the per-code attempt cap a cap,
  rather than one budget per document a caller mints by asking for two codes at once.
  Both indexes *are* their guarantees, not decorations on ones the code keeps anyway, so a build that
  fails raises and `verify_applicant_identity_indexes()` (`back-end/app.py`) asserts both at boot: a
  process that cannot enforce them does not serve. Do not soften either back into a logged warning -
  an index that will not build almost always means the collection already holds the duplicates the
  index forbids, which is the state serving on would deepen.
- **A request is admitted by all of its budgets or by none of them.** The applicant endpoints charge
  a per-IP budget and a global ceiling for the same request, and both are budgets *other people* are
  also spending, so they are charged together through `any_budget_exceeded()`
  (`back-end/utils/rate_limit.py`), which gives back every increment it took as soon as one budget
  refuses. Charging them one call at a time is a live bug in either order: charge the IP budget first
  and an hour in which the product hits its global ceiling burns down the hourly budget of every
  shared NAT signing in at the time; charge the ceiling first and one abusive IP burns the shared
  ceiling with requests its own budget already refused. The stored count of every window stays what
  `utils/rate_limit.py` promises: the number of requests that were *admitted*, and nothing else.
- **The captcha is the control against scripts here; the rate limits are safety ceilings, not the
  control.**
  Applicants share addresses (a hall's wifi is one; carrier CGNAT pools thousands) and a market whose
  applications open at an announced hour takes hundreds of legitimate sign-ins in minutes - so a
  per-IP or per-market cap tight enough to bother a distributed attacker throttles exactly that crowd
  at exactly that moment.
  There is deliberately **no per-market cap** (the market is what an attacker would aim at, so
  capping it hands them the outage), and nothing may spend *any* budget before passing the captcha.
  Refused requests are refunded rather than counted (`back-end/utils/rate_limit.py`), so a shared
  window cannot be held down by requests that were already turned away.

## Market Document Keys (Conventioner sharp edge)

- **The back end refuses to boot** unless `migrations/migrate_market_keys.py` has recorded its
  marker in the `schema_migrations` collection. A dev Mongo volume created before the migration
  existed has no marker, so an existing stack hits this on first pull. The fix is the migration
  itself: `docker compose run --rm backend python migrations/migrate_market_keys.py`
  (`run`, not `exec` - the back end is crash-looping). Do not "fix" it by softening the check:
  it fails closed because an unmigrated market is invisible, not broken.
- **Market documents are stored camelCase, and that is the only spelling reads may name.**
  Every write camel-cases the whole document, so a hand-written filter on `organization_id`
  matches nothing. Anything touching a raw document or a Mongo filter goes through
  `back-end/market_documents.py` (`market_doc_field`/`market_doc_filter`/`market_doc_set`/
  `market_from_document`). Do not add a read-time fallback that accepts both spellings: writes
  only refresh the camelCase key, so a legacy key holds a value that is stale forever.
  `front-end/e2e/access-control.spec.ts` pins the visibility that depends on this: a
  snake_case filter in the org-scoped market query is exactly the bug that once hid every
  org member's markets, and the suite's positive assertions catch it.
- **Parse stored markets with `market_from_document()`**, never `Market(**snake_dict)`.
  `Market.phase` defaults to `draft`, so a raw parse silently mislabels every market written
  before the field existed. `phase_from_market_document()` (`back-end/datatypes.py`) is the one
  source of truth for that mapping, and `MarketsApi.load_market_context()` is the shared
  market + organization + permission load every endpoint should use.

## Phase Transitions (Conventioner sharp edge)

- **Every precondition for every phase transition lives in `back-end/guards.py`.** Adding or
  removing one is a one-file edit: the `POST /markets/<id>/transition` endpoint and the
  front-end `BlockerPanel.vue` are generic over the `PreconditionResult` wire shape and must
  stay that way. `_validate_registry()` runs at import and refuses to load tables that disagree,
  so a misspelled phase or a dropped entry invariant is a startup error, not a silent no-op.
- `Market.phase` is server-owned: `create_market()` stamps `draft`, `update_market()` re-applies
  the stored phase, and the transition endpoint is the only writer on an existing market.
- **`phase` is the single source of truth for the market lifecycle; `is_draft` is derived from
  it.** `Market.is_draft` is a Pydantic `@computed_field` (true iff `phase == draft`) and is
  never independently writable: no request body can set it, and it is recomputed from the stored
  phase on every write. Nothing reads the stored value for a market whose `phase` this build
  understands. It is still *persisted*, and every writer keeps it in agreement with `phase` (create stamps both,
  `update_market()` re-derives it from the stored phase, the transition endpoint sets both in one
  atomic update), purely because it is the fallback `phase_from_market_document()` drops to when
  `phase` is missing or unrecognized - a fallback that contradicted the phase would answer
  confidently and wrongly. The two endpoints that serve a raw document rather than a parsed
  `Market` re-stamp `isDraft` from the effective phase before responding.
- **Publishing a CSV market is the `draft` → `archived` transition** (no guards), fired by the
  Done button in `GenerateAssignmentView.vue`. It used to be a `PUT` of `isDraft: false`; that
  route is gone, and this transition is now the only way a CSV market leaves `draft`.
  A legacy published market (`phase: "draft"` + `isDraft: false`) reads back as a *draft*, since
  `draft` is a phase this build recognizes and takes at face value - hence the migration below.
- **No Mongo condition can answer "is this market published?"** `{"phase": {"$ne": "draft"}}`
  also matches a document with no `phase` - which is exactly what a legacy *draft* looks like -
  so a filter like that would put an unpublished market on a public check-in URL. The public
  slug lookup prunes with `non_draft_market_prefilter()` (`back-end/market_documents.py`) and
  makes the draft decision in Python via `phase_from_market_document()`. The prefilter prunes;
  it does not judge. Keep it that way.
- **`migrations/migrate_is_draft_consistency.py`** repairs documents whose `isDraft` and `phase`
  disagree, in *opposite* directions depending on which build wrote them: a market the old build
  published (`phase: "draft"` + `isDraft: false`) has its **phase** advanced to `archived` - its
  `isDraft` was the only publish signal it ever had, and confirming it as a draft would take a
  live market's public check-in URL off the air - while a market with a non-draft `phase` and a
  stale `isDraft: true` has its `isDraft` recomputed. Documents with **no** `phase` are left
  alone; they are `migrate_phase.py`'s to backfill.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.

import { execFileSync } from 'node:child_process';

/**
 * Create a verified test user, idempotently.
 *
 * `/register-user` does NOT set `email_verified`, so a user created through it cannot log
 * in. `back-end/create_test_user.py` is the one place that creates a login-ready user, and
 * it is what `scripts/seed_fixture.sh` already runs for the fixture users; a spec that needs
 * its own users runs the same script rather than re-deriving the document shape. The script
 * is a no-op when the email already exists, so this is safe to call from every `beforeAll`.
 *
 * `E2E_BACKEND_CONTAINER` overrides the container name for worktree stacks that offset
 * theirs; the default matches `docker-compose.yml`, the same convention `seedApplication.ts`
 * and `legacyMarketDoc.ts` already use.
 */
export function ensureVerifiedUser(email: string, password: string): void {
  const container = process.env.E2E_BACKEND_CONTAINER || 'conventioner_backend';
  execFileSync(
    'docker',
    ['exec', container, 'python', '/app/create_test_user.py', email, password],
    { encoding: 'utf-8', timeout: 30_000 },
  );
}

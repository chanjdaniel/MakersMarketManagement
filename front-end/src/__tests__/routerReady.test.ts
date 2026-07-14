// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createRouter, createMemoryHistory, type Router } from 'vue-router';
import { defineComponent, h } from 'vue';

import { routerSettled } from '@/utils/routerReady';

/**
 * Two things wait for the first navigation: the mount, and the session probe in `App.vue` that
 * decides whether a visitor with no organizer session belongs on the login screen. `router.isReady()`
 * cannot serve them both, and the way it fails is silent - a promise that never settles, so the
 * caller simply stops running with no error anywhere.
 *
 * That is the whole reason `routerSettled` exists, and it is a claim about vue-router's internals, so
 * it is pinned against the real router rather than a mock: a version that changed this behavior would
 * make the helper pointless, and nothing else in this codebase would notice.
 */

const Home = defineComponent({ render: () => h('div', 'home') });

function routerThatFailsItsFirstNavigation(): Router {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', name: 'home', component: Home }],
  });
  // A lazy route chunk a deploy has replaced, or a guard that threw on a corrupt `localStorage.user`:
  // the first navigation rejects, and vue-router leaves the router permanently not-ready.
  router.beforeEach(() => {
    throw new Error('the first navigation failed');
  });
  return router;
}

/** Whether the promise has settled at all, once the microtask queue has been drained. */
async function settlesPromptly(promise: Promise<unknown>): Promise<boolean> {
  let done = false;
  promise.then(
    () => { done = true; },
    () => { done = true; },
  );
  for (let tick = 0; tick < 10; tick += 1) await Promise.resolve();
  return done;
}

describe('waiting for the first navigation', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('answers every caller once the first navigation has succeeded', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', name: 'home', component: Home }],
    });
    const mount = routerSettled(router);
    router.push('/');

    await expect(mount).resolves.toBeUndefined();
    await expect(routerSettled(router)).resolves.toBeUndefined();
  });

  it('answers every caller when the first navigation has failed, which is when it matters', async () => {
    const router = routerThatFailsItsFirstNavigation();

    // What `main.ts` waits on before it mounts: it resolves rather than rejecting, so the shell is
    // painted even when the router could not fill it - a blank page is a far worse failure than the
    // page the navigation was trying to reach.
    const mount = routerSettled(router);
    router.push('/').catch(() => {});
    await expect(mount).resolves.toBeUndefined();

    // And what `App.vue` waits on *after* mounting, which is the half that recovers the visitor: the
    // session probe sends an organizer with no session to `/login`, and it cannot do that if it never
    // gets past this line. Asking the router directly is exactly what hangs here - vue-router
    // rejected the handlers it had and emptied the set, so a second `isReady()` waits on a navigation
    // that already happened and that nothing is going to drive again.
    expect(await settlesPromptly(routerSettled(router))).toBe(true);
    expect(await settlesPromptly(router.isReady())).toBe(false);
  });
});

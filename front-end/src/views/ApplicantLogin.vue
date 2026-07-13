<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useApplicationStore } from '@/stores/application';
import { fetchPublicApplicationForm } from '@/utils/publicApplicationForm';

const route = useRoute();
const router = useRouter();
const store = useApplicationStore();

const marketSlug = computed(() => (route.params.marketSlug as string) || '');
const redirect = computed(() => (route.query.redirect as string) || 'dashboard');
const marketName = ref('');

// Step 1: enter email
const email = ref('');
const emailSent = ref(false);

// Step 2: enter verification code
const key = ref('');

const step = ref<'email' | 'key'>('email');
const submitting = ref(false);

onMounted(async () => {
  // Only a session for *this* market skips the sign-in; a token for another one signs in nobody here.
  if (store.isAuthenticatedFor(marketSlug.value)) {
    router.push({
      name: 'applicant-dashboard',
      params: { marketSlug: marketSlug.value },
    });
    return;
  }

  // The name is the only thing that tells the applicant which market they are signing in to. The
  // slug they are here from is a URL detail, and failing to fetch it is not worth an error on a
  // sign-in screen that works without it.
  try {
    marketName.value = (await fetchPublicApplicationForm(marketSlug.value)).marketName;
  } catch {
    marketName.value = '';
  }
});

async function requestKey() {
  if (!email.value.trim()) {
    store.error = 'Email address is required.';
    return;
  }
  store.error = null;
  submitting.value = true;
  await store.requestKey(marketSlug.value, email.value.trim().toLowerCase());
  submitting.value = false;
  if (!store.error) {
    emailSent.value = true;
    step.value = 'key';
  }
}

async function verifyKey() {
  if (!key.value.trim()) {
    store.error = 'Verification code is required.';
    return;
  }
  store.error = null;
  submitting.value = true;
  const ok = await store.verifyKey(
    marketSlug.value,
    email.value.trim().toLowerCase(),
    key.value.trim(),
  );
  submitting.value = false;
  if (ok) {
    router.push({
      name: redirect.value === 'apply' ? 'apply' : 'applicant-dashboard',
      params: { marketSlug: marketSlug.value },
    });
  }
}

function goBack() {
  step.value = 'email';
  key.value = '';
  store.error = null;
}
</script>

<template>
  <div class="login-page" data-testid="applicant-login-page">
    <header class="login-header">
      <h1>Sign In</h1>
      <p class="login-market" data-testid="applicant-login-market">
        {{ marketName || marketSlug }}
      </p>
    </header>

    <div v-if="store.error" class="login-error" data-testid="applicant-login-error">
      {{ store.error }}
    </div>

    <!-- Step 1: Email -->
    <template v-if="step === 'email'">
      <div class="login-step" data-testid="applicant-login-email-step">
        <p class="login-instruction">
          Enter the email address you used to apply.
          We'll send you a verification code.
        </p>
        <input
          v-model="email"
          class="login-input"
          type="email"
          placeholder="you@example.com"
          data-testid="applicant-login-email-input"
          @keyup.enter="requestKey"
        />
        <button
          class="login-btn"
          :disabled="submitting || !email.trim()"
          @click="requestKey"
          data-testid="applicant-login-request-btn"
        >
          {{ submitting ? 'Sending...' : 'Send Code' }}
        </button>
      </div>
    </template>

    <!-- Step 2: Verification code -->
    <template v-else>
      <div class="login-step" data-testid="applicant-login-key-step">
        <p class="login-instruction">
          We sent a 6-digit code to <strong>{{ email }}</strong>.
          Enter it below.
        </p>
        <input
          v-model="key"
          class="login-input login-key-input"
          type="text"
          inputmode="numeric"
          maxlength="6"
          placeholder="000000"
          data-testid="applicant-login-key-input"
          @keyup.enter="verifyKey"
        />
        <button
          class="login-btn"
          :disabled="submitting || key.trim().length !== 6"
          @click="verifyKey"
          data-testid="applicant-login-verify-btn"
        >
          {{ submitting ? 'Verifying...' : 'Verify & Sign In' }}
        </button>
        <div class="login-alt">
          <button class="login-link-btn" @click="goBack" data-testid="applicant-login-back-btn">
            Use a different email
          </button>
          <span class="login-sep">|</span>
          <button class="login-link-btn" :disabled="submitting" @click="requestKey" data-testid="applicant-login-resend-btn">
            Resend code
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.login-page {
  max-width: 420px;
  margin: 60px auto;
  padding: 0 16px;
}

.login-header {
  text-align: center;
  margin-bottom: 24px;
}

.login-header h1 {
  font-family: 'Merge One';
  font-size: 24px;
  color: var(--mm-black);
  margin: 0 0 4px;
}

.login-market {
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #666);
  margin: 0;
}

.login-error {
  background: #f8d7da;
  border: 1px solid var(--mm-red, #cc0000);
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 16px;
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: #721c24;
}

.login-step {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.login-instruction {
  font-family: 'Outfit Regular';
  font-size: 14px;
  color: var(--mm-grey, #666);
  margin: 0;
  line-height: 1.5;
}

.login-input {
  height: 44px;
  padding: 4px 12px;
  font-family: 'Outfit Regular';
  font-size: 16px;
  border: 1px solid var(--mm-grey, #b0b0b0);
  border-radius: 5px;
}

.login-key-input {
  letter-spacing: 12px;
  text-align: center;
  font-size: 24px;
}

.login-btn {
  height: 44px;
  background: var(--mm-green);
  color: white;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  font-family: 'Merge One';
  font-size: 16px;
}

.login-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.login-alt {
  display: flex;
  flex-direction: row;
  justify-content: center;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.login-link-btn {
  background: none;
  border: none;
  color: var(--mm-grey, #666);
  cursor: pointer;
  font-family: 'Outfit Regular';
  font-size: 13px;
  text-decoration: underline;
  padding: 0;
}

.login-link-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.login-sep {
  color: var(--mm-grey, #ccc);
}
</style>

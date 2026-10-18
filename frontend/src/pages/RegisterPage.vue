<script setup lang="ts">
import AuthShell from '@/components/securfile/AuthShell.vue'
import { computed, nextTick, onUnmounted, reactive, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ArrowLeft, Download, KeyRound, ShieldCheck, UserPlus } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { authApi } from '@/api/auth_api'
import { apiErrorMessage } from '@/api/http'
import PasswordField from '@/components/PasswordField.vue'
import { useAuthStore } from '@/stores/auth_store'
import { enrolAccountKey } from '@/utils/account-crypto'

const route = useRoute()
const { t } = useI18n()

// Arriving straight from a deletion. Saying so beats a bare registration form for someone
// who has just destroyed an account on purpose and is expecting to start over.
const afterDeletion = computed(() => route.query.deleted === '1')
import {
  weakPassphraseMessage,
  weakPassphraseReason,
  PASSPHRASE_MIN_LENGTH,
  PASSWORD_MIN_LENGTH,
  passwordRequirementHint,
  evaluatePassword,
  passphraseLength,
} from '@/utils/password-policy'

const USERNAME_MIN_LENGTH = 3
const USERNAME_MAX_LENGTH = 100
const USERNAME_PATTERN = /^[A-Za-z0-9_.-]+$/

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const passphrase = ref('')
const verificationCode = ref('')

const errorMessage = ref('')
const codeNotice = ref('')
const isSendingCode = ref(false)
const isSubmitting = ref(false)
const progressLabel = ref('')
const cooldownSeconds = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | undefined

const privateKeyPem = ref('')
const publicKeyFingerprint = ref('')
const keyAcknowledged = ref(false)

/**
 * Two steps, because one form asking for a password, a second password with different rules,
 * an email and a code was the hardest part of a first-time walkthrough. Step one is the
 * account; step two is the encryption passphrase alone, with why it exists.
 */
const step = ref<1 | 2>(1)
/** Signed in straight after registering, so the user is not asked to sign in again. */
const signedIn = ref(false)
const auth = useAuthStore()

/**
 * Registration validates on submit, not by disabling the button.
 *
 * A disabled Register button cannot explain itself: the user is left comparing
 * their password against a placeholder to guess which rule they missed. So the
 * button stays live, every rule is checked on click, and the first field that
 * fails is named and focused. A rule is also shown early once the user has left
 * that field, which is the point they have finished their thought about it.
 */
type FieldName = 'username' | 'password' | 'confirmPassword' | 'passphrase' | 'email' | 'code'

const touched = reactive<Record<FieldName, boolean>>({
  username: false,
  password: false,
  confirmPassword: false,
  passphrase: false,
  email: false,
  code: false,
})
const hasAttemptedSubmit = ref(false)

const usernameInput = ref<HTMLInputElement | null>(null)
const emailInput = ref<HTMLInputElement | null>(null)
const codeInput = ref<HTMLInputElement | null>(null)
const passwordField = ref<InstanceType<typeof PasswordField> | null>(null)
const confirmPasswordField = ref<InstanceType<typeof PasswordField> | null>(null)
const passphraseField = ref<InstanceType<typeof PasswordField> | null>(null)

const emailLooksValid = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim()))

/** The password must not be built out of the account details it protects. */
const passwordCheck = computed(() =>
  evaluatePassword(password.value, [username.value.trim(), email.value.trim()]),
)

const errors = computed<Record<FieldName, string>>(() => {
  const trimmedUsername = username.value.trim()

  let usernameError = ''
  if (trimmedUsername.length < USERNAME_MIN_LENGTH) {
    usernameError = t('register.usernameTooShort', { min: USERNAME_MIN_LENGTH })
  } else if (trimmedUsername.length > USERNAME_MAX_LENGTH) {
    usernameError = t('register.usernameTooLong', { max: USERNAME_MAX_LENGTH })
  } else if (!USERNAME_PATTERN.test(trimmedUsername)) {
    usernameError = t('register.usernameCharacters')
  }

  let confirmError = ''
  if (confirmPassword.value.length === 0) {
    confirmError = t('register.confirmEmpty')
  } else if (confirmPassword.value !== password.value) {
    confirmError = t('register.confirmMismatch')
  }

  let passphraseError = ''
  const currentPassphraseLength = passphraseLength(passphrase.value)
  if (currentPassphraseLength === 0) {
    passphraseError = t('passphrase.enter')
  } else if (currentPassphraseLength < PASSPHRASE_MIN_LENGTH) {
    passphraseError = t('passphrase.tooShort', { min: PASSPHRASE_MIN_LENGTH, length: currentPassphraseLength })
  } else if (passphrase.value === password.value) {
    passphraseError = t('passphrase.sameAsPassword')
  } else {
    passphraseError = weakPassphraseMessage(
      weakPassphraseReason(passphrase.value, [username.value.trim(), email.value.trim()]),
    )
  }

  return {
    username: usernameError,
    password: passwordCheck.value.message,
    confirmPassword: confirmError,
    passphrase: passphraseError,
    email: emailLooksValid.value ? '' : t('register.emailInvalid'),
    code: /^\d{6}$/.test(verificationCode.value.trim())
      ? ''
      : t('register.codeInvalid'),
  }
})

/** Field order here is the order on screen, so "first problem" means the top one. */
const FIELD_ORDER: readonly FieldName[] = [
  'username',
  'password',
  'confirmPassword',
  'passphrase',
  'email',
  'code',
]

const STEP_ONE: readonly FieldName[] = ['username', 'password', 'confirmPassword', 'email', 'code']

async function goToStepTwo() {
  for (const field of STEP_ONE) markTouched(field)
  const firstInvalid = STEP_ONE.find((field) => errors.value[field] !== '')
  if (firstInvalid) {
    errorMessage.value = t('register.fixErrors')
    focusField(firstInvalid)
    return
  }
  errorMessage.value = ''
  step.value = 2
  await nextTick()
  focusField('passphrase')
}

function backToStepOne() {
  errorMessage.value = ''
  step.value = 1
}

/**
 * Sign in with the credentials just registered. The account key is not opened here: uploading
 * only needs the public key, and every decrypted download or share asks for the passphrase
 * anyway. Failing is not an error: the key page then offers sign-in.
 */
async function signInAfterRegistering() {
  try {
    const res = await authApi.login({ username: username.value.trim(), password: password.value })
    const token = res.data?.data?.access_token
    if (!token) return
    auth.setSession(token, res.data?.data?.refresh_token ?? '')
    signedIn.value = true
  } catch {
    // Throttled: the user signs in from the login page as before.
  }
}

function errorFor(field: FieldName): string {
  if (!hasAttemptedSubmit.value && !touched[field]) return ''
  return errors.value[field]
}

function markTouched(field: FieldName) {
  touched[field] = true
}

function focusField(field: FieldName) {
  const targets: Record<FieldName, { focus: () => void } | null> = {
    username: usernameInput.value,
    password: passwordField.value,
    confirmPassword: confirmPasswordField.value,
    passphrase: passphraseField.value,
    email: emailInput.value,
    code: codeInput.value,
  }
  targets[field]?.focus()
}

function startCooldown(seconds: number) {
  cooldownSeconds.value = seconds
  clearInterval(cooldownTimer)
  cooldownTimer = setInterval(() => {
    cooldownSeconds.value -= 1
    if (cooldownSeconds.value <= 0) {
      clearInterval(cooldownTimer)
      cooldownSeconds.value = 0
    }
  }, 1000)
}

onUnmounted(() => clearInterval(cooldownTimer))

async function sendCode() {
  if (isSendingCode.value || cooldownSeconds.value > 0) return
  // The same rule as Register: the button explains the problem instead of hiding it.
  if (!emailLooksValid.value) {
    markTouched('email')
    focusField('email')
    return
  }
  isSendingCode.value = true
  errorMessage.value = ''
  codeNotice.value = ''
  try {
    const response = await authApi.sendVerificationCode({
      email: email.value.trim(),
      purpose: 'REGISTRATION',
    })
    const data = response.data.data
    const minutes = Math.max(1, Math.round(data.expires_in_seconds / 60))
    codeNotice.value = t('register.codeSent', { email: email.value.trim(), minutes })
    startCooldown(data.resend_available_in_seconds)
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, t('register.codeSendFailed'))
  } finally {
    isSendingCode.value = false
  }
}

async function register() {
  if (isSubmitting.value) return

  hasAttemptedSubmit.value = true
  const firstInvalid = FIELD_ORDER.find((field) => errors.value[field] !== '')
  if (firstInvalid) {
    errorMessage.value = t('register.fixErrors')
    if (STEP_ONE.includes(firstInvalid)) step.value = 1
    await nextTick()
    focusField(firstInvalid)
    return
  }

  isSubmitting.value = true
  errorMessage.value = ''
  codeNotice.value = ''
  try {
    // Generating a 3072-bit RSA key and running Argon2id takes a moment and
    // blocks the main thread, so the button reports each stage.
    progressLabel.value = t('register.progressKey')
    const { keyMaterial, privateKeyPem: generatedPem } = await enrolAccountKey(passphrase.value)

    progressLabel.value = t('register.progressAccount')
    const response = await authApi.register({
      username: username.value.trim(),
      email: email.value.trim(),
      password: password.value,
      verification_code: verificationCode.value.trim(),
      key_material: keyMaterial,
    })

    progressLabel.value = t('register.progressSignIn')
    await signInAfterRegistering()

    privateKeyPem.value = generatedPem
    publicKeyFingerprint.value = response.data.data.public_key_fingerprint
    // The passphrase has done its job; drop it from component state.
    passphrase.value = ''
    password.value = ''
    confirmPassword.value = ''
    verificationCode.value = ''
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, t('register.failed'))
  } finally {
    isSubmitting.value = false
    progressLabel.value = ''
  }
}

function downloadPrivateKey() {
  const blob = new Blob([privateKeyPem.value], { type: 'application/x-pem-file' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `secureview-private-key-${username.value.trim() || 'account'}.pem`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <AuthShell>
    <div class="w-full rounded-xl border border-border bg-card p-8">
      <template v-if="!privateKeyPem">
        <div class="flex items-center gap-2 mb-6">
          <div class="p-2 rounded-lg bg-primary/10">
            <UserPlus class="h-5 w-5 text-primary" />
          </div>
          <h1 class="text-2xl font-bold text-foreground">{{ t('register.title') }}</h1>
        </div>

        <p
          v-if="afterDeletion"
          class="text-sm rounded-md border border-border bg-secondary/60 text-foreground px-3 py-2 mb-4"
        >
          {{ t('register.afterDeletion') }}
        </p>

        <p class="mb-4 text-xs font-medium text-muted-foreground" data-testid="register-step">
          {{ t('register.stepOf', { step, total: 2 }) }} · {{ step === 1 ? t('register.stepAccount') : t('register.stepEncryption') }}
        </p>

        <form novalidate @submit.prevent="step === 1 ? goToStepTwo() : register()">
          <template v-if="step === 1">
          <label for="register-username" class="text-sm text-foreground mb-2 block">
            {{ t('login.username') }} <span class="text-destructive">*</span>
          </label>
          <input
            id="register-username"
            ref="usernameInput"
            v-model="username"
            :placeholder="t('login.username')"
            autocomplete="username"
            :aria-invalid="errorFor('username') ? 'true' : undefined"
            class="h-10 w-full rounded-md border bg-secondary px-3 text-foreground"
            :class="errorFor('username') ? 'border-destructive' : 'border-border'"
            @blur="markTouched('username')"
          />
          <p v-if="errorFor('username')" class="text-xs text-destructive mt-1" role="alert">
            {{ errorFor('username') }}
          </p>
          <div class="mb-4" />
          <PasswordField
            ref="passwordField"
            v-model="password"
            :label="t('login.password')"
            :placeholder="t('register.atLeastCharacters', { min: PASSWORD_MIN_LENGTH })"
            :hint="passwordRequirementHint()"
            :error="errorFor('password')"
            @blur="markTouched('password')"
          />
          <div class="mb-4" />
          <PasswordField
            ref="confirmPasswordField"
            v-model="confirmPassword"
            :label="t('register.confirmPassword')"
            :placeholder="t('register.confirmPlaceholder')"
            :error="errorFor('confirmPassword')"
            @blur="markTouched('confirmPassword')"
          />
          <div class="mb-4" />
          <label for="register-email" class="text-sm text-foreground mb-2 block">
            {{ t('register.email') }} <span class="text-destructive">*</span>
          </label>
          <input
            id="register-email"
            ref="emailInput"
            v-model="email"
            placeholder="you@example.com"
            type="email"
            autocomplete="email"
            :aria-invalid="errorFor('email') ? 'true' : undefined"
            class="h-10 w-full rounded-md border bg-secondary px-3 text-foreground"
            :class="errorFor('email') ? 'border-destructive' : 'border-border'"
            @blur="markTouched('email')"
          />
          <p v-if="errorFor('email')" class="text-xs text-destructive mt-1" role="alert">
            {{ errorFor('email') }}
          </p>
          <div class="mb-4" />
          <label for="register-code" class="text-sm text-foreground mb-2 block">
            {{ t('register.code') }} <span class="text-destructive">*</span>
          </label>
          <div class="flex gap-2">
            <input
              id="register-code"
              ref="codeInput"
              v-model="verificationCode"
              :placeholder="t('register.codePlaceholder')"
              inputmode="numeric"
              maxlength="6"
              autocomplete="one-time-code"
              :aria-invalid="errorFor('code') ? 'true' : undefined"
              class="h-11 min-w-0 flex-1 rounded-md border bg-secondary px-3 text-foreground tracking-widest"
              :class="errorFor('code') ? 'border-destructive' : 'border-border'"
              @blur="markTouched('code')"
            />
            <button
              type="button"
              class="h-11 shrink-0 rounded-md border border-border px-3 text-sm text-foreground hover:bg-secondary disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isSendingCode || cooldownSeconds > 0"
              @click="sendCode"
            >
              <span v-if="isSendingCode">{{ t('register.sending') }}</span>
              <span v-else-if="cooldownSeconds > 0">{{ t('register.resendIn', { seconds: cooldownSeconds }) }}</span>
              <span v-else>{{ t('register.sendCode') }}</span>
            </button>
          </div>
          <p v-if="errorFor('code')" class="text-xs text-destructive mt-1" role="alert">
            {{ errorFor('code') }}
          </p>
          <p v-if="codeNotice" class="text-xs text-muted-foreground mt-1">{{ codeNotice }}</p>
          <div class="mb-6" />

          <button
            type="submit"
            class="w-full h-11 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {{ t('register.next') }}
          </button>
          </template>

          <template v-else>
          <div class="mb-4 rounded-lg border border-border bg-secondary/50 p-3" data-testid="two-secrets">
            <p class="flex items-center gap-1.5 text-sm font-medium text-foreground">
              <ShieldCheck class="h-4 w-4 shrink-0 text-primary" />
              {{ t('register.twoSecretsTitle') }}
            </p>
            <p class="mt-1 text-xs text-muted-foreground">{{ t('register.twoSecretsBody') }}</p>
          </div>
          <PasswordField
            ref="passphraseField"
            v-model="passphrase"
            :label="t('passphrase.label')"
            :placeholder="t('register.passphrasePlaceholder', { min: PASSPHRASE_MIN_LENGTH })"
            :error="errorFor('passphrase')"
            @blur="markTouched('passphrase')"
          >
            <template #hint>
              <p class="text-xs text-muted-foreground mt-1 flex gap-1.5">
                <ShieldCheck class="h-4 w-4 shrink-0 text-primary" />
                <span>{{ t('register.passphraseHint') }}</span>
              </p>
            </template>
          </PasswordField>
          <div class="mb-4" />
          <div class="mb-2" />

          <button
            type="submit"
            class="w-full h-11 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="isSubmitting"
          >
            {{ progressLabel || t('register.submit') }}
          </button>
          <button
            type="button"
            class="mt-2 w-full h-10 rounded-md border border-border text-sm text-foreground hover:bg-secondary inline-flex items-center justify-center gap-2 disabled:opacity-50"
            :disabled="isSubmitting"
            @click="backToStepOne"
          >
            <ArrowLeft class="h-4 w-4" />
            {{ t('register.back') }}
          </button>
          </template>
        </form>

        <p v-if="errorMessage" class="text-sm text-destructive mt-3" role="alert">
          {{ errorMessage }}
        </p>

        <p class="text-sm text-muted-foreground mt-6 text-center">
          {{ t('register.haveAccount') }}
          <RouterLink to="/login" class="inline-flex min-h-10 items-center text-primary hover:underline">{{ t('register.signIn') }}</RouterLink>
        </p>
      </template>

      <template v-else>
        <div class="flex items-center gap-2 mb-4">
          <div class="p-2 rounded-lg bg-primary/10">
            <KeyRound class="h-5 w-5 text-primary" />
          </div>
          <h1 class="text-2xl font-bold text-foreground">{{ t('register.saveKeyTitle') }}</h1>
        </div>

        <p class="text-sm text-muted-foreground mb-4">{{ t('register.saveKeyIntro') }}</p>

        <i18n-t keypath="register.saveKeyWhy" tag="p" class="text-sm text-muted-foreground mb-4" scope="global">
          <template #saveIt><strong class="text-foreground">{{ t('register.saveIt') }}</strong></template>
          <template #pem><code class="text-xs">.pem</code></template>
        </i18n-t>

        <p class="text-sm text-muted-foreground mb-4">{{ t('register.saveKeySecret') }}</p>

        <textarea
          :value="privateKeyPem"
          rows="9"
          readonly
          class="w-full rounded-md border border-border bg-background p-3 text-xs font-mono"
        />

        <p class="text-xs text-muted-foreground mt-2 break-all">
          {{ t('register.fingerprint') }} <span class="font-mono">{{ publicKeyFingerprint }}</span>
        </p>

        <button
          type="button"
          class="mt-4 w-full h-10 rounded-md border border-border text-sm text-foreground hover:bg-secondary flex items-center justify-center gap-2"
          @click="downloadPrivateKey"
        >
          <Download class="h-4 w-4" />
          {{ t('register.downloadKey') }}
        </button>

        <label class="flex items-start gap-2 mt-4 text-sm text-foreground">
          <input v-model="keyAcknowledged" type="checkbox" class="mt-1 h-5 w-5 shrink-0" />
          <span>{{ t('register.keyAcknowledge') }}</span>
        </label>

        <RouterLink
          :to="signedIn ? '/dashboard' : '/login'"
          class="mt-4 w-full h-11 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 flex items-center justify-center"
          :class="keyAcknowledged ? '' : 'pointer-events-none opacity-50'"
        >
          {{ signedIn ? t('register.continueToWorkspace') : t('register.continue') }}
        </RouterLink>
      </template>
    </div>
  </AuthShell>
</template>

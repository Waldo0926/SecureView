<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Eye, EyeOff, KeyRound, Lock, Play, RotateCcw, Unlock } from 'lucide-vue-next'
import {
  RSA_DEMO,
  aesDecrypt,
  aesEncrypt,
  caesarDecrypt,
  caesarEncrypt,
  caesarSteps,
  railFenceDecrypt,
  railFenceEncrypt,
  railFenceSteps,
  rsaToyDecrypt,
  rsaToyEncrypt,
  rsaToyStepsFromCiphertext,
  vigenereDecrypt,
  vigenereEncrypt,
  vigenereSteps,
  type AesEncryptResult,
  type RsaStep,
} from '@/utils/crypto-playground'

type PlayMode = 'caesar' | 'vigenere' | 'railfence' | 'aes' | 'rsa'

const mode = ref<PlayMode>('caesar')
const plaintext = ref('HELLO SECUREVIEW')
const key = ref('3')
const output = ref('')
const errorMessage = ref('')
const isProcessing = ref(false)
const animateStep = ref(-1)
const aesMeta = ref<AesEncryptResult | null>(null)
const rsaSteps = ref<RsaStep[]>([])
const showAesKey = ref(false)

const modes: { id: PlayMode; label: string; hint: string }[] = [
  { id: 'caesar', label: 'Caesar', hint: 'Shift: 1–25 (e.g. 3)' },
  { id: 'vigenere', label: 'Vigenère', hint: 'Keyword (e.g. KEY)' },
  { id: 'railfence', label: 'Rail Fence', hint: 'Number of rails: 2–10' },
  { id: 'aes', label: 'AES', hint: 'Password used to derive an AES-256 key' },
  { id: 'rsa', label: 'RSA', hint: 'Uses a demo public / private key pair' },
]

const currentMode = computed(() => modes.find((m) => m.id === mode.value)!)

const caesarShift = computed(() => {
  const n = parseInt(key.value, 10)
  return Number.isFinite(n) ? n : 3
})

const railCount = computed(() => {
  const n = parseInt(key.value, 10)
  return Number.isFinite(n) ? Math.max(2, Math.min(10, n)) : 3
})

const visualSteps = computed(() => {
  if (mode.value === 'caesar' && plaintext.value) {
    return caesarSteps(plaintext.value, caesarShift.value)
  }
  return []
})

const vigenereVisual = computed(() => {
  if (mode.value === 'vigenere' && plaintext.value && key.value) {
    return vigenereSteps(plaintext.value, key.value)
  }
  return []
})

const railVisual = computed(() => {
  if (mode.value === 'railfence' && plaintext.value) {
    return railFenceSteps(plaintext.value, railCount.value)
  }
  return []
})

const inputLabel = computed(() => {
  if (mode.value === 'aes') return 'Plaintext or AES ciphertext (Base64)'
  if (mode.value === 'rsa') return 'Plaintext or RSA ciphertext numbers'
  return 'Input Text'
})

async function runEncrypt() {
  errorMessage.value = ''
  isProcessing.value = true
  animateStep.value = -1
  aesMeta.value = null
  rsaSteps.value = []
  try {
    if (mode.value === 'caesar') {
      await animateCaesar()
      output.value = caesarEncrypt(plaintext.value, caesarShift.value)
    } else if (mode.value === 'vigenere') {
      if (!key.value.trim()) throw new Error('Keyword is required')
      output.value = vigenereEncrypt(plaintext.value, key.value)
    } else if (mode.value === 'railfence') {
      output.value = railFenceEncrypt(plaintext.value, railCount.value)
    } else if (mode.value === 'aes') {
      if (!key.value.trim()) throw new Error('Password is required for AES')
      const result = await aesEncrypt(plaintext.value, key.value)
      aesMeta.value = result
      output.value = result.ciphertext
    } else {
      const result = rsaToyEncrypt(plaintext.value)
      rsaSteps.value = result.steps
      output.value = result.ciphertext
    }
  } catch (e) {
    errorMessage.value = (e instanceof Error && e.message) || 'Encryption failed'
    output.value = ''
  } finally {
    isProcessing.value = false
  }
}

async function runDecrypt() {
  errorMessage.value = ''
  isProcessing.value = true
  rsaSteps.value = []
  try {
    if (mode.value === 'caesar') {
      output.value = caesarDecrypt(plaintext.value, caesarShift.value)
    } else if (mode.value === 'vigenere') {
      if (!key.value.trim()) throw new Error('Keyword is required')
      output.value = vigenereDecrypt(plaintext.value, key.value)
    } else if (mode.value === 'railfence') {
      output.value = railFenceDecrypt(plaintext.value, railCount.value)
    } else if (mode.value === 'aes') {
      if (!key.value.trim()) throw new Error('Password is required for AES')
      output.value = await aesDecrypt(plaintext.value, key.value)
      aesMeta.value = null
    } else {
      output.value = rsaToyDecrypt(plaintext.value)
      rsaSteps.value = rsaToyStepsFromCiphertext(plaintext.value)
    }
  } catch (e) {
    // Some browser errors carry an empty message; never leave the error line blank.
    errorMessage.value = (e instanceof Error && e.message) || 'Decryption failed'
    output.value = ''
  } finally {
    isProcessing.value = false
  }
}

function animateCaesar(): Promise<void> {
  return new Promise((resolve) => {
    const steps = caesarSteps(plaintext.value, caesarShift.value)
    animateStep.value = 0
    let i = 0
    const tick = () => {
      animateStep.value = i
      i++
      if (i >= steps.length) {
        setTimeout(resolve, 300)
        return
      }
      setTimeout(tick, 120)
    }
    tick()
  })
}

function reset() {
  plaintext.value = 'HELLO SECUREVIEW'
  key.value = defaultKeyForMode(mode.value)
  output.value = ''
  errorMessage.value = ''
  animateStep.value = -1
  aesMeta.value = null
  rsaSteps.value = []
}

function defaultKeyForMode(m: PlayMode): string {
  if (m === 'caesar') return '3'
  if (m === 'vigenere') return 'KEY'
  if (m === 'railfence') return '3'
  if (m === 'aes') return 'my-secret-password'
  return ''
}

watch(mode, (m) => {
  key.value = defaultKeyForMode(m)
  output.value = ''
  errorMessage.value = ''
  animateStep.value = -1
  aesMeta.value = null
  rsaSteps.value = []
  showAesKey.value = false
})
</script>

<template>
  <div class="rounded-xl border border-border bg-card overflow-hidden">
    <div class="border-b border-border px-6 py-4 flex flex-wrap items-center justify-between gap-4">
      <div>
        <h3 class="text-lg font-semibold text-foreground">Encryption Playground</h3>
        <p class="text-sm text-muted-foreground">Try classic ciphers and modern algorithms — all processing happens in your browser.</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="m in modes"
          :key="m.id"
          type="button"
          class="h-9 px-3 rounded-md text-sm font-medium transition-colors"
          :class="mode === m.id ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground hover:text-foreground'"
          @click="mode = m.id"
        >
          {{ m.label }}
        </button>
      </div>
    </div>

    <div class="p-6 md:p-8 space-y-6">
      <div class="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-muted-foreground">
        <template v-if="mode === 'caesar'">
          Each letter shifts forward by <strong class="text-foreground">{{ caesarShift }}</strong> positions in the alphabet. A→{{ caesarEncrypt('A', caesarShift) }}.
        </template>
        <template v-else-if="mode === 'vigenere'">
          <strong class="text-foreground">Vigenère</strong> uses a repeating keyword — each letter shifts by a different amount based on the key.
        </template>
        <template v-else-if="mode === 'railfence'">
          <strong class="text-foreground">Rail Fence</strong> writes text in a zigzag across {{ railCount }} rows, then reads row by row.
        </template>
        <template v-else-if="mode === 'aes'">
          <strong class="text-foreground">AES-256-GCM</strong> derives a 256-bit key from your password with PBKDF2, then encrypts the text. This is real browser cryptography.
          (SecureView itself never turns a password into a file key: every file gets a random key, and your passphrase, stretched with Argon2id, only opens your private key.)
        </template>
        <template v-else>
          <strong class="text-foreground">RSA</strong> encrypts with the public key <code class="text-foreground">(n={{ RSA_DEMO.n }}, e={{ RSA_DEMO.e }})</code> and decrypts with the private key <code class="text-foreground">d={{ RSA_DEMO.d }}</code>. Tiny demo primes — for learning only.
        </template>
      </div>

      <div class="grid md:grid-cols-2 gap-4">
        <div>
          <label class="text-sm font-medium text-foreground mb-2 block">{{ inputLabel }}</label>
          <textarea
            v-model="plaintext"
            rows="3"
            class="w-full rounded-md border border-border bg-secondary/50 px-3 py-2 text-sm font-mono resize-y"
            placeholder="Enter text to encrypt or decrypt..."
          />
        </div>
        <div v-if="mode !== 'rsa'">
          <label class="text-sm font-medium text-foreground mb-2 block">
            {{ mode === 'aes' ? 'Password' : 'Key' }}
          </label>
          <div class="relative">
            <input
              v-model="key"
              :type="mode === 'aes' && !showAesKey ? 'password' : 'text'"
              class="w-full h-10 rounded-md border border-border bg-secondary/50 px-3 text-sm font-mono"
              :class="mode === 'aes' ? 'pr-11' : ''"
              :placeholder="currentMode.hint"
            />
            <button
              v-if="mode === 'aes'"
              type="button"
              class="absolute right-1 top-1/2 -translate-y-1/2 h-8 w-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
              :title="showAesKey ? 'Hide password' : 'Show password'"
              :aria-label="showAesKey ? 'Hide password' : 'Show password'"
              @click="showAesKey = !showAesKey"
            >
              <EyeOff v-if="showAesKey" class="h-4 w-4" />
              <Eye v-else class="h-4 w-4" />
            </button>
          </div>
          <p class="text-xs text-muted-foreground mt-1.5">{{ currentMode.hint }}</p>
        </div>
        <div v-else class="rounded-lg border border-border bg-secondary/30 p-4">
          <p class="text-xs font-medium text-muted-foreground mb-3 flex items-center gap-1.5">
            <KeyRound class="h-3.5 w-3.5" />
            Demo RSA Key Pair
          </p>
          <div class="grid grid-cols-2 gap-2 text-xs font-mono">
            <div>
              <p class="text-muted-foreground">Public key</p>
              <p class="text-foreground mt-1">n = {{ RSA_DEMO.n }}</p>
              <p class="text-foreground">e = {{ RSA_DEMO.e }}</p>
            </div>
            <div>
              <p class="text-muted-foreground">Private key</p>
              <p class="text-foreground mt-1">d = {{ RSA_DEMO.d }}</p>
              <p class="text-foreground">p={{ RSA_DEMO.p }}, q={{ RSA_DEMO.q }}</p>
            </div>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap gap-3">
        <button
          type="button"
          class="h-10 px-5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 inline-flex items-center gap-2 text-sm font-medium disabled:opacity-50"
          :disabled="isProcessing"
          @click="runEncrypt"
        >
          <Lock class="h-4 w-4" />
          Encrypt
        </button>
        <button
          type="button"
          class="h-10 px-5 rounded-md border border-border text-foreground hover:bg-secondary inline-flex items-center gap-2 text-sm font-medium disabled:opacity-50"
          :disabled="isProcessing"
          @click="runDecrypt"
        >
          <Unlock class="h-4 w-4" />
          Decrypt
        </button>
        <button
          type="button"
          class="h-10 px-5 rounded-md text-muted-foreground hover:bg-secondary inline-flex items-center gap-2 text-sm"
          @click="reset"
        >
          <RotateCcw class="h-4 w-4" />
          Reset
        </button>
      </div>

      <p v-if="errorMessage" class="text-sm text-destructive">{{ errorMessage }}</p>

      <div v-if="output" class="rounded-lg border border-border bg-secondary/30 p-4">
        <p class="text-xs font-medium text-muted-foreground mb-2">Output</p>
        <p class="text-sm font-mono text-foreground break-all">{{ output }}</p>
      </div>

      <div v-if="mode === 'caesar' && plaintext" class="rounded-lg border border-border p-4">
        <p class="text-xs font-medium text-muted-foreground mb-3 flex items-center gap-1.5">
          <Play class="h-3.5 w-3.5" />
          Visual: Character Shift (+{{ caesarShift }})
        </p>
        <div class="flex flex-wrap gap-2">
          <div
            v-for="(step, i) in visualSteps"
            :key="i"
            class="flex flex-col items-center gap-1 transition-all duration-200"
            :class="animateStep >= i ? 'opacity-100 scale-100' : 'opacity-40 scale-95'"
          >
            <span class="text-xs text-muted-foreground font-mono">{{ step.char }}</span>
            <span class="text-[10px] text-primary">↓</span>
            <span
              class="h-8 w-8 rounded-md flex items-center justify-center text-sm font-mono font-bold"
              :class="animateStep >= i ? 'bg-primary text-primary-foreground' : 'bg-secondary text-foreground'"
            >
              {{ step.shifted }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="mode === 'vigenere' && vigenereVisual.length" class="rounded-lg border border-border p-4 overflow-x-auto">
        <p class="text-xs font-medium text-muted-foreground mb-3">Visual: Keyword Shift per Character</p>
        <div class="flex gap-3 min-w-max">
          <div v-for="(step, i) in vigenereVisual" :key="i" class="flex flex-col items-center gap-1 text-center">
            <span class="text-xs font-mono text-muted-foreground">{{ step.char }}</span>
            <span class="text-[10px] text-primary font-mono">+{{ step.keyChar }} ({{ step.shift }})</span>
            <span class="h-8 w-8 rounded-md bg-primary/15 text-primary flex items-center justify-center text-sm font-mono font-bold">
              {{ step.output }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="mode === 'railfence' && railVisual.length" class="rounded-lg border border-border p-4">
        <p class="text-xs font-medium text-muted-foreground mb-3">Visual: Zigzag on {{ railCount }} Rails</p>
        <div class="space-y-1 font-mono text-sm">
          <div
            v-for="r in railCount"
            :key="r"
            class="flex gap-1 min-h-[2rem] items-center"
          >
            <span class="w-12 text-[10px] text-muted-foreground">Rail {{ r }}</span>
            <span
              v-for="(step, i) in railVisual.filter((s) => s.row === r - 1)"
              :key="i"
              class="h-8 w-8 rounded bg-primary/15 text-primary flex items-center justify-center font-bold"
            >
              {{ step.char }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="mode === 'aes' && aesMeta" class="rounded-lg border border-border p-4 space-y-3">
        <p class="text-xs font-medium text-muted-foreground">Visual: AES-256-GCM Pipeline</p>
        <div class="grid sm:grid-cols-3 gap-3 text-xs">
          <div class="rounded-md bg-secondary/50 p-3">
            <p class="text-muted-foreground mb-1">1. Password → key</p>
            <p class="font-mono text-foreground break-all">{{ aesMeta.keyHex.slice(0, 32) }}…</p>
          </div>
          <div class="rounded-md bg-secondary/50 p-3">
            <p class="text-muted-foreground mb-1">2. Random IV</p>
            <p class="font-mono text-foreground break-all">{{ aesMeta.ivHex }}</p>
          </div>
          <div class="rounded-md bg-secondary/50 p-3">
            <p class="text-muted-foreground mb-1">3. Ciphertext (Base64)</p>
            <p class="font-mono text-foreground break-all">{{ aesMeta.ciphertext.slice(0, 24) }}…</p>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">To decrypt, paste the Base64 output into the input box and use the same password.</p>
      </div>

      <div v-if="mode === 'rsa' && rsaSteps.length" class="rounded-lg border border-border p-4 overflow-x-auto">
        <p class="text-xs font-medium text-muted-foreground mb-3">Visual: c = m<sup>e</sup> mod n</p>
        <div class="flex gap-3 min-w-max">
          <div v-for="(step, i) in rsaSteps" :key="i" class="flex flex-col items-center gap-1 text-center min-w-[4.5rem]">
            <span class="text-xs font-mono text-muted-foreground">{{ step.char }} ({{ step.m }})</span>
            <span class="text-[10px] text-primary font-mono">^{{ RSA_DEMO.e }} mod {{ RSA_DEMO.n }}</span>
            <span class="h-8 px-2 rounded-md bg-primary/15 text-primary flex items-center justify-center text-xs font-mono font-bold">
              {{ step.c }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

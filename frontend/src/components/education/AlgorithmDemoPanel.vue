<script setup lang="ts">
import { computed } from 'vue'
import { Clapperboard, Play } from 'lucide-vue-next'
import type { AlgorithmDemo, AlgorithmId } from '@/data/education/algorithms'

const props = defineProps<{
  demo: AlgorithmDemo
  algorithmId: AlgorithmId
  roundsHint?: string
}>()

const hasVideo = computed(() => Boolean(props.demo.videoSrc))
</script>

<template>
  <div class="algo-demo w-full">
    <div class="mb-4 flex flex-wrap items-center justify-center gap-2 text-center">
      <Clapperboard class="h-4 w-4 text-primary shrink-0" />
      <p class="text-sm font-semibold text-foreground">{{ demo.title }}</p>
      <span class="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
        {{ hasVideo ? 'Video' : 'Animation' }}
      </span>
    </div>
    <p class="mb-5 text-center text-xs text-muted-foreground">{{ demo.description }}</p>

    <div class="algo-demo__stage flex w-full items-center justify-center px-2 py-6 sm:px-4">
      <video
        v-if="hasVideo"
        class="mx-auto max-h-[22rem] w-full max-w-3xl object-contain"
        controls
        playsinline
        :src="demo.videoSrc"
        :aria-label="demo.title"
      />

      <div v-else class="flex w-full flex-col items-center justify-center" :data-scene="demo.animationId">
        <div v-if="demo.animationId === 'aes-rounds'" class="aes-flow mx-auto w-full">
          <div class="aes-flow__rail">
            <span class="aes-chip aes-chip--plain">Plaintext</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--key">{{ algorithmId === 'aes256' ? '256-bit key' : '128-bit key' }}</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--rounds">
              {{ algorithmId === 'aes256' ? '14 rounds' : '10 rounds' }}
            </span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--cipher">Ciphertext</span>
          </div>
          <p class="mt-5 text-center text-xs text-muted-foreground">
            {{ roundsHint || demo.posterLabel }} · SubBytes → ShiftRows → MixColumns → AddRoundKey
          </p>
        </div>

        <div v-else-if="demo.animationId === 'rsa-keys'" class="rsa-flow mx-auto w-full max-w-lg text-center">
          <div class="flex items-center justify-center gap-3 md:gap-6">
            <div class="rsa-key rsa-key--public">
              <Play class="h-4 w-4 mb-1 opacity-70" />
              Public key
            </div>
            <div class="rsa-packet" aria-hidden="true">
              <span class="rsa-packet__lock" />
            </div>
            <div class="rsa-key rsa-key--private">
              Private key
            </div>
          </div>
          <p class="mt-5 text-xs text-muted-foreground">Encrypt with public · decrypt only with private</p>
        </div>

        <div v-else-if="demo.animationId === 'sha-digest'" class="sha-flow mx-auto flex w-full max-w-md flex-col items-center text-center">
          <div class="sha-input">Any file / message</div>
          <div class="sha-funnel" aria-hidden="true" />
          <div class="sha-out">Fixed digest (e.g. SHA-256)</div>
          <p class="mt-5 text-xs text-muted-foreground">One-way · same input → same hash · tiny change → new hash</p>
        </div>

        <div v-else-if="demo.animationId === 'chacha-stream'" class="chacha-flow mx-auto w-full text-center">
          <div class="aes-flow__rail">
            <span class="aes-chip aes-chip--plain">Plaintext</span>
            <span class="chacha-op">⊕</span>
            <span class="aes-chip aes-chip--key chacha-stream">Keystream</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--cipher">Ciphertext</span>
          </div>
          <p class="mt-5 text-xs text-muted-foreground">ChaCha20 generates a keystream, then XORs it with the message</p>
        </div>

        <div v-else-if="demo.animationId === 'siv-flow'" class="aes-flow mx-auto w-full">
          <div class="aes-flow__rail">
            <span class="aes-chip aes-chip--plain">Plaintext</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--rounds">POLYVAL → tag</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--key">tag = IV</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--cipher">AES-CTR → ciphertext</span>
          </div>
          <p class="mt-5 text-center text-xs text-muted-foreground">
            The IV comes from the message itself, so a repeated nonce reveals only “same message twice”
          </p>
        </div>

        <div v-else-if="demo.animationId === 'xchacha-nonce'" class="chacha-flow mx-auto w-full text-center">
          <div class="aes-flow__rail">
            <span class="aes-chip aes-chip--plain">24-byte nonce</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--key">HChaCha20 → subkey</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--key chacha-stream">ChaCha20-Poly1305</span>
            <span class="aes-arrow" aria-hidden="true" />
            <span class="aes-chip aes-chip--cipher">Ciphertext + tag</span>
          </div>
          <p class="mt-5 text-xs text-muted-foreground">
            16 nonce bytes make a fresh subkey; the last 8 feed ordinary ChaCha20-Poly1305
          </p>
        </div>

        <div v-else class="argon-flow mx-auto w-full max-w-md text-center">
          <div class="mb-3 flex justify-center gap-2">
            <span class="aes-chip aes-chip--plain">Password</span>
            <span class="aes-chip aes-chip--key">Salt</span>
          </div>
          <div class="argon-grid" aria-hidden="true">
            <span v-for="i in 24" :key="i" class="argon-cell" :style="{ animationDelay: `${(i % 8) * 0.12}s` }" />
          </div>
          <div class="aes-chip aes-chip--cipher mt-4 inline-flex">Derived hash / key</div>
          <p class="mt-5 text-xs text-muted-foreground">Memory-hard filling makes brute force expensive</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aes-flow__rail {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: max-content;
  max-width: 100%;
  margin-inline: auto;
}

.aes-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-height: 2.4rem;
  padding: 0.4rem 0.85rem;
  border-radius: 0.7rem;
  border: 1px solid var(--border);
  font-size: 0.8rem;
  font-weight: 600;
  background: var(--card);
  color: var(--foreground);
  white-space: nowrap;
}

.aes-chip--plain {
  border-color: color-mix(in oklab, var(--primary) 35%, var(--border));
}

.aes-chip--key {
  color: var(--primary);
  background: color-mix(in oklab, var(--primary) 10%, var(--card));
}

.aes-chip--rounds {
  color: var(--primary);
  border-color: color-mix(in oklab, var(--primary) 40%, var(--border));
  background: color-mix(in oklab, var(--primary) 8%, var(--card));
  animation: round-pop 2.8s ease-in-out infinite;
}

.aes-chip--cipher {
  animation: pulse-soft 2.4s ease-in-out infinite;
}

.aes-arrow {
  flex-shrink: 0;
  width: 1.25rem;
  height: 2px;
  background: color-mix(in oklab, var(--primary) 55%, transparent);
  position: relative;
}

.aes-arrow::after {
  content: '';
  position: absolute;
  right: -1px;
  top: -3px;
  border: 4px solid transparent;
  border-left-color: color-mix(in oklab, var(--primary) 55%, transparent);
}

.rsa-key {
  min-width: 7rem;
  padding: 1rem 0.85rem;
  border-radius: 1rem;
  border: 1px solid var(--border);
  background: var(--card);
  font-size: 0.85rem;
  font-weight: 600;
}

.rsa-key--public {
  animation: slide-in-left 2.8s ease-in-out infinite;
}

.rsa-key--private {
  animation: slide-in-right 2.8s ease-in-out infinite;
  border-color: color-mix(in oklab, var(--primary) 40%, var(--border));
}

.rsa-packet {
  width: 2.4rem;
  height: 2.4rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  animation: hop 1.8s ease-in-out infinite;
}

.rsa-packet__lock {
  width: 1.15rem;
  height: 0.85rem;
  border-radius: 0.2rem;
  background: color-mix(in oklab, var(--primary) 70%, var(--foreground));
  position: relative;
}

.rsa-packet__lock::before {
  content: '';
  position: absolute;
  left: 50%;
  top: -0.55rem;
  width: 0.7rem;
  height: 0.7rem;
  transform: translateX(-50%);
  border: 2px solid color-mix(in oklab, var(--primary) 70%, var(--foreground));
  border-bottom: 0;
  border-radius: 0.55rem 0.55rem 0 0;
}

.sha-input,
.sha-out {
  display: inline-flex;
  padding: 0.65rem 1rem;
  border-radius: 0.75rem;
  border: 1px solid var(--border);
  background: var(--card);
  font-size: 0.85rem;
  font-weight: 600;
}

.sha-funnel {
  width: 3.5rem;
  height: 2.2rem;
  margin: 0.65rem auto;
  clip-path: polygon(10% 0, 90% 0, 62% 100%, 38% 100%);
  background: color-mix(in oklab, var(--primary) 35%, transparent);
  animation: funnel-pulse 2s ease-in-out infinite;
}

.sha-out {
  color: var(--primary);
  animation: pulse-soft 2.2s ease-in-out infinite;
}

.chacha-op {
  flex-shrink: 0;
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--primary);
}

.chacha-stream {
  animation: stream-scan 2s linear infinite;
}

.argon-grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 0.35rem;
  max-width: 16rem;
  margin: 0 auto;
}

.argon-cell {
  aspect-ratio: 1;
  border-radius: 0.25rem;
  background: color-mix(in oklab, var(--primary) 22%, var(--card));
  border: 1px solid color-mix(in oklab, var(--primary) 18%, var(--border));
  animation: cell-fill 2.4s ease-in-out infinite;
}

@keyframes round-pop {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.55;
  }
  35% {
    transform: scale(1.12);
    opacity: 1;
  }
}

@keyframes pulse-soft {
  0%,
  100% {
    opacity: 0.75;
  }
  50% {
    opacity: 1;
  }
}

@keyframes hop {
  0%,
  100% {
    transform: translateX(-6px) scale(0.95);
  }
  50% {
    transform: translateX(6px) scale(1.05);
  }
}

@keyframes slide-in-left {
  0%,
  100% {
    transform: translateX(-4px);
  }
  50% {
    transform: translateX(0);
  }
}

@keyframes slide-in-right {
  0%,
  100% {
    transform: translateX(4px);
  }
  50% {
    transform: translateX(0);
  }
}

@keyframes funnel-pulse {
  0%,
  100% {
    opacity: 0.55;
    transform: scaleY(0.92);
  }
  50% {
    opacity: 1;
    transform: scaleY(1);
  }
}

@keyframes stream-scan {
  0% {
    box-shadow: inset 0 0 0 0 color-mix(in oklab, var(--primary) 25%, transparent);
  }
  50% {
    box-shadow: inset 120px 0 24px -40px color-mix(in oklab, var(--primary) 28%, transparent);
  }
  100% {
    box-shadow: inset 240px 0 24px -40px transparent;
  }
}

@keyframes cell-fill {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.92);
  }
  40% {
    opacity: 1;
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .aes-chip--rounds,
  .aes-chip--cipher,
  .rsa-key--public,
  .rsa-key--private,
  .rsa-packet,
  .sha-funnel,
  .sha-out,
  .chacha-stream,
  .argon-cell {
    animation: none;
  }
}
</style>

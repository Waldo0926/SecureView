<script setup lang="ts">
import SentenceLines from '@/components/SentenceLines.vue'
import { ArrowRight } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import CipherWall from '@/components/brand/CipherWall.vue'
import { useAuthStore } from '@/stores/auth_store'

const auth = useAuthStore()
const standards = ['AES-256-GCM', 'RSA-OAEP', 'Argon2id', 'SHA-256', 'Hash-chained audit']
</script>

<template>
  <!-- The one dark scene on the site: the hero is dark in both themes, everything below follows the theme. -->
  <section class="hero relative overflow-hidden">
    <div class="hero-grid pointer-events-none absolute inset-0" aria-hidden="true" />
    <div class="container relative mx-auto flex min-h-[calc(100svh-5.5rem)] flex-wrap items-center gap-14 px-4 py-20 lg:flex-nowrap lg:py-24">
      <div class="flex w-full min-w-0 flex-col gap-8 lg:w-auto lg:flex-1 lg:basis-[30rem]">
        <p class="inline-flex items-center gap-2.5 font-mono text-xs uppercase tracking-[0.16em] text-[#7ce0b5]">
          <span class="hero-dot h-2 w-2 rounded-full bg-[#7ce0b5]" />
          End-to-end encrypted file sharing
        </p>
        <h1 class="text-5xl font-semibold leading-[1.02] tracking-[-0.045em] text-white sm:text-6xl lg:text-5xl 2xl:text-6xl">
          Your cloud drive can read your files.
          <span class="block text-[#7ce0b5]">We cannot.</span>
        </h1>
        <p class="max-w-xl text-lg leading-relaxed text-[#b7bcc6] md:text-xl">
          <SentenceLines text="Every file is encrypted in your browser before upload. Only you and the people you share it with can open it. Our server only ever stores scrambled bytes." />
        </p>
        <div class="flex flex-wrap items-center gap-3">
          <!-- Signed out, /upload only redirects to sign in, so the first step is an account. -->
          <RouterLink
            :to="auth.isAuthed ? '/upload' : '/register'"
            class="inline-flex h-12 items-center gap-2 rounded-lg bg-white px-7 font-medium text-[#07090d] transition-colors hover:bg-[#e8eaee]"
          >
            {{ auth.isAuthed ? 'Encrypt a file' : 'Get started' }}
            <ArrowRight class="h-4 w-4" />
          </RouterLink>
          <RouterLink
            to="/how-it-works"
            class="inline-flex h-12 items-center rounded-lg border border-white/20 px-7 font-medium text-[#f2f3f5] transition-colors hover:bg-white/10"
          >
            See how it works
          </RouterLink>
        </div>
        <ul class="flex flex-wrap gap-x-6 gap-y-2 border-t border-white/10 pt-6 font-mono text-xs text-[#8a92a3]">
          <li v-for="item in standards" :key="item">{{ item }}</li>
        </ul>
      </div>

      <div class="relative h-[26rem] w-full min-w-0 lg:h-[34rem] lg:w-auto lg:flex-1 lg:basis-[26rem]" data-testid="hero-scene">
        <CipherWall />
        <div class="hero-scan pointer-events-none absolute inset-x-0 top-0 h-24" aria-hidden="true" />
        <div class="hero-card absolute left-1/2 top-1/2 w-[min(24rem,92%)] overflow-hidden rounded-2xl border border-white/10 bg-[#0e1117]/90 backdrop-blur">
          <div class="flex items-center justify-between border-b border-white/10 px-5 py-4">
            <div>
              <div class="text-[0.95rem] font-semibold text-white">board-minutes.pdf</div>
              <div class="font-mono text-xs text-[#8a92a3]">603 bytes · AES-256-GCM</div>
            </div>
            <span class="rounded-md bg-[#7ce0b5] px-2.5 py-1 font-mono text-xs font-medium text-[#07090d]">SEALED</span>
          </div>
          <div class="flex flex-col gap-2.5 px-5 py-4 font-mono text-[0.7rem] sm:text-[0.8rem]">
            <div class="text-[#8a92a3]">your file</div>
            <div class="tracking-[0.05em] text-[#f2f3f5]">25 50 44 46 2d 31 2e 37 0a 31 20 30</div>
            <div class="pt-1.5 text-[#8a92a3]">what the server receives</div>
            <div class="tracking-[0.05em] text-[#7ce0b5]">a1 d6 0d a9 b8 75 31 9d 5f 9d 32 70</div>
          </div>
          <div class="flex flex-col gap-1.5 border-t border-white/10 px-5 py-4">
            <span class="text-xs text-[#8a92a3]">Sealed for demo-bob · key fingerprint</span>
            <span class="font-mono text-sm tracking-[0.08em] text-[#f2f3f5]">3C06 B3AC DFEA A038</span>
          </div>
        </div>
        <p class="absolute -bottom-1 left-0 right-0 text-center font-mono text-[0.7rem] text-[#6b7280]">
          Sample bytes from a real upload.
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.hero {
  background: #07090d;
  color: #f2f3f5;
}
.hero-grid {
  background-image:
    linear-gradient(rgb(255 255 255 / 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgb(255 255 255 / 0.04) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse 90% 80% at 60% 45%, #000 30%, transparent 85%);
}
.hero-scan {
  background: linear-gradient(180deg, transparent, rgb(124 224 181 / 0.14), transparent);
  animation: hero-scan 6s linear infinite;
}
.hero-card {
  transform: translate(-50%, -50%);
  box-shadow: 0 40px 80px -20px rgb(0 0 0 / 0.7);
  animation: hero-float 6s ease-in-out infinite;
}
.hero-dot {
  animation: hero-pulse 2.4s ease-out infinite;
}
@keyframes hero-scan {
  0% { transform: translateY(-120px); }
  100% { transform: translateY(560px); }
}
@keyframes hero-float {
  0%, 100% { transform: translate(-50%, -50%); }
  50% { transform: translate(-50%, calc(-50% - 8px)); }
}
@keyframes hero-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgb(124 224 181 / 0.45); }
  70% { box-shadow: 0 0 0 10px rgb(124 224 181 / 0); }
}
@media (prefers-reduced-motion: reduce) {
  .hero-scan, .hero-card, .hero-dot { animation: none; }
}
</style>

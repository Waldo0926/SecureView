<script setup lang="ts">
import SentenceLines from '@/components/SentenceLines.vue'
import { ArrowRight, FileLock2, KeyRound, LockKeyhole, Maximize2, Share2, UserPlus, X } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import PageHeader from '@/components/securfile/PageHeader.vue'
import SecurityStory from '@/components/explainers/SecurityStory.vue'
import WhySecureView from '@/components/explainers/WhySecureView.vue'
import { useAuthStore } from '@/stores/auth_store'

/**
 * One page that explains SecureView to someone new: what happens to a file (animated), why that
 * is better than ordinary cloud storage, and how to get started. The Help page links here, and
 * so does the home page.
 */
const auth = useAuthStore()
const route = useRoute()

// `?present` shows only the explainer, full screen, playing from the start: for projecting it in a
// presentation, and for recording the explainer video (frontend/scripts/record-walkthroughs.mjs).
const presenting = computed(() => 'present' in route.query)

const steps = [
  {
    icon: UserPlus,
    title: 'Create your account',
    body:
      'Register with your email (we send a code). You choose two different secrets: a password to ' +
      'sign in, and an encryption passphrase of at least 10 characters that protects your key.',
    tip: 'Download the private key file when offered. With it you can reset a forgotten passphrase.',
    to: '/register',
    cta: 'Register',
  },
  {
    icon: FileLock2,
    title: 'Encrypt and upload',
    body:
      'On Upload, choose files and press Start Encryption. Your browser encrypts each one before it ' +
      'is sent; AES-256-GCM is the default.',
    tip: 'Up to 500 MB per file. The encrypted copy is the same size as the original — that is expected.',
    to: '/upload',
    cta: 'Upload',
  },
  {
    icon: Share2,
    title: 'Share with a named person',
    body:
      'In My Files, press Share and enter the other person’s username or email. Your browser re-seals ' +
      'the file key for them; you can revoke it later.',
    tip: 'They need a SecureView account. Sharing asks for your passphrase once, to open your key.',
    to: '/files',
    cta: 'My Files',
  },
  {
    icon: KeyRound,
    title: 'Download, decrypt, check',
    body:
      'Download and decrypt asks for your passphrase and gives you back the original file, checked ' +
      'against its fingerprint. The Activity Log shows every upload, share and download.',
    tip: 'A changed file is refused rather than handed to you, and can be restored by an administrator.',
    to: '/audit-logs',
    cta: 'Activity Log',
  },
]
</script>

<template>
  <div
    v-if="presenting"
    class="fixed inset-0 z-[100] flex flex-col items-center justify-center overflow-auto bg-background p-6"
    data-testid="story-present"
  >
    <RouterLink
      to="/how-it-works"
      class="absolute right-4 top-4 inline-flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground hover:bg-secondary"
      aria-label="Leave full screen"
    >
      <X class="h-4 w-4" />
    </RouterLink>
    <p class="mb-4 text-xs uppercase font-mono tracking-[0.14em] text-muted-foreground">SecureView · how your file stays private</p>
    <div class="w-full max-w-5xl">
      <SecurityStory autoplay compact :scene-ms="'fast' in route.query ? 6000 : 8000" />
    </div>
  </div>
  <div v-else>
    <section class="py-16 md:py-20">
      <div class="page-container">
        <PageHeader
          eyebrow="How it works"
          title="Locked before it leaves your computer"
          subtitle="Follow one file from Alice to Bob. Press play, or step through at your own pace."
        />
        <SecurityStory />
        <div class="mt-4 text-center">
          <RouterLink
            to="/how-it-works?present"
            class="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
          >
            <Maximize2 class="h-4 w-4" /> Full screen, for presenting
          </RouterLink>
        </div>
      </div>
    </section>

    <section class="bg-secondary/30 py-16 md:py-20" aria-labelledby="why-heading">
      <div class="page-container">
        <div class="mx-auto mb-10 max-w-3xl text-center">
          <p class="mb-3 text-xs uppercase font-mono tracking-[0.14em] text-muted-foreground">Why it is different</p>
          <h2 id="why-heading" class="text-balance text-3xl font-bold tracking-tight text-foreground md:text-4xl">
            What ordinary cloud storage cannot promise
          </h2>
          <p class="mx-auto mt-4 max-w-2xl text-pretty text-muted-foreground">
            Most services encrypt files on their own servers, with keys they hold. SecureView never has
            your key, so it cannot read your files — and neither can anyone who breaks into it.
          </p>
        </div>
        <WhySecureView />
      </div>
    </section>

    <section class="py-16 md:py-20" aria-labelledby="start-heading">
      <div class="page-container">
        <div class="mx-auto mb-10 max-w-3xl text-center">
          <p class="mb-3 text-xs uppercase font-mono tracking-[0.14em] text-muted-foreground">Get started</p>
          <h2 id="start-heading" class="text-balance text-3xl font-bold tracking-tight text-foreground md:text-4xl">
            Four steps to your first secure share
          </h2>
        </div>

        <div class="mb-8 flex items-start gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-foreground">
          <LockKeyhole class="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
          <p>
            <span class="font-semibold">Two secrets, two jobs.</span> Your <em>password</em> signs you in and
            can be reset by email. Your <em>encryption passphrase</em> opens your files; we never see it and
            cannot reset it for you. The private key file you download at sign-up lets you set a new one
            yourself, so keep it somewhere safe. Lose both, and the files cannot be recovered by anyone.
          </p>
        </div>

        <ol class="grid gap-4 md:grid-cols-2">
          <li v-for="(step, i) in steps" :key="step.title" class="flex flex-col rounded-2xl border border-border bg-card p-5">
            <div class="flex items-center gap-3">
              <span class="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">{{ i + 1 }}</span>
              <component :is="step.icon" class="h-5 w-5 text-primary" />
              <h3 class="font-semibold text-foreground">{{ step.title }}</h3>
            </div>
            <p class="mt-3 text-sm leading-relaxed text-muted-foreground">{{ step.body }}</p>
            <p class="mt-2 text-sm text-foreground"><span class="font-medium text-primary">Tip:</span> <SentenceLines :text="step.tip" /></p>
            <RouterLink
              v-if="step.to !== '/register' || !auth.isAuthed"
              :to="step.to"
              class="mt-4 inline-flex w-fit items-center gap-1.5 text-sm font-medium text-primary hover:underline"
            >
              {{ step.cta }} <ArrowRight class="h-4 w-4" />
            </RouterLink>
          </li>
        </ol>

        <div class="mt-10 flex flex-wrap justify-center gap-3">
          <RouterLink to="/help" class="inline-flex h-11 items-center gap-2 rounded-full bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            Watch the walkthrough videos <ArrowRight class="h-4 w-4" />
          </RouterLink>
          <RouterLink to="/#how-it-works" class="inline-flex h-11 items-center gap-2 rounded-full border border-border px-6 text-sm font-medium text-foreground hover:bg-secondary">
            Picture guide with real screenshots
          </RouterLink>
        </div>
      </div>
    </section>
  </div>
</template>

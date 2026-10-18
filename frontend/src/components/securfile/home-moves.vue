<script setup lang="ts">
/**
 * The home page's feature overview. It replaces the old scrolling wall of icon cards: the same
 * information, said as the three things the product does, each with the real artefact it produces.
 * Keep id="features": the header and footer "Product" links point at it.
 */
import { proof } from '@/data/proof'
const alsoIncluded = [
  'Folders and search',
  'Who opened a file',
  'Six ciphers',
  'Daily integrity scan',
  'Revoke access any time',
  'English and 简体中文',
]
</script>

<template>
  <section id="features" class="scroll-mt-24 bg-background" aria-labelledby="moves-heading">
    <div class="border-y border-border bg-card">
      <div class="container mx-auto px-4 py-12">
        <ul class="grid grid-cols-2 gap-x-6 gap-y-8 lg:grid-cols-4" data-testid="home-proof">
          <li v-for="item in proof" :key="item.value" class="flex flex-col gap-2">
            <span class="text-4xl font-semibold tracking-[-0.03em] text-foreground md:text-5xl">{{ item.value }}</span>
            <span class="text-sm leading-relaxed text-muted-foreground">{{ item.label }}</span>
          </li>
        </ul>
        <p class="mt-8 font-mono text-xs text-muted-foreground">From our own test runs on the live site; the reports are in the project documentation.</p>
      </div>
    </div>

    <div class="container mx-auto px-4 py-24">
      <div class="mb-12 flex flex-col items-center gap-4 text-center">
        <p class="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">How it works</p>
        <h2 id="moves-heading" class="text-balance text-4xl font-semibold leading-[1.1] md:text-5xl">
          What happens to your file
        </h2>
      </div>
      <div class="grid gap-6 lg:grid-cols-3">
        <article class="flex flex-col gap-5 rounded-xl border border-border bg-card p-7">
          <span class="font-mono text-xs text-muted-foreground">01 · Encrypt</span>
          <h3 class="text-xl font-semibold xl:text-2xl">Encrypted before upload</h3>
          <p class="leading-relaxed text-muted-foreground">
            Every file gets its own random key and is encrypted in your browser, up to 500 MB. Your passphrase
            stays on your device, where Argon2id turns it into the key that opens your private key.
          </p>
          <p class="mt-auto rounded-lg bg-secondary px-4 py-3 font-mono text-xs">
            AES key wrapped with RSA-OAEP
          </p>
        </article>
        <article class="flex flex-col gap-5 rounded-xl border border-border bg-card p-7">
          <span class="font-mono text-xs text-muted-foreground">02 · Share</span>
          <h3 class="text-xl font-semibold xl:text-2xl">Shared with one person</h3>
          <p class="leading-relaxed text-muted-foreground">
            You pick a SecureView account and check their key fingerprint before anything is sent. There is no
            public link that could leak, and you can revoke access later.
          </p>
          <p class="mt-auto rounded-lg bg-secondary px-4 py-3 font-mono text-xs tracking-[0.06em]">
            Bob's key: 3C06 B3AC DFEA A038
          </p>
        </article>
        <article class="flex flex-col gap-5 rounded-xl border border-border bg-card p-7">
          <span class="font-mono text-xs text-muted-foreground">03 · Check</span>
          <h3 class="text-xl font-semibold xl:text-2xl">Checked before download</h3>
          <p class="leading-relaxed text-muted-foreground">
            Before a download, the file is checked against its recorded SHA-256 and the audit chain, then
            decrypted in your browser. A daily scan also checks every stored file.
          </p>
          <p class="mt-auto flex flex-wrap gap-2.5 font-mono text-xs">
            <span class="rounded-lg bg-success-soft px-3 py-2 text-success">● Verified</span>
            <span class="rounded-lg bg-destructive-soft px-3 py-2 text-destructive">● Modified, refused</span>
          </p>
        </article>
      </div>
      <ul class="mt-10 flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-6 text-sm text-muted-foreground">
        <li v-for="item in alsoIncluded" :key="item">{{ item }}</li>
      </ul>
    </div>
  </section>
</template>

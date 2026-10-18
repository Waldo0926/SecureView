<script setup lang="ts">
import SentenceLines from '@/components/SentenceLines.vue'
import { ArrowLeft, Compass } from 'lucide-vue-next'
import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section class="py-24 md:py-32">
    <div class="container mx-auto px-4">
      <div class="mx-auto max-w-xl text-center" data-testid="not-found">
        <div class="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Compass class="h-7 w-7" />
        </div>
        <p class="text-sm uppercase tracking-[0.22em] text-muted-foreground">Error 404</p>
        <h1 class="mt-3 text-balance text-3xl font-bold text-foreground md:text-4xl">We can't find that page</h1>
        <p class="mt-4 text-muted-foreground">
          There is nothing at
          <code class="break-all rounded bg-secondary px-1.5 py-0.5 text-sm text-foreground">{{ route.path }}</code>.
        </p>
        <p class="mt-1 text-muted-foreground">
          <SentenceLines text="The link may be mistyped or out of date. Your files and keys are not affected." />
        </p>
        <div class="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <RouterLink
            to="/"
            class="inline-flex h-11 items-center gap-2 rounded-full bg-primary px-6 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <ArrowLeft class="h-4 w-4" />
            Back to home
          </RouterLink>
          <RouterLink
            to="/help"
            class="inline-flex h-11 items-center rounded-full border border-border px-6 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
          >
            Open Help
          </RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>
